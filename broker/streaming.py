"""
OpenClaw Broker Streaming Module

Provides Server-Sent Events (SSE) streaming for job results and
bidirectional tool call support between runners and bots.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from pydantic import BaseModel

import logging

DB_PATH = os.environ.get("BROKER_DB", "/var/lib/openclaw-broker/broker.db")

logger = logging.getLogger(__name__)


# Chunk types for job streaming
class ChunkType:
    THINKING = "thinking"           # LLM reasoning/thinking step
    TOOL_CALL = "tool_call"         # Tool call request from runner
    TOOL_RESULT = "tool_result"     # Tool execution result
    MESSAGE = "message"             # Intermediate message to user
    PROGRESS = "progress"           # Progress update
    FINAL = "final"                 # Final result
    HEARTBEAT = "heartbeat"         # Keep-alive from runner


# Tool call status
class ToolCallStatus:
    PENDING = "pending"             # Waiting for execution
    RUNNING = "running"             # Currently executing
    COMPLETED = "completed"         # Successfully completed
    FAILED = "failed"               # Execution failed


class JobChunk(BaseModel):
    """A chunk of streaming job output."""
    id: Optional[int] = None
    job_id: str
    chunk_type: str
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[int] = None


class JobToolCall(BaseModel):
    """A bidirectional tool call request."""
    id: Optional[int] = None
    job_id: str
    tool_name: str
    tool_args: Optional[Dict[str, Any]] = None
    status: str = ToolCallStatus.PENDING
    result: Optional[str] = None
    requested_at: Optional[int] = None
    completed_at: Optional[int] = None


class JobStreamManager:
    """Manages streaming job chunks and bidirectional tool calls."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_tables()

    def _db_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        """Create streaming-related tables if they don't exist."""
        with self._db_conn() as conn:
            # Job chunks table for streaming results
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    chunk_type TEXT NOT NULL,
                    content TEXT,
                    metadata TEXT,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_job ON job_chunks(job_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_type ON job_chunks(chunk_type)"
            )

            # Tool call requests table for bidirectional execution
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_tool_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    tool_args TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result TEXT,
                    requested_at INTEGER NOT NULL,
                    completed_at INTEGER,
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tool_calls_job ON job_tool_calls(job_id, requested_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tool_calls_status ON job_tool_calls(status)"
            )

            conn.commit()
        logger.info("Streaming tables initialized")

    def add_chunk(
        self,
        job_id: str,
        chunk_type: str,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Add a chunk to the job stream.

        Returns:
            The ID of the created chunk.
        """
        with self._db_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO job_chunks (job_id, chunk_type, content, metadata, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    chunk_type,
                    content,
                    json.dumps(metadata) if metadata else None,
                    int(time.time()),
                ),
            )
            conn.commit()
            chunk_id = cursor.lastrowid

        # Audit log for important chunk types
        if chunk_type in (ChunkType.TOOL_CALL, ChunkType.FINAL, ChunkType.MESSAGE):
            self._audit("chunk_added", job_id=job_id, chunk_type=chunk_type, chunk_id=chunk_id)

        return chunk_id

    def get_chunks(
        self,
        job_id: str,
        after_id: Optional[int] = None,
        chunk_types: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[JobChunk]:
        """Get chunks for a job, optionally filtered.

        Args:
            job_id: The job ID to fetch chunks for
            after_id: Only return chunks with ID > this value (for streaming)
            chunk_types: Filter by specific chunk types
            limit: Maximum chunks to return

        Returns:
            List of JobChunk objects
        """
        query = "SELECT * FROM job_chunks WHERE job_id = ?"
        params: List[Any] = [job_id]

        if after_id is not None:
            query += " AND id > ?"
            params.append(after_id)

        if chunk_types:
            placeholders = ",".join("?" * len(chunk_types))
            query += f" AND chunk_type IN ({placeholders})"
            params.extend(chunk_types)

        query += " ORDER BY id ASC LIMIT ?"
        params.append(limit)

        with self._db_conn() as conn:
            rows = conn.execute(query, params).fetchall()

        chunks = []
        for row in rows:
            chunks.append(
                JobChunk(
                    id=row["id"],
                    job_id=row["job_id"],
                    chunk_type=row["chunk_type"],
                    content=row["content"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else None,
                    created_at=row["created_at"],
                )
            )

        return chunks

    def get_chunk_count(self, job_id: str, chunk_types: Optional[List[str]] = None) -> int:
        """Get total number of chunks for a job."""
        query = "SELECT COUNT(*) FROM job_chunks WHERE job_id = ?"
        params: List[Any] = [job_id]

        if chunk_types:
            placeholders = ",".join("?" * len(chunk_types))
            query += f" AND chunk_type IN ({placeholders})"
            params.extend(chunk_types)

        with self._db_conn() as conn:
            row = conn.execute(query, params).fetchone()
            return row[0] if row else 0

    def create_tool_call(
        self,
        job_id: str,
        tool_name: str,
        tool_args: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Create a new tool call request.

        Returns:
            The ID of the created tool call.
        """
        with self._db_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO job_tool_calls
                (job_id, tool_name, tool_args, status, requested_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    tool_name,
                    json.dumps(tool_args) if tool_args else None,
                    ToolCallStatus.PENDING,
                    int(time.time()),
                ),
            )
            conn.commit()
            tool_call_id = cursor.lastrowid

        self._audit("tool_call_created", job_id=job_id, tool_name=tool_name, tool_call_id=tool_call_id)
        return tool_call_id

    def get_tool_call(self, tool_call_id: int) -> Optional[JobToolCall]:
        """Get a specific tool call by ID."""
        with self._db_conn() as conn:
            row = conn.execute(
                "SELECT * FROM job_tool_calls WHERE id = ?",
                (tool_call_id,),
            ).fetchone()

        if not row:
            return None

        return JobToolCall(
            id=row["id"],
            job_id=row["job_id"],
            tool_name=row["tool_name"],
            tool_args=json.loads(row["tool_args"]) if row["tool_args"] else None,
            status=row["status"],
            result=row["result"],
            requested_at=row["requested_at"],
            completed_at=row["completed_at"],
        )

    def get_pending_tool_calls(
        self,
        job_id: str,
        limit: int = 10,
    ) -> List[JobToolCall]:
        """Get pending tool calls for a job."""
        with self._db_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM job_tool_calls
                WHERE job_id = ? AND status = ?
                ORDER BY requested_at ASC
                LIMIT ?
                """,
                (job_id, ToolCallStatus.PENDING, limit),
            ).fetchall()

        calls = []
        for row in rows:
            calls.append(
                JobToolCall(
                    id=row["id"],
                    job_id=row["job_id"],
                    tool_name=row["tool_name"],
                    tool_args=json.loads(row["tool_args"]) if row["tool_args"] else None,
                    status=row["status"],
                    result=row["result"],
                    requested_at=row["requested_at"],
                    completed_at=row["completed_at"],
                )
            )

        return calls

    def update_tool_call_status(
        self,
        tool_call_id: int,
        status: str,
        result: Optional[str] = None,
    ) -> bool:
        """Update the status of a tool call.

        Returns:
            True if successful, False if tool call not found.
        """
        completed_at = int(time.time()) if status in (ToolCallStatus.COMPLETED, ToolCallStatus.FAILED) else None

        with self._db_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE job_tool_calls
                SET status = ?, result = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, result, completed_at, tool_call_id),
            )
            conn.commit()

            if cursor.rowcount == 0:
                return False

        self._audit("tool_call_updated", tool_call_id=tool_call_id, status=status)
        return True

    def complete_tool_call(
        self,
        tool_call_id: int,
        result: str,
    ) -> bool:
        """Mark a tool call as completed with result."""
        return self.update_tool_call_status(tool_call_id, ToolCallStatus.COMPLETED, result)

    def fail_tool_call(
        self,
        tool_call_id: int,
        error: str,
    ) -> bool:
        """Mark a tool call as failed with error message."""
        return self.update_tool_call_status(tool_call_id, ToolCallStatus.FAILED, error)

    def cleanup_old_chunks(self, max_age_seconds: int = 3600) -> int:
        """Remove chunks older than specified age.

        Returns:
            Number of chunks deleted.
        """
        cutoff = int(time.time()) - max_age_seconds

        with self._db_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM job_chunks WHERE created_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount

    def cleanup_old_tool_calls(self, max_age_seconds: int = 86400) -> int:
        """Remove completed/failed tool calls older than specified age.

        Returns:
            Number of tool calls deleted.
        """
        cutoff = int(time.time()) - max_age_seconds

        with self._db_conn() as conn:
            cursor = conn.execute(
                """
                DELETE FROM job_tool_calls
                WHERE requested_at < ?
                AND status IN (?, ?)
                """,
                (cutoff, ToolCallStatus.COMPLETED, ToolCallStatus.FAILED),
            )
            conn.commit()
            return cursor.rowcount

    def _audit(self, event: str, **kwargs: Any) -> None:
        """Emit structured audit line to stderr."""
        parts = [f"event={event}"]
        for k, v in kwargs.items():
            if v is not None:
                parts.append(f"{k}={v}")
        print(" ".join(parts), file=sys.stderr)


# Global singleton instance
_stream_manager: Optional[JobStreamManager] = None


def get_stream_manager(db_path: str = DB_PATH) -> JobStreamManager:
    """Get or create the global stream manager instance."""
    global _stream_manager
    if _stream_manager is None:
        _stream_manager = JobStreamManager(db_path)
    return _stream_manager
