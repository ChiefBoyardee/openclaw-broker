"""
AgenticSession for OpenClaw Discord Bot

Manages streaming, multi-turn agentic conversations with the runner.
Handles real-time message delivery, tool call execution, and conversation flow.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

import discord

from discord_bot.streaming_client import (
    BrokerStreamingClient,
    JobChunk,
    ToolCallRequest,
    get_streaming_client,
)

logger = logging.getLogger(__name__)


@dataclass
class AgenticConfig:
    """Configuration for an agentic session."""
    max_steps: int = 10
    enable_thinking_display: bool = True
    enable_progress_updates: bool = True
    max_stream_wait: float = 300.0
    tool_timeout: float = 60.0
    poll_interval: float = 1.0
    use_sse: bool = True  # Use SSE if available, otherwise polling


@dataclass
class SessionContext:
    """Context information for a session."""
    conversation_id: str
    user_id: str
    channel_id: str
    username: str
    persona_key: str
    started_at: float


class AgenticSession:
    """
    Manages a streaming agentic conversation session.

    This class handles:
    - Creating streaming jobs with the runner
    - Receiving and processing real-time chunks
    - Executing Discord-native tool calls
    - Managing conversation flow and state
    """

    def __init__(
        self,
        message: discord.Message,
        config: AgenticConfig,
        context: SessionContext,
        streaming_client: Optional[BrokerStreamingClient] = None,
    ):
        self.message = message
        self.config = config
        self.context = context
        self.streaming_client = streaming_client or get_streaming_client()

        # State
        self.job_id: Optional[str] = None
        self.is_running = False
        self.is_complete = False
        self.final_result: Optional[str] = None
        self.tool_calls_completed: Set[int] = set()
        self.messages_sent = 0
        self.thinking_steps: List[str] = []

        # Callbacks for Discord integration
        self._on_message: Optional[Callable[[str], Coroutine]] = None
        self._on_thinking: Optional[Callable[[str, int], Coroutine]] = None
        self._on_tool_call: Optional[Callable[[str, Dict], Coroutine]] = None
        self._on_complete: Optional[Callable[[str], Coroutine]] = None

    def on_message(self, callback: Callable[[str], Coroutine]) -> "AgenticSession":
        """Register callback for intermediate messages."""
        self._on_message = callback
        return self

    def on_thinking(self, callback: Callable[[str, int], Coroutine]) -> "AgenticSession":
        """Register callback for thinking steps."""
        self._on_thinking = callback
        return self

    def on_tool_call(self, callback: Callable[[str, Dict], Coroutine]) -> "AgenticSession":
        """Register callback for tool calls."""
        self._on_tool_call = callback
        return self

    def on_complete(self, callback: Callable[[str], Coroutine]) -> "AgenticSession":
        """Register callback for completion."""
        self._on_complete = callback
        return self

    async def start(
        self,
        prompt: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        tools: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Start the agentic session.

        Args:
            prompt: The user prompt
            conversation_history: Previous conversation messages
            tools: Specific tools to enable

        Returns:
            Final result string, or None if failed
        """
        try:
            # Create streaming job
            self.job_id = await self._create_job(prompt, conversation_history, tools)
            if not self.job_id:
                logger.error("Failed to create streaming job")
                return None

            logger.info(f"Started agentic session {self.context.conversation_id} with job {self.job_id}")

            self.is_running = True

            # Start processing stream
            await self._process_stream()

            return self.final_result

        except Exception as e:
            logger.exception(f"Error in agentic session: {e}")
            await self._send_message(f"Error: {str(e)[:200]}")
            return None

        finally:
            self.is_running = False
            self.is_complete = True

    async def _create_job(
        self,
        prompt: str,
        conversation_history: Optional[List[Dict[str, str]]],
        tools: Optional[List[str]],
    ) -> Optional[str]:
        """Create a streaming job with the broker."""
        import aiohttp
        import os

        broker_url = os.environ.get("BROKER_URL", "http://127.0.0.1:8000").rstrip("/")
        bot_token = os.environ.get("BOT_TOKEN", "")

        payload = {
            "command": "llm_agentic",
            "payload": json.dumps({
                "prompt": prompt,
                "conversation_history": conversation_history or [],
                "tools": tools or [],
                "max_steps": self.config.max_steps,
                "streaming": True,
            }),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{broker_url}/jobs",
                    headers={"X-Bot-Token": bot_token},
                    json=payload,
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        job_id = data.get("id")
                        logger.info(f"Job created successfully: {job_id}")
                        return job_id
                    elif response.status == 400:
                        text = await response.text()
                        logger.error(f"Job creation failed (400 - invalid request): {text[:500]}")
                        await self._send_message(f"I can't process that request. Error: {text[:200]}")
                    elif response.status == 401:
                        logger.error("Job creation failed (401 - authentication error). Check BOT_TOKEN.")
                        await self._send_message("I'm having trouble authenticating with the broker. Please check my configuration.")
                    elif response.status == 429:
                        logger.error("Job creation failed (429 - rate limit).")
                        await self._send_message("I'm a bit overloaded right now. Please try again in a moment.")
                    else:
                        logger.error(f"Failed to create job: HTTP {response.status}")
                        text = await response.text()
                        logger.error(f"Response: {text[:500]}")
                        await self._send_message(f"I encountered an error (HTTP {response.status}) when trying to process your request.")
        except aiohttp.ClientError as e:
            logger.exception(f"Network error creating job - cannot connect to broker at {broker_url}: {e}")
            await self._send_message("I can't reach the job broker right now. The runner may be offline.")
        except Exception as e:
            logger.exception(f"Unexpected error creating job: {e}")
            await self._send_message("An unexpected error occurred while processing your request.")

        return None

    async def _check_job_status(self) -> Optional[str]:
        """Check the current status of the job from the broker.

        Returns:
            Job status string (queued, running, done, failed) or None if not found/error.
        """
        import os
        import aiohttp

        broker_url = os.environ.get("BROKER_URL", "http://127.0.0.1:8000").rstrip("/")
        bot_token = os.environ.get("BOT_TOKEN", "")

        if not self.job_id:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{broker_url}/jobs/{self.job_id}",
                    headers={"X-Bot-Token": bot_token},
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("status")
                    elif response.status == 404:
                        return None
        except Exception as e:
            logger.debug(f"Error checking job status: {e}")

        return None

    async def _process_stream(self) -> None:
        """Process the job stream, handling chunks and tool calls."""
        if not self.job_id:
            return

        try:
            # Initial delay to allow runner to claim the job before we start polling
            # Runner polls every 10s (default), but may have longer intervals or network delays
            # We wait 15s to account for: poll_interval (10s) + network latency + processing time
            import os
            initial_delay = float(os.environ.get("AGENTIC_INITIAL_WAIT_SEC", "15.0"))
            logger.info(f"Waiting {initial_delay}s for runner to claim job {self.job_id} before polling...")
            await asyncio.sleep(initial_delay)

            # Verify job was claimed - check if it's still "queued"
            job_status = await self._check_job_status()
            if job_status == "queued":
                logger.warning(f"Job {self.job_id} is still 'queued' after {initial_delay}s wait. "
                              f"Runner may not be polling or there's a capability mismatch.")
            elif job_status == "running":
                logger.info(f"Job {self.job_id} is 'running' - runner claimed it successfully")
            elif job_status in ("done", "failed"):
                logger.info(f"Job {self.job_id} is already '{job_status}' - runner may have finished quickly")
            elif job_status is None:
                logger.error(f"Job {self.job_id} not found after wait - may have been deleted or never created")

            if self.config.use_sse:
                # Use SSE streaming
                async for chunk in self.streaming_client.stream_job(
                    self.job_id, timeout=self.config.max_stream_wait
                ):
                    await self._handle_chunk(chunk)
            else:
                # Use polling fallback
                async for chunk in self.streaming_client.poll_chunks(
                    self.job_id,
                    poll_interval=self.config.poll_interval,
                    timeout=self.config.max_stream_wait,
                ):
                    await self._handle_chunk(chunk)

        except Exception as e:
            logger.exception(f"Error processing stream: {e}")

    async def _handle_chunk(self, chunk: JobChunk) -> None:
        """Handle a single chunk from the stream."""
        from discord_bot.streaming_client import JobChunk as JC

        chunk_handlers = {
            "thinking": self._handle_thinking,
            "message": self._handle_message,
            "tool_call": self._handle_tool_call,
            "tool_result": self._handle_tool_result,
            "progress": self._handle_progress,
            "final": self._handle_final,
            "heartbeat": self._handle_heartbeat,
        }

        handler = chunk_handlers.get(chunk.chunk_type)
        if handler:
            await handler(chunk)
        else:
            logger.debug(f"Unknown chunk type: {chunk.chunk_type}")

    async def _handle_thinking(self, chunk: JobChunk) -> None:
        """Handle a thinking step."""
        if not self.config.enable_thinking_display:
            return

        content = chunk.content or "Thinking..."
        step = chunk.metadata.get("step", 0) if chunk.metadata else 0

        self.thinking_steps.append(content)

        if self._on_thinking:
            await self._on_thinking(content, step)

        # Add thinking reaction to message
        try:
            if step == 1:
                await self.message.add_reaction("🤔")
            elif step > 1 and step % 3 == 0:
                # Cycle through thinking reactions
                reactions = ["🤔", "💭", "🧠", "⚙️"]
                reaction = reactions[step % len(reactions)]
                await self.message.add_reaction(reaction)
        except Exception as e:
            logger.debug(f"Failed to add reaction: {e}")

    async def _handle_message(self, chunk: JobChunk) -> None:
        """Handle an intermediate message."""
        content = chunk.content
        if not content:
            return

        msg_type = chunk.metadata.get("message_type", "info") if chunk.metadata else "info"

        # Format based on message type
        if msg_type == "success":
            formatted = f"✅ {content}"
        elif msg_type == "warning":
            formatted = f"⚠️ {content}"
        elif msg_type == "error":
            formatted = f"❌ {content}"
        else:
            formatted = content

        self.messages_sent += 1

        if self._on_message:
            await self._on_message(formatted)
        else:
            await self._send_message(formatted)

    async def _handle_tool_call(self, chunk: JobChunk) -> None:
        """Handle a tool call request."""
        if not chunk.metadata:
            return

        tool_name = chunk.metadata.get("tool_name", "")
        tool_args = chunk.metadata.get("tool_args", {})

        if self._on_tool_call:
            await self._on_tool_call(tool_name, tool_args)

        # Execute Discord-native tools
        if tool_name.startswith("discord_"):
            await self._execute_discord_tool(tool_name, tool_args, chunk)

    async def _execute_discord_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        chunk: JobChunk,
    ) -> None:
        """Execute a Discord-native tool."""
        try:
            result = await self._run_discord_tool(tool_name, tool_args)

            # Report result back via streaming client
            tool_call_id = chunk.metadata.get("tool_call_id") if chunk.metadata else None
            if tool_call_id:
                await self.streaming_client.complete_tool_call(tool_call_id, result)

        except Exception as e:
            logger.exception(f"Error executing Discord tool {tool_name}: {e}")
            error_msg = f"Error: {str(e)[:200]}"

            tool_call_id = chunk.metadata.get("tool_call_id") if chunk.metadata else None
            if tool_call_id:
                await self.streaming_client.fail_tool_call(tool_call_id, error_msg)

    async def _run_discord_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """Execute a Discord tool and return result."""
        if tool_name == "discord_send_message":
            message = tool_args.get("message", "")
            if message:
                await self._send_message(message)
            return json.dumps({"sent": True, "channel_id": str(self.message.channel.id)})

        elif tool_name == "discord_add_reaction":
            emoji = tool_args.get("emoji", "👍")
            try:
                await self.message.add_reaction(emoji)
                return json.dumps({"added": True, "emoji": emoji})
            except Exception as e:
                return json.dumps({"added": False, "error": str(e)})

        elif tool_name == "discord_send_embed":
            title = tool_args.get("title", "")
            description = tool_args.get("description", "")
            color = tool_args.get("color", 0x3498db)

            embed = discord.Embed(title=title, description=description, color=color)
            await self.message.channel.send(embed=embed)
            return json.dumps({"sent": True, "type": "embed"})

        else:
            return json.dumps({"error": f"Unknown Discord tool: {tool_name}"})

    async def _handle_tool_result(self, chunk: JobChunk) -> None:
        """Handle a tool result chunk."""
        # Tool results are processed internally, no user-facing action needed
        pass

    async def _handle_progress(self, chunk: JobChunk) -> None:
        """Handle a progress update."""
        if not self.config.enable_progress_updates:
            return

        content = chunk.content
        percent = chunk.metadata.get("percent") if chunk.metadata else None

        # Only show significant progress updates (every 20%)
        if percent and int(percent) % 20 == 0:
            logger.debug(f"Progress: {percent}% - {content}")

    async def _handle_final(self, chunk: JobChunk) -> None:
        """Handle the final result."""
        self.final_result = chunk.content or "(no result)"
        self.is_complete = True
        self.is_running = False

        logger.info(f"Agentic session complete. Final result length: {len(self.final_result)}")

        # Send the final result to Discord
        if self._on_complete:
            await self._on_complete(self.final_result)
        else:
            # Send the final result as a message
            await self._send_message(self.final_result)

        # Clear thinking reactions and add completion reaction
        try:
            await self.message.clear_reactions()
            await self.message.add_reaction("✅")
        except Exception as e:
            logger.debug(f"Failed to update reactions: {e}")

    async def _handle_heartbeat(self, chunk: JobChunk) -> None:
        """Handle a heartbeat."""
        # Heartbeats keep the job alive, no action needed
        pass

    async def _send_message(self, content: str) -> Optional[discord.Message]:
        """Send a message to the channel."""
        try:
            return await self.message.channel.send(content[:2000])  # Discord limit
        except Exception as e:
            logger.exception(f"Failed to send message: {e}")
            return None

    async def check_and_execute_pending_tools(self) -> None:
        """Check for and execute pending bidirectional tool calls."""
        if not self.job_id or not self.is_running:
            return

        try:
            pending_calls = await self.streaming_client.get_pending_tool_calls(self.job_id)

            for call in pending_calls:
                if call.id in self.tool_calls_completed:
                    continue

                if call.tool_name.startswith("discord_"):
                    result = await self._run_discord_tool(call.tool_name, call.tool_args)
                    success = await self.streaming_client.complete_tool_call(call.id, result)
                    if success:
                        self.tool_calls_completed.add(call.id)
                else:
                    # Non-Discord tools are handled by runner
                    pass

        except Exception as e:
            logger.exception(f"Error checking pending tools: {e}")


class AgenticSessionManager:
    """Manages multiple agentic sessions."""

    def __init__(self):
        self.sessions: Dict[str, AgenticSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        message: discord.Message,
        config: Optional[AgenticConfig] = None,
        conversation_id: Optional[str] = None,
        persona_key: str = "default",
    ) -> AgenticSession:
        """Create a new agentic session."""
        conv_id = conversation_id or f"{message.channel.id}_{message.author.id}_{int(time.time())}"

        context = SessionContext(
            conversation_id=conv_id,
            user_id=str(message.author.id),
            channel_id=str(message.channel.id),
            username=message.author.display_name,
            persona_key=persona_key,
            started_at=time.time(),
        )

        session = AgenticSession(
            message=message,
            config=config or AgenticConfig(),
            context=context,
        )

        async with self._lock:
            self.sessions[conv_id] = session

        return session

    async def end_session(self, conversation_id: str) -> None:
        """End an agentic session."""
        async with self._lock:
            if conversation_id in self.sessions:
                session = self.sessions[conversation_id]
                session.is_running = False
                del self.sessions[conversation_id]

    def get_session(self, conversation_id: str) -> Optional[AgenticSession]:
        """Get an active session by conversation ID."""
        return self.sessions.get(conversation_id)


# Global manager instance
_session_manager: Optional[AgenticSessionManager] = None


def get_agentic_manager() -> AgenticSessionManager:
    """Get or create the global agentic session manager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = AgenticSessionManager()
    return _session_manager
