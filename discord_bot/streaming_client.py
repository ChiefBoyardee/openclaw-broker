"""
Discord Bot Streaming Client for OpenClaw

Provides SSE (Server-Sent Events) client for receiving real-time job updates
from the broker. Enables the bot to handle streaming agentic conversations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)

# Configuration from environment
BROKER_URL = os.environ.get("BROKER_URL", "http://127.0.0.1:8000").strip().rstrip("/")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
AGENTIC_MODE = os.environ.get("AGENTIC_MODE", "true").lower() in ("true", "1", "yes")
AGENTIC_MAX_STREAM_WAIT = float(os.environ.get("AGENTIC_MAX_STREAM_WAIT", "300"))


@dataclass
class JobChunk:
    """Represents a chunk from a job stream."""
    id: int
    chunk_type: str
    content: Optional[str]
    metadata: Optional[Dict[str, Any]]
    created_at: Optional[int]


@dataclass
class ToolCallRequest:
    """Represents a bidirectional tool call request."""
    id: int
    tool_name: str
    tool_args: Dict[str, Any]
    requested_at: int


class BrokerStreamingClient:
    """Client for streaming job results from the broker via SSE."""

    def __init__(
        self,
        broker_url: str = BROKER_URL,
        bot_token: str = BOT_TOKEN,
    ):
        self.broker_url = broker_url
        self.bot_token = bot_token
        self.enabled = AGENTIC_MODE and bool(bot_token)

    def _headers(self) -> Dict[str, str]:
        """Return authentication headers."""
        return {"X-Bot-Token": self.bot_token}

    async def stream_job(
        self,
        job_id: str,
        timeout: float = AGENTIC_MAX_STREAM_WAIT,
    ) -> AsyncGenerator[JobChunk, None]:
        """
        Stream chunks for a job via Server-Sent Events.

        Args:
            job_id: The job ID to stream
            timeout: Maximum time to wait for stream

        Yields:
            JobChunk objects as they arrive
        """
        if not self.enabled:
            logger.warning("Streaming not enabled")
            return

        url = f"{self.broker_url}/jobs/{job_id}/stream"

        try:
            timeout_obj = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.get(url, headers=self._headers()) as response:
                    if response.status != 200:
                        logger.error(f"Failed to start stream: {response.status}")
                        return

                    # Process SSE stream
                    buffer = ""
                    async for line in response.content:
                        try:
                            line = line.decode("utf-8")
                        except UnicodeDecodeError:
                            continue

                        # SSE format: lines starting with "data: " contain data
                        if line.startswith("data: "):
                            data = line[6:].strip()
                            if data:
                                try:
                                    chunk_data = json.loads(data)

                                    # Handle stream end
                                    if chunk_data.get("type") == "stream_end":
                                        logger.info(f"Stream ended for job {job_id}")
                                        return

                                    # Handle timeout
                                    if chunk_data.get("type") == "timeout":
                                        logger.warning(f"Stream timeout for job {job_id}")
                                        return

                                    # Yield chunk
                                    yield JobChunk(
                                        id=chunk_data.get("id", 0),
                                        chunk_type=chunk_data.get("type", "unknown"),
                                        content=chunk_data.get("content"),
                                        metadata=chunk_data.get("metadata"),
                                        created_at=chunk_data.get("created_at"),
                                    )
                                except json.JSONDecodeError:
                                    logger.warning(f"Invalid JSON in stream: {data}")

                        # Check for timeout comment
                        elif line.startswith(":heartbeat"):
                            # Keep connection alive
                            pass

        except asyncio.TimeoutError:
            logger.warning(f"Stream timeout for job {job_id}")
        except Exception as e:
            logger.exception(f"Error streaming job {job_id}: {e}")

    async def poll_chunks(
        self,
        job_id: str,
        after_id: int = 0,
        chunk_type: Optional[str] = None,
        poll_interval: float = 1.0,
        timeout: float = AGENTIC_MAX_STREAM_WAIT,
    ) -> AsyncGenerator[JobChunk, None]:
        """
        Poll for chunks via HTTP polling (fallback when SSE is not available).

        Args:
            job_id: The job ID to poll
            after_id: Only return chunks after this ID
            chunk_type: Filter by chunk type
            poll_interval: Seconds between polls
            timeout: Maximum time to poll

        Yields:
            JobChunk objects as they arrive
        """
        if not self.enabled:
            logger.warning(f"Streaming client not enabled for job {job_id} - AGENTIC_MODE={AGENTIC_MODE}, has_bot_token={bool(self.bot_token)}")
            return

        url = f"{self.broker_url}/jobs/{job_id}/chunks"
        last_id = after_id
        start_time = asyncio.get_event_loop().time()
        chunks_received = 0

        logger.info(f"Starting chunk polling for job {job_id}")
        warning_interval = 10  # Warn every 10 seconds if no chunks received
        last_warning_time = start_time

        not_found_attempts = 0
        while True:
            try:
                params: Dict[str, Any] = {"after_id": last_id, "limit": 50}
                if chunk_type:
                    params["chunk_type"] = chunk_type

                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url, headers=self._headers(), params=params
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            chunks = data.get("chunks", [])

                            for chunk_data in chunks:
                                chunks_received += 1
                                chunk = JobChunk(
                                    id=chunk_data.get("id", 0),
                                    chunk_type=chunk_data.get("chunk_type", "unknown"),
                                    content=chunk_data.get("content"),
                                    metadata=chunk_data.get("metadata"),
                                    created_at=chunk_data.get("created_at"),
                                )
                                last_id = max(last_id, chunk.id)
                                
                                if chunks_received == 1:
                                    logger.info(f"First chunk received for job {job_id}: {chunk.chunk_type}")
                                
                                yield chunk

                                # Stop on final chunk
                                if chunk.chunk_type == "final":
                                    logger.info(f"Final chunk received for job {job_id}. Total chunks: {chunks_received}")
                                    return

                        elif response.status == 404:
                            # Job might not be visible yet - runner hasn't claimed it or WAL mode delay
                            # Instead of giving up, keep polling at normal intervals - runner may claim it later
                            not_found_attempts += 1
                            if not_found_attempts <= 5:
                                # Exponential backoff for first 5 attempts: 200ms, 400ms, 800ms, 1600ms, 3200ms
                                delay = 0.2 * (2 ** (not_found_attempts - 1))
                                logger.warning(f"Job {job_id} not found (attempt {not_found_attempts}), retrying in {delay:.1f}s...")
                                await asyncio.sleep(delay)
                                continue  # Try again immediately
                            else:
                                # After 5 attempts, just log at debug level and continue normal polling
                                # The runner may be busy with previous LLM work - keep waiting
                                logger.debug(f"Job {job_id} not visible yet, continuing to poll...")
                                # Fall through to normal sleep at end of loop

                # Check timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout:
                    logger.warning(f"Polling timeout for job {job_id} after {elapsed:.1f}s. Received {chunks_received} chunks.")
                    return

                # Warn if no chunks received after warning_interval
                time_since_warning = asyncio.get_event_loop().time() - last_warning_time
                if chunks_received == 0 and time_since_warning > warning_interval:
                    logger.warning(f"No chunks received for job {job_id} after {elapsed:.1f}s. Check runner ENABLE_STREAMING and WORKER_TOKEN settings.")
                    last_warning_time = asyncio.get_event_loop().time()

                # Check job status
                job_done = await self._is_job_done(job_id)
                if job_done and not chunks:
                    # Job done and no new chunks
                    await asyncio.sleep(0.5)  # One more poll after delay
                    continue

                await asyncio.sleep(poll_interval)

            except Exception as e:
                logger.exception(f"Error polling chunks: {e}")
                await asyncio.sleep(poll_interval)

    async def _is_job_done(self, job_id: str) -> bool:
        """Check if a job is done or failed."""
        url = f"{self.broker_url}/jobs/{job_id}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self._headers()) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("status") in ("done", "failed")
        except Exception as e:
            logger.warning(f"Error checking job status: {e}")

        return False

    async def get_pending_tool_calls(
        self,
        job_id: str,
        limit: int = 10,
    ) -> list[ToolCallRequest]:
        """
        Get pending tool calls for a job.

        Args:
            job_id: The job ID to check
            limit: Maximum tool calls to return

        Returns:
            List of pending ToolCallRequest objects
        """
        if not self.enabled:
            return []

        url = f"{self.broker_url}/jobs/{job_id}/tool_calls"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=self._headers(), params={"status": "pending", "limit": limit}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        calls = data.get("tool_calls", [])
                        return [
                            ToolCallRequest(
                                id=c.get("id"),
                                tool_name=c.get("tool_name", ""),
                                tool_args=c.get("tool_args", {}),
                                requested_at=c.get("requested_at", 0),
                            )
                            for c in calls
                        ]
        except Exception as e:
            logger.exception(f"Error getting tool calls: {e}")

        return []

    async def complete_tool_call(
        self,
        tool_call_id: int,
        result: str,
    ) -> bool:
        """
        Complete a tool call with result.

        Args:
            tool_call_id: The tool call ID to complete
            result: The result string

        Returns:
            True if successful
        """
        if not self.enabled:
            return False

        url = f"{self.broker_url}/tool_calls/{tool_call_id}/result"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=self._headers(), json={"result": result}
                ) as response:
                    if response.status == 200:
                        logger.info(f"Completed tool call {tool_call_id}")
                        return True
                    else:
                        logger.warning(f"Failed to complete tool call: {response.status}")
        except Exception as e:
            logger.exception(f"Error completing tool call: {e}")

        return False

    async def fail_tool_call(
        self,
        tool_call_id: int,
        error: str,
    ) -> bool:
        """
        Mark a tool call as failed.

        Args:
            tool_call_id: The tool call ID to fail
            error: Error message

        Returns:
            True if successful
        """
        if not self.enabled:
            return False

        url = f"{self.broker_url}/tool_calls/{tool_call_id}/fail"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=self._headers(), json={"error": error}
                ) as response:
                    if response.status == 200:
                        logger.info(f"Failed tool call {tool_call_id}")
                        return True
        except Exception as e:
            logger.exception(f"Error failing tool call: {e}")

        return False


# Global singleton instance
_streaming_client: Optional[BrokerStreamingClient] = None


def get_streaming_client(
    broker_url: str = BROKER_URL,
    bot_token: str = BOT_TOKEN,
) -> BrokerStreamingClient:
    """Get or create the global streaming client."""
    global _streaming_client
    if _streaming_client is None:
        _streaming_client = BrokerStreamingClient(broker_url, bot_token)
    return _streaming_client
