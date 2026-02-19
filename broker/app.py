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
    worker_id TEXT                       # set on claim (Sprint 2)
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

import os
import sqlite3
import time
import uuid
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

DB_PATH = os.environ.get("BROKER_DB", "/var/lib/openclaw-broker/broker.db")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
LEASE_SECONDS = int(os.environ.get("LEASE_SECONDS", "60"))

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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_lease ON jobs(status, lease_until)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_worker_id ON jobs(worker_id)")


init_db()
migrate_db()


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
# Models
# ----------------------------
class JobCreate(BaseModel):
    command: str
    payload: str


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


@app.post("/jobs", dependencies=[Depends(require_bot_token)])
def create_job(job: JobCreate):
    jid = str(uuid.uuid4())
    now = int(time.time())
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO jobs(id, created_at, status, command, payload) VALUES(?,?,?,?,?)",
            (jid, now, "queued", job.command, job.payload),
        )
    return {"id": jid, "status": "queued"}


@app.get("/jobs/next", dependencies=[Depends(require_worker_token)])
def next_job(
    x_worker_id: Optional[str] = Header(default=None, alias="X-Worker-Id"),
):
    """
    Claim the next queued job. Inside one BEGIN IMMEDIATE transaction:
    1) Requeue stale running jobs (lease_until < now); clear worker_id
    2) Select oldest queued job
    3) Claim it with started_at, lease_until, worker_id; clear result/error/finished_at
    """
    now = int(time.time())
    lease_until = now + LEASE_SECONDS
    worker_id = (x_worker_id or "").strip() or None
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
        # 2) Select oldest queued job
        row = conn.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if not row:
            conn.execute("COMMIT")
            return {"job": None}

        job_id = row["id"]
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
    return {"ok": True, "status": "failed"}


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("BROKER_HOST", "127.0.0.1")
    port = int(os.environ.get("BROKER_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
