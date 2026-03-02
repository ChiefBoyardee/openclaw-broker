"""
OpenClaw Broker — FastAPI service for a tiny job queue (SQLite-backed).

Schema (compatible with your existing DB):
  jobs(
    id TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,         # epoch seconds
    status TEXT NOT NULL,                # queued|running|done|failed
    command TEXT NOT NULL,
    payload TEXT NOT NULL,
    result TEXT,
    finished_at INTEGER,                 # epoch seconds
    error TEXT,                          # set when status=failed (Sprint 1)
    started_at INTEGER,                  # set on claim (Sprint 1)
    lease_until INTEGER,                 # set on claim; used for requeue (Sprint 1)
    worker_id TEXT,                      # set on claim (Sprint 2)
    requires TEXT                        # optional; JSON e.g. {"caps":["llm:vllm"]} (Sprint 5)
  )

Endpoints:
  - GET  /health                 (no auth)
  - POST /jobs                   (X-Bot-Token)
  - GET  /jobs/{job_id}          (X-Bot-Token)
  - GET  /jobs/next              (X-Worker-Token)  [atomic claim + lease + requeue]
  - POST /jobs/{job_id}/result   (X-Worker-Token)  [idempotent]
  - POST /jobs/{job_id}/fail     (X-Worker-Token)  [worker failure]

Auth:
  - X-Bot-Token for bot operations (create/read)
  - X-Worker-Token for worker operations (claim/finish/fail)

Notes:
  - Uses BEGIN IMMEDIATE for atomic claim; stale running jobs are requeued when lease_until < now.
  - Keeps minimal dependencies and simple logging.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
import uuid
from collections import defaultdict
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from broker.caps import is_command_allowed, job_matches_worker, parse_worker_caps

DB_PATH = os.environ.get("BROKER_DB", "/var/lib/openclaw-broker/broker.db")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
LEASE_SECONDS = int(os.environ.get("LEASE_SECONDS", "60"))
_raw_max_queued = os.environ.get("MAX_QUEUED_JOBS", "").strip()
MAX_QUEUED_JOBS: Optional[int] = int(_raw_max_queued) if _raw_max_queued else None

# Sprint 3: rate limit and request limits
_raw_rate = os.environ.get("RATE_LIMIT_JOBS_PER_MIN", "").strip()
RATE_LIMIT_JOBS_PER_MIN: Optional[int] = int(_raw_rate) if _raw_rate and int(_raw_rate) > 0 else None
_raw_body = os.environ.get("MAX_REQUEST_BODY_BYTES", "").strip()
MAX_REQUEST_BODY_BYTES = int(_raw_body) if _raw_body and int(_raw_body) > 0 else 524288  # 512KB default
MAX_PAYLOAD_BYTES = 262144  # 256KB
MAX_REQUIRES_BYTES = 2048  # 2KB

# Rate limit: token_hash -> list of create timestamps in last 60s (purged periodically)
_rate_limit_store: dict[str, list[float]] = defaultdict(list)

app = FastAPI(title="OpenClaw Broker")

# Standard job JSON keys (null if absent)
JOB_KEYS = (
    "id",
    "created_at",
    "started_at",
    "finished_at",
    "lease_until",
    "status",
    "command",
    "payload",
    "result",
    "error",
    "worker_id",
    "requires",
)


# ----------------------------
# DB helpers
# ----------------------------
def db_conn() -> sqlite3.Connection:
    # timeout helps when runner polls rapidly while a write txn is happening
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def columns(conn: sqlite3.Connection) -> set[str]:
    """Return set of column names for jobs table (from PRAGMA table_info)."""
    rows = conn.execute("PRAGMA table_info(jobs)").fetchall()
    return {row[1] for row in rows}


def row_to_job_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    """Convert a sqlite3.Row to a dict with all standard job keys (null if absent)."""
    if row is None:
        return None
    d = dict(row)
    out = {}
    for k in JOB_KEYS:
        out[k] = d.get(k)
    return out


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY,
              created_at INTEGER NOT NULL,
              status TEXT NOT NULL,
              command TEXT NOT NULL,
              payload TEXT NOT NULL,
              result TEXT,
              finished_at INTEGER
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at)"
        )


def migrate_db() -> None:
    """Add Sprint 1 columns and index if missing. Safe to run repeatedly."""
    with db_conn() as conn:
        cur_cols = columns(conn)
        if "error" not in cur_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN error TEXT")
        if "started_at" not in cur_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN started_at INTEGER")
        if "lease_until" not in cur_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN lease_until INTEGER")
        if "worker_id" not in cur_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN worker_id TEXT")
        if "requires" not in cur_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN requires TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_lease ON jobs(status, lease_until)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_worker_id ON jobs(worker_id)")


def enable_wal() -> None:
    """Enable WAL mode and recommended pragmas. Call after init_db/migrate_db. Also sets PRAGMA synchronous=NORMAL (recommended with WAL)."""
    with db_conn() as conn:
        row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        mode = (row[0] or "").strip().lower() if row else ""
        if mode != "wal":
            raise RuntimeError(f"PRAGMA journal_mode=WAL did not stick: got {mode!r}")
        conn.execute("PRAGMA synchronous=NORMAL")
    return None


init_db()
migrate_db()
enable_wal()


# ----------------------------
# Auth (Depends style)
# ----------------------------
def require_worker_token(
    x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"),
) -> None:
    if not WORKER_TOKEN:
        raise HTTPException(500, "WORKER_TOKEN not configured")
    if not x_worker_token or x_worker_token != WORKER_TOKEN:
        raise HTTPException(401, "bad worker token")


def require_bot_token(
    x_bot_token: Optional[str] = Header(default=None, alias="X-Bot-Token"),
) -> None:
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN not configured")
    if not x_bot_token or x_bot_token != BOT_TOKEN:
        raise HTTPException(401, "bad bot token")


# ----------------------------
# Capability matching (Sprint 5) — see broker.caps
# ----------------------------


# ----------------------------
# Audit (Sprint 3) — structured events, no secrets
# ----------------------------
def _audit(event: str, **kwargs: Any) -> None:
    """Emit structured audit line to stderr. No tokens or payload content."""
    parts = [f"event={event}"]
    for k, v in kwargs.items():
        if v is not None:
            parts.append(f"{k}={v}")
    print(" ".join(parts), file=sys.stderr)


# ----------------------------
# Models
# ----------------------------
class JobCreate(BaseModel):
    command: str
    payload: str
    requires: Optional[str] = None


class JobResult(BaseModel):
    result: str


class JobFail(BaseModel):
    error: str = "unknown"


# ----------------------------
# Routes
# ----------------------------
@app.get("/health")
def health():
    # Keep compatibility with your existing checks
    return {"ok": True, "ts_bound": True}


def _rate_limit_check(x_bot_token: Optional[str]) -> None:
    """Raise 429 if over rate limit. Key by token hash."""
    if RATE_LIMIT_JOBS_PER_MIN is None or not x_bot_token:
        return
    now = time.time()
    key = hashlib.sha256(x_bot_token.encode()).hexdigest()[:16]
    window_start = now - 60
    # Purge old entries
    _rate_limit_store[key] = [t for t in _rate_limit_store[key] if t > window_start]
    if len(_rate_limit_store[key]) >= RATE_LIMIT_JOBS_PER_MIN:
        _audit("job_rejected_rate_limit")
        raise HTTPException(429, detail="rate limit exceeded")
    _rate_limit_store[key].append(now)


@app.post("/jobs", dependencies=[Depends(require_bot_token)])
async def create_job(
    request: Request,
    x_bot_token: Optional[str] = Header(default=None, alias="X-Bot-Token"),
):
    # Read body with size limit (Sprint 3)
    body_bytes = b""
    async for chunk in request.stream():
        body_bytes += chunk
        if len(body_bytes) > MAX_REQUEST_BODY_BYTES:
            _audit("job_rejected", reason="body_too_large")
            raise HTTPException(413, detail="request body too large")
    try:
        data = json.loads(body_bytes) if body_bytes else {}
    except json.JSONDecodeError:
        raise HTTPException(400, detail="invalid JSON")

    command = (data.get("command") or "").strip()
    payload = data.get("payload") or ""
    requires_raw = data.get("requires")
    if requires_raw is None:
        requires = None
    elif isinstance(requires_raw, str):
        requires = requires_raw
    else:
        requires = json.dumps(requires_raw)

    # Command allowlist (Sprint 3)
    if not is_command_allowed(command):
        _audit("job_rejected", reason="invalid_command", command=command)
        raise HTTPException(400, detail="invalid command")

    # Payload and requires size caps
    payload_bytes = len((payload or "").encode("utf-8"))
    requires_bytes = len((requires or "").encode("utf-8"))
    if payload_bytes > MAX_PAYLOAD_BYTES:
        _audit("job_rejected", reason="payload_too_large")
        raise HTTPException(400, detail="payload too large")
    if requires_bytes > MAX_REQUIRES_BYTES:
        _audit("job_rejected", reason="requires_too_large")
        raise HTTPException(400, detail="requires too large")

    # Rate limit (Sprint 3)
    _rate_limit_check(x_bot_token)

    jid = str(uuid.uuid4())
    now = int(time.time())
    with db_conn() as conn:
        if MAX_QUEUED_JOBS is not None and MAX_QUEUED_JOBS > 0:
            (cur_count,) = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchone()
            if cur_count >= MAX_QUEUED_JOBS:
                _audit("job_rejected", reason="queue_cap")
                raise HTTPException(429, detail="job queue limit reached")
        conn.execute(
            "INSERT INTO jobs(id, created_at, status, command, payload, requires) VALUES(?,?,?,?,?,?)",
            (jid, now, "queued", command, payload, requires),
        )
    _audit("job_created", job_id=jid, command=command)
    return {"id": jid, "status": "queued"}


@app.get("/jobs/next", dependencies=[Depends(require_worker_token)])
def next_job(
    x_worker_id: Optional[str] = Header(default=None, alias="X-Worker-Id"),
    x_worker_caps: Optional[str] = Header(default=None, alias="X-Worker-Caps"),
):
    """
    Claim the next queued job. Inside one BEGIN IMMEDIATE transaction:
    1) Requeue stale running jobs (lease_until < now); clear worker_id
    2) Select oldest queued job that matches worker caps (requires IS NULL or required caps ⊆ worker caps)
    3) Claim it with started_at, lease_until, worker_id; clear result/error/finished_at
    """
    now = int(time.time())
    lease_until = now + LEASE_SECONDS
    worker_id = (x_worker_id or "").strip() or None
    worker_caps = parse_worker_caps(x_worker_caps)
    with db_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        # 1) Requeue stale running jobs; clear worker_id
        conn.execute(
            """UPDATE jobs
               SET status='queued', started_at=NULL, lease_until=NULL,
                   finished_at=NULL, result=NULL, error=NULL, worker_id=NULL
               WHERE status='running' AND lease_until IS NOT NULL AND lease_until < ?""",
            (now,),
        )
        # 2) Select oldest queued jobs and pick first that matches worker caps
        rows = conn.execute(
            "SELECT id, requires FROM jobs WHERE status='queued' ORDER BY created_at ASC LIMIT 50"
        ).fetchall()
        job_id = None
        for row in rows:
            if job_matches_worker(row["requires"], worker_caps):
                job_id = row["id"]
                break
        if not job_id:
            conn.execute("COMMIT")
            return {"job": None}
        # 3) Claim: set running, started_at, lease_until, worker_id; clear result/error/finished_at
        cur = conn.execute(
            """UPDATE jobs
               SET status='running', started_at=?, lease_until=?, worker_id=?,
                   error=NULL, result=NULL, finished_at=NULL
               WHERE id=? AND status='queued'""",
            (now, lease_until, worker_id, job_id),
        )
        if cur.rowcount != 1:
            conn.execute("COMMIT")
            return {"job": None}

        # Re-fetch to get standardized shape (row may have old columns only before migration)
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        conn.execute("COMMIT")
        _audit("job_claimed", job_id=job_id, worker_id=worker_id)
        return {"job": row_to_job_dict(row)}


@app.get("/jobs/{job_id}", dependencies=[Depends(require_bot_token)])
def get_job(job_id: str):
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "job not found")
        return row_to_job_dict(row)


@app.post("/jobs/{job_id}/result", dependencies=[Depends(require_worker_token)])
def finish_job(job_id: str, body: JobResult):
    """
    Finish a job. Idempotent: if already done/failed return 200 with no change.
    Finish-without-claim (queued) returns 400.
    """
    with db_conn() as conn:
        row = conn.execute(
            "SELECT status FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "job not found")

        status = row["status"]
        if status == "done":
            return {"ok": True, "status": "done"}
        if status == "failed":
            return {"ok": True, "status": "failed", "note": "already failed; result ignored"}
        if status == "queued":
            raise HTTPException(400, "job not in running state: queued")

        # status == "running"
        now = int(time.time())
        conn.execute(
            "UPDATE jobs SET status='done', result=?, finished_at=?, lease_until=NULL WHERE id=?",
            (body.result, now, job_id),
        )
    _audit("job_done", job_id=job_id)
    return {"ok": True, "status": "done"}


@app.post("/jobs/{job_id}/fail", dependencies=[Depends(require_worker_token)])
def fail_job(job_id: str, body: JobFail):
    """
    Mark a job as failed (worker token). Idempotent when already done/failed.
    """
    with db_conn() as conn:
        row = conn.execute(
            "SELECT status FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "job not found")

        status = row["status"]
        if status == "done":
            return {"ok": True, "status": "done", "note": "already done; fail ignored"}
        if status == "failed":
            return {"ok": True, "status": "failed"}

        # queued or running
        err = (body.error or "").strip() or "unknown"
        now = int(time.time())
        conn.execute(
            "UPDATE jobs SET status='failed', error=?, finished_at=?, lease_until=NULL WHERE id=?",
            (err, now, job_id),
        )
    _audit("job_failed", job_id=job_id)
    return {"ok": True, "status": "failed"}


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("BROKER_HOST", "127.0.0.1")
    port = int(os.environ.get("BROKER_PORT", "8000"))
    if host == "0.0.0.0" and os.environ.get("BROKER_BIND_PUBLIC", "").strip() != "1":
        print(
            "[broker] WARNING: BROKER_HOST=0.0.0.0 binds to all interfaces. "
            "Set BROKER_BIND_PUBLIC=1 to suppress this warning.",
            file=sys.stderr,
        )
    uvicorn.run(app, host=host, port=port)
