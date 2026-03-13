"""
Runner Streaming Client for OpenClaw

Provides the runner with the ability to stream job chunks to the broker
for real-time bidirectional communication.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# Configuration from environment
BROKER_URL = os.environ.get("BROKER_URL", "http://127.0.0.1:8000").strip().rstrip("/")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")
STREAMING_ENABLED = os.environ.get("ENABLE_STREAMING", "true").lower() in ("true", "1", "yes")
STREAMING_HEARTBEAT_SECONDS = int(os.environ.get("STREAMING_HEARTBEAT_SECONDS", "30"))

# HTTP timeouts
CHUNK_POST_TIMEOUT = (5, 15)  # (connect, read)


class ChunkType:
    """Chunk types for job streaming."""
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    MESSAGE = "message"
    PROGRESS = "progress"
    FINAL = "final"
    HEARTBEAT = "heartbeat"


class RunnerStreamClient:
    """Client for streaming job chunks to the broker."""

    def __init__(
        self,
        job_id: str,
        broker_url: str = BROKER_URL,
        worker_token: str = WORKER_TOKEN,
    ):
        self.job_id = job_id
        self.broker_url = broker_url
        self.worker_token = worker_token
        self.enabled = STREAMING_ENABLED and bool(worker_token)
        self.last_heartbeat = 0
        self.chunks_posted = 0
        
        if not self.enabled:
            logger.warning(f"Streaming client disabled for job {job_id}: STREAMING_ENABLED={STREAMING_ENABLED}, has_token={bool(worker_token)}")
        else:
            logger.info(f"Streaming client initialized for job {job_id}")

    def _headers(self) -> Dict[str, str]:
        """Return authentication headers."""
        return {"X-Worker-Token": self.worker_token}

    def verify_job_visible(self, max_retries: int = 5, initial_delay: float = 0.2) -> bool:
        """
        Verify that the job is visible to the broker before posting chunks.

        This is critical for WAL mode SQLite where job visibility may be delayed
        after the runner claims the job.

        Args:
            max_retries: Maximum number of retry attempts
            initial_delay: Initial delay between retries in seconds (doubles each retry)

        Returns:
            True if job is visible, False otherwise
        """
        if not self.enabled:
            return False

        url = f"{self.broker_url}/jobs/{self.job_id}"
        delay = initial_delay

        for attempt in range(max_retries):
            try:
                response = requests.get(
                    url,
                    headers=self._headers(),
                    timeout=CHUNK_POST_TIMEOUT,
                )

                if response.status_code == 200:
                    if attempt > 0:
                        logger.info(f"Job {self.job_id} now visible after {attempt + 1} attempts")
                    return True
                elif response.status_code == 404:
                    if attempt < max_retries - 1:
                        logger.warning(f"Job {self.job_id} not visible yet (attempt {attempt + 1}/{max_retries}), waiting {delay:.2f}s...")
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff
                    else:
                        logger.error(f"Job {self.job_id} still not visible after {max_retries} attempts")
                        return False
                else:
                    logger.warning(f"Unexpected status {response.status_code} checking job visibility")
                    return False

            except requests.RequestException as e:
                logger.warning(f"Request error checking job visibility: {e}")
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2

        return False

    def post_chunk(
        self,
        chunk_type: str,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Post a chunk to the job stream.

        Args:
            chunk_type: Type of chunk (thinking, message, tool_call, etc.)
            content: Chunk content/text
            metadata: Optional JSON metadata

        Returns:
            True if posted successfully, False otherwise
        """
        if not self.enabled:
            logger.debug(f"Streaming disabled, chunk not posted: {chunk_type}")
            return False

        url = f"{self.broker_url}/jobs/{self.job_id}/chunks"
        payload = {
            "chunk_type": chunk_type,
            "content": content,
            "metadata": metadata,
        }

        try:
            response = requests.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=CHUNK_POST_TIMEOUT,
            )

            if response.status_code == 200:
                self.chunks_posted += 1
                if self.chunks_posted == 1:
                    logger.info(f"First chunk posted for job {self.job_id}: {chunk_type}")
                else:
                    logger.debug(f"Posted chunk {chunk_type} for job {self.job_id}")
                return True
            elif response.status_code == 404:
                logger.warning(f"Job {self.job_id} not found when posting chunk")
                return False
            else:
                logger.warning(f"Failed to post chunk: {response.status_code} {response.text}")
                return False

        except requests.RequestException as e:
            logger.warning(f"Request error posting chunk: {e}")
            return False

    def post_thinking(self, thought: str, step: Optional[int] = None) -> bool:
        """Post a thinking/reasoning step."""
        metadata = {"step": step} if step is not None else None
        return self.post_chunk(ChunkType.THINKING, thought, metadata)

    def post_message(self, message: str, msg_type: str = "info") -> bool:
        """Post an intermediate message to the user."""
        return self.post_chunk(
            ChunkType.MESSAGE,
            message,
            metadata={"message_type": msg_type},
        )

    def post_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call_id: Optional[str] = None,
    ) -> bool:
        """Post a tool call request.

        Also creates a bidirectional tool call request in the broker.
        """
        metadata = {
            "tool_name": tool_name,
            "tool_args": tool_args,
        }
        if tool_call_id:
            metadata["tool_call_id"] = tool_call_id

        return self.post_chunk(ChunkType.TOOL_CALL, None, metadata)

    def post_tool_result(
        self,
        tool_name: str,
        result: str,
        success: bool = True,
    ) -> bool:
        """Post a tool execution result."""
        return self.post_chunk(
            ChunkType.TOOL_RESULT,
            result,
            metadata={
                "tool_name": tool_name,
                "success": success,
            },
        )

    def post_progress(self, message: str, percent: Optional[float] = None) -> bool:
        """Post a progress update."""
        metadata = {"percent": percent} if percent is not None else None
        return self.post_chunk(ChunkType.PROGRESS, message, metadata)

    def post_final(self, result: str) -> bool:
        """Post the final result and end the stream."""
        success = self.post_chunk(ChunkType.FINAL, result)
        logger.info(f"Posted final chunk for job {self.job_id}, total chunks: {self.chunks_posted}")
        return success

    def post_heartbeat(self, force: bool = False) -> bool:
        """Post a heartbeat to keep the job lease alive.

        This is called automatically during long operations.

        Args:
            force: If True, post heartbeat even if not enough time has elapsed.
                   Use this when you need to ensure a heartbeat is actually sent.

        Returns:
            True if heartbeat was posted or was too soon (within rate limit),
            False if posting failed.
        """
        now = time.time()
        time_since_last = now - self.last_heartbeat

        if not force and time_since_last < STREAMING_HEARTBEAT_SECONDS:
            # Within rate limit window - check if we're approaching timeout
            # If we're close to the heartbeat interval, force a post to keep connection alive
            if time_since_last < STREAMING_HEARTBEAT_SECONDS * 0.8:
                return True  # Too soon, no need to post
            # We're at 80%+ of the interval, go ahead and post

        success = self.post_chunk(ChunkType.HEARTBEAT, None, {"timestamp": now})
        if success:
            self.last_heartbeat = now
            logger.debug(f"Heartbeat posted for job {self.job_id}")
        else:
            logger.warning(f"Failed to post heartbeat for job {self.job_id}")
        return success

    def create_bidirectional_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
    ) -> Optional[int]:
        """Create a bidirectional tool call request.

        This creates a tool call that the bot can execute and return results for.

        Returns:
            Tool call ID if created successfully, None otherwise
        """
        if not self.enabled:
            return None

        url = f"{self.broker_url}/jobs/{self.job_id}/tool_calls"
        payload = {
            "tool_name": tool_name,
            "tool_args": tool_args,
        }

        try:
            response = requests.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=CHUNK_POST_TIMEOUT,
            )

            if response.status_code == 200:
                data = response.json()
                tool_call_id = data.get("tool_call_id")
                logger.info(f"Created bidirectional tool call {tool_call_id} for {tool_name}")
                return tool_call_id
            else:
                logger.warning(f"Failed to create tool call: {response.status_code}")
                return None

        except requests.RequestException as e:
            logger.warning(f"Request error creating tool call: {e}")
            return None

    def poll_tool_call_result(
        self,
        tool_call_id: int,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
    ) -> Optional[str]:
        """Poll for a tool call result.

        Args:
            tool_call_id: The ID of the tool call to poll
            timeout: Maximum time to wait for result
            poll_interval: Seconds between polls

        Returns:
            Tool result string if completed, None if failed or timeout
        """
        if not self.enabled:
            return None

        url = f"{self.broker_url}/tool_calls/{tool_call_id}"
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                response = requests.get(
                    url,
                    headers=self._headers(),
                    timeout=CHUNK_POST_TIMEOUT,
                )

                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status")

                    if status == "completed":
                        logger.info(f"Tool call {tool_call_id} completed")
                        return data.get("result")
                    elif status == "failed":
                        logger.warning(f"Tool call {tool_call_id} failed")
                        return None
                    # else still pending, continue polling

                elif response.status_code == 404:
                    logger.warning(f"Tool call {tool_call_id} not found")
                    return None

            except requests.RequestException as e:
                logger.warning(f"Error polling tool call: {e}")

            time.sleep(poll_interval)
            self.post_heartbeat()  # Keep job alive while waiting

        logger.warning(f"Timeout waiting for tool call {tool_call_id}")
        return None


def create_stream_client(job_id: str) -> RunnerStreamClient:
    """Create a streaming client for a job.

    Args:
        job_id: The job ID to create client for

    Returns:
        RunnerStreamClient instance
    """
    return RunnerStreamClient(job_id)
