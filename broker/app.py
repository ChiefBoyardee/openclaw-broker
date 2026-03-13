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
import logging
import os
import sqlite3
import sys
import time
import uuid
from collections import defaultdict
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from broker.caps import is_command_allowed, job_matches_worker, job_required_caps, parse_worker_caps

logger = logging.getLogger(__name__)
from broker.streaming import (
    ChunkType,
    JobChunk,
    JobToolCall,
    ToolCallStatus,
    get_stream_manager,
)

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

# Streaming configuration
ENABLE_STREAMING = os.environ.get("ENABLE_STREAMING", "true").lower() in ("true", "1", "yes")
MAX_CHUNK_AGE_SECONDS = int(os.environ.get("MAX_CHUNK_AGE_SECONDS", "3600"))

app = FastAPI(title="OpenClaw Broker")

# Initialize streaming manager if enabled
stream_manager = get_stream_manager(DB_PATH) if ENABLE_STREAMING else None

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
        logger.warning(f"Worker token mismatch: received={x_worker_token[:20] if x_worker_token else None}..., expected={WORKER_TOKEN[:20]}...")
        raise HTTPException(401, "bad worker token")


def require_bot_token(
    x_bot_token: Optional[str] = Header(default=None, alias="X-Bot-Token"),
) -> None:
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN not configured")
    if not x_bot_token or x_bot_token != BOT_TOKEN:
        logger.warning(f"Bot token mismatch: received={x_bot_token[:20] if x_bot_token else None}..., expected={BOT_TOKEN[:20]}...")
        raise HTTPException(401, "bad bot token")


def require_any_token(
    x_bot_token: Optional[str] = Header(default=None, alias="X-Bot-Token"),
    x_worker_token: Optional[str] = Header(default=None, alias="X-Worker-Token"),
) -> None:
    """Accept either bot token or worker token for job visibility endpoints."""
    if x_bot_token and x_bot_token == BOT_TOKEN:
        return
    if x_worker_token and x_worker_token == WORKER_TOKEN:
        return
    # Log detailed diagnostics for failed auth
    logger.warning(f"Token auth failed: bot_token_present={bool(x_bot_token)}, worker_token_present={bool(x_worker_token)}, "
                  f"bot_match={x_bot_token == BOT_TOKEN if x_bot_token else False}, "
                  f"worker_match={x_worker_token == WORKER_TOKEN if x_worker_token else False}")
    raise HTTPException(401, "bad token")


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


# Streaming models
class ChunkCreate(BaseModel):
    chunk_type: str
    content: Optional[str] = None
    metadata: Optional[dict] = None


class ChunkList(BaseModel):
    chunks: list
    total_count: int


class ToolCallCreate(BaseModel):
    tool_name: str
    tool_args: Optional[dict] = None


class ToolCallResult(BaseModel):
    result: str


class ToolCallFail(BaseModel):
    error: str


# ----------------------------
# Routes
# ----------------------------
@app.get("/health")
def health():
    # Keep compatibility with your existing checks
    return {"ok": True, "ts_bound": True}


@app.get("/capabilities", dependencies=[Depends(require_bot_token)])
def get_capabilities():
    """Return broker capabilities including streaming support."""
    return {
        "streaming_enabled": ENABLE_STREAMING,
        "streaming_endpoints": {
            "chunks": "/jobs/{id}/chunks",
            "stream": "/jobs/{id}/stream",
            "tool_calls": "/jobs/{id}/tool_calls",
        },
        "chunk_types": [
            ChunkType.THINKING,
            ChunkType.TOOL_CALL,
            ChunkType.TOOL_RESULT,
            ChunkType.MESSAGE,
            ChunkType.PROGRESS,
            ChunkType.FINAL,
            ChunkType.HEARTBEAT,
        ],
        "version": "2.0-agentic",
    }


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
        stale_reclaimed = conn.execute(
            """UPDATE jobs
               SET status='queued', started_at=NULL, lease_until=NULL,
                   finished_at=NULL, result=NULL, error=NULL, worker_id=NULL
               WHERE status='running' AND lease_until IS NOT NULL AND lease_until < ?""",
            (now,),
        ).rowcount

        # 2) Select oldest queued jobs and pick first that matches worker caps
        rows = conn.execute(
            "SELECT id, requires, command FROM jobs WHERE status='queued' ORDER BY created_at ASC LIMIT 50"
        ).fetchall()

        # Diagnostic logging
        total_queued = len(rows)
        caps_str = ",".join(sorted(worker_caps)) if worker_caps else "(none)"

        job_id = None
        skipped_reasons = []
        for row in rows:
            if job_matches_worker(row["requires"], worker_caps):
                job_id = row["id"]
                break
            else:
                # Log why job was skipped
                req_caps = job_required_caps(row["requires"])
                if req_caps:
                    skipped_reasons.append(f"{row['id'][:8]}... (requires: {req_caps}, has: {worker_caps})")

        if not job_id:
            conn.execute("COMMIT")
            if total_queued > 0:
                # Jobs exist but none match - this is important diagnostic info
                logger.info(f"Worker {worker_id} polled: {total_queued} queued job(s), 0 matched caps. "
                           f"Worker caps: [{caps_str}]. Skipped {len(skipped_reasons)} job(s) due to capability mismatch")
                if skipped_reasons[:3]:  # Log first 3 for debugging
                    for reason in skipped_reasons[:3]:
                        logger.debug(f"  Skipped: {reason}")
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
            logger.warning(f"Worker {worker_id} failed to claim job {job_id[:8]}... - race condition (job no longer queued)")
            return {"job": None}

        # Re-fetch to get standardized shape (row may have old columns only before migration)
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        conn.execute("COMMIT")

    # Force WAL checkpoint in a fresh connection to ensure job is visible
    try:
        with db_conn() as checkpoint_conn:
            checkpoint_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as e:
        logger.warning(f"WAL checkpoint failed (non-fatal): {e}")

    # Success logging with diagnostics
    job_command = row["command"] if row else "unknown"
    logger.info(f"Worker {worker_id} claimed job {job_id[:8]}... (command: {job_command}). "
               f"Queued before claim: {total_queued}. Stale jobs requeued: {stale_reclaimed}")
    _audit("job_claimed", job_id=job_id, worker_id=worker_id)
    return {"job": row_to_job_dict(row)}


@app.get("/jobs/{job_id}", dependencies=[Depends(require_any_token)])
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


# ----------------------------
# Streaming Routes (Agentic Job Streaming)
# ----------------------------

@app.post("/jobs/{job_id}/chunks", dependencies=[Depends(require_worker_token)])
def add_job_chunk(job_id: str, body: ChunkCreate):
    """
    Add a chunk to a job stream. Used by runners to stream intermediate results.
    """
    if not ENABLE_STREAMING or not stream_manager:
        raise HTTPException(503, "streaming not enabled")

    # Verify job exists and is running (with retry for WAL mode visibility)
    row = None
    for attempt in range(3):  # Try 3 times with small delays
        with db_conn() as conn:
            row = conn.execute(
                "SELECT status FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row:
            break
        if attempt < 2:  # Don't sleep on last attempt
            time.sleep(0.05 * (attempt + 1))  # 50ms, then 100ms

    # Debug: log what we found
    if not row:
        # Check if job exists at all (including done/failed)
        with db_conn() as conn:
            all_jobs = conn.execute(
                "SELECT id, status FROM jobs WHERE id LIKE ?",
                (job_id[:8] + "%",),
            ).fetchall()
        logger.warning(f"Chunk post for job {job_id}: not found after 3 attempts. Similar jobs: {[dict(r) for r in all_jobs]}")
        raise HTTPException(404, "job not found")

    if row["status"] not in ("running", "queued"):
        # Still allow chunks for done/failed jobs briefly (final messages)
        pass

    chunk_id = stream_manager.add_chunk(
        job_id=job_id,
        chunk_type=body.chunk_type,
        content=body.content,
        metadata=body.metadata,
    )

    return {"ok": True, "chunk_id": chunk_id}


@app.get("/jobs/{job_id}/chunks", dependencies=[Depends(require_bot_token)])
def get_job_chunks(
    job_id: str,
    after_id: Optional[int] = None,
    chunk_type: Optional[str] = None,
    limit: int = 100,
):
    """
    Get chunks for a job. Used by bots to poll for streaming results.
    """
    if not ENABLE_STREAMING or not stream_manager:
        raise HTTPException(503, "streaming not enabled")

    # Verify job exists
    with db_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()

    if not row:
        raise HTTPException(404, "job not found")

    chunk_types = [chunk_type] if chunk_type else None
    chunks = stream_manager.get_chunks(job_id, after_id, chunk_types, limit)

    return {
        "chunks": [
            {
                "id": c.id,
                "chunk_type": c.chunk_type,
                "content": c.content,
                "metadata": c.metadata,
                "created_at": c.created_at,
            }
            for c in chunks
        ],
        "count": len(chunks),
    }


@app.post("/jobs/{job_id}/tool_calls", dependencies=[Depends(require_worker_token)])
def create_job_tool_call(job_id: str, body: ToolCallCreate):
    """
    Create a bidirectional tool call request. Runner requests tool execution.
    """
    if not ENABLE_STREAMING or not stream_manager:
        raise HTTPException(503, "streaming not enabled")

    # Verify job exists and is running
    with db_conn() as conn:
        row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()

    if not row:
        raise HTTPException(404, "job not found")

    if row["status"] != "running":
        raise HTTPException(400, "job not in running state")

    tool_call_id = stream_manager.create_tool_call(
        job_id=job_id,
        tool_name=body.tool_name,
        tool_args=body.tool_args,
    )

    return {"ok": True, "tool_call_id": tool_call_id}


@app.get("/jobs/{job_id}/tool_calls", dependencies=[Depends(require_bot_token)])
def get_job_tool_calls(
    job_id: str,
    status: Optional[str] = None,
    limit: int = 10,
):
    """
    Get tool calls for a job. Bot polls for pending tool execution requests.
    """
    if not ENABLE_STREAMING or not stream_manager:
        raise HTTPException(503, "streaming not enabled")

    # Verify job exists
    with db_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()

    if not row:
        raise HTTPException(404, "job not found")

    if status == ToolCallStatus.PENDING or not status:
        calls = stream_manager.get_pending_tool_calls(job_id, limit)
    else:
        # Get all tool calls for job (would need additional method)
        calls = []

    return {
        "tool_calls": [
            {
                "id": c.id,
                "tool_name": c.tool_name,
                "tool_args": c.tool_args,
                "status": c.status,
                "requested_at": c.requested_at,
            }
            for c in calls
        ],
        "count": len(calls),
    }


@app.post("/tool_calls/{tool_call_id}/result", dependencies=[Depends(require_bot_token)])
def complete_tool_call(tool_call_id: int, body: ToolCallResult):
    """
    Complete a tool call with result. Bot provides tool execution result.
    """
    if not ENABLE_STREAMING or not stream_manager:
        raise HTTPException(503, "streaming not enabled")

    success = stream_manager.complete_tool_call(tool_call_id, body.result)

    if not success:
        raise HTTPException(404, "tool call not found")

    return {"ok": True, "status": "completed"}


@app.post("/tool_calls/{tool_call_id}/fail", dependencies=[Depends(require_bot_token)])
def fail_tool_call(tool_call_id: int, body: ToolCallFail):
    """
    Mark a tool call as failed. Bot reports tool execution failure.
    """
    if not ENABLE_STREAMING or not stream_manager:
        raise HTTPException(503, "streaming not enabled")

    success = stream_manager.fail_tool_call(tool_call_id, body.error)

    if not success:
        raise HTTPException(404, "tool call not found")

    return {"ok": True, "status": "failed"}


@app.get("/tool_calls/{tool_call_id}", dependencies=[Depends(require_worker_token)])
def get_tool_call(tool_call_id: int):
    """
    Get a specific tool call. Runner polls for tool call status/result.
    """
    if not ENABLE_STREAMING or not stream_manager:
        raise HTTPException(503, "streaming not enabled")

    call = stream_manager.get_tool_call(tool_call_id)

    if not call:
        raise HTTPException(404, "tool call not found")

    return {
        "id": call.id,
        "job_id": call.job_id,
        "tool_name": call.tool_name,
        "tool_args": call.tool_args,
        "status": call.status,
        "result": call.result,
        "requested_at": call.requested_at,
        "completed_at": call.completed_at,
    }


# Server-Sent Events streaming endpoint
@app.get("/jobs/{job_id}/stream", dependencies=[Depends(require_bot_token)])
async def stream_job(job_id: str):
    """
    Server-Sent Events stream for job chunks. Real-time streaming endpoint.
    """
    if not ENABLE_STREAMING or not stream_manager:
        raise HTTPException(503, "streaming not enabled")

    # Verify job exists
    with db_conn() as conn:
        row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()

    if not row:
        raise HTTPException(404, "job not found")

    from fastapi.responses import StreamingResponse
    import asyncio

    async def event_generator():
        last_chunk_id = 0
        empty_count = 0
        max_empty = 180  # ~3 minutes of empty polls (at 1s intervals)

        while empty_count < max_empty:
            chunks = stream_manager.get_chunks(job_id, after_id=last_chunk_id, limit=50)

            if chunks:
                empty_count = 0
                for chunk in chunks:
                    data = {
                        "id": chunk.id,
                        "type": chunk.chunk_type,
                        "content": chunk.content,
                        "metadata": chunk.metadata,
                        "created_at": chunk.created_at,
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                    last_chunk_id = chunk.id

                    # Stop if final chunk received
                    if chunk.chunk_type == ChunkType.FINAL:
                        return
            else:
                empty_count += 1

            # Check if job is done/failed and no more chunks expected
            with db_conn() as conn:
                status_row = conn.execute(
                    "SELECT status FROM jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()

            if status_row and status_row["status"] in ("done", "failed"):
                # Give a moment for any final chunks to be written
                if empty_count > 5:
                    yield f"data: {json.dumps({'type': 'stream_end'})}\n\n"
                    return

            # Heartbeat to keep connection alive
            yield ":heartbeat\n\n"
            await asyncio.sleep(1)

        # Timeout - stream ended without final chunk
        yield f"data: {json.dumps({'type': 'timeout', 'message': 'Stream timeout'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering for SSE
        },
    )


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
