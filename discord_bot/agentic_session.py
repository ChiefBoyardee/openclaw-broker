"""
AgenticSession for OpenClaw Discord Bot

Manages streaming, multi-turn agentic conversations with the runner.
Handles real-time message delivery, tool call execution, and conversation flow.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
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

from discord_bot.self_memory import get_self_memory

logger = logging.getLogger(__name__)


@dataclass
class AgenticConfig:
    """Configuration for an agentic session."""
    max_steps: int = 25
    enable_thinking_display: bool = True
    enable_progress_updates: bool = True
    # Use 900s absolute max to allow for long-running multi-step tasks
    # The streaming client's idle timeout (300s) will reset when chunks/heartbeats are received
    max_stream_wait: float = 900.0
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
        self.followup_job_ids: List[str] = []  # Track follow-up jobs created

        # Status tracking for real-time updates
        self.status_message: Optional[discord.Message] = None  # Initial status message to edit
        self.current_step: int = 0
        self.total_steps: int = config.max_steps
        self.tokens_generated: int = 0
        self.start_time: float = 0.0
        self.last_status_update: float = 0.0
        self.gpu_usage_history: List[float] = []  # Track GPU usage over time

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
            self.start_time = time.time()
            self.last_status_update = self.start_time

            # Send initial status message
            await self._send_initial_status_message()

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

        # Track chunk timing for status updates
        last_chunk_time = time.time()
        chunks_received = 0
        status_update_interval = 30  # Update status every 30 seconds during long waits
        last_status_update = time.time()

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
                # Pass absolute_timeout as the safety ceiling, idle timeout uses defaults
                async for chunk in self.streaming_client.stream_job(
                    self.job_id, absolute_timeout=self.config.max_stream_wait
                ):
                    chunks_received += 1
                    last_chunk_time = time.time()
                    await self._handle_chunk(chunk)
            else:
                # Use polling fallback with status updates
                # Pass both timeouts: idle timeout resets on chunk receipt, absolute is safety ceiling
                async for chunk in self.streaming_client.poll_chunks(
                    self.job_id,
                    poll_interval=self.config.poll_interval,
                    absolute_timeout=self.config.max_stream_wait,
                ):
                    chunks_received += 1
                    last_chunk_time = time.time()
                    await self._handle_chunk(chunk)

                    # Periodic status update for long-running operations
                    now = time.time()
                    if now - last_status_update > status_update_interval:
                        time_since_chunk = now - last_chunk_time
                        if time_since_chunk > 20:
                            logger.info(f"Agentic session {self.job_id} still active, "
                                       f"{chunks_received} chunks received, waiting for more...")
                        last_status_update = now

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
        """Handle a thinking step (internal only, not displayed to user)."""
        content = chunk.content or "Thinking..."
        step = chunk.metadata.get("step", 0) if chunk.metadata else 0
        self.thinking_steps.append(content)
        self.current_step = max(self.current_step, step)

        # Track tokens if provided in metadata
        if chunk.metadata:
            tokens = chunk.metadata.get("tokens", 0)
            if tokens > 0:
                self.tokens_generated = max(self.tokens_generated, tokens)

        logger.debug(f"Thinking step {step}: {content[:100]}")

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

        # Track step progression
        self.current_step += 1

        # Track tokens if provided
        tokens = chunk.metadata.get("tokens", 0)
        if tokens > 0:
            self.tokens_generated = max(self.tokens_generated, tokens)

        # Update status message immediately on tool call
        await self._update_status_message()

        if self._on_tool_call:
            await self._on_tool_call(tool_name, tool_args)

        # Execute Discord-native and Self-Memory tools
        if tool_name.startswith(("discord_", "self_memory_")):
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

        elif tool_name == "self_memory_add_fact":
            content = tool_args.get("content", "")
            if not content:
                return json.dumps({"error": "content required"})
            category = tool_args.get("category", "other")
            
            memory = get_self_memory()
            fact_id = memory.add_learned_fact(
                content=content,
                source_type="conversation",
                source_ref=self.context.conversation_id,
                category=category,
                confidence=0.8
            )
            return json.dumps({"added": True, "fact_id": fact_id, "content": content})

        elif tool_name == "self_memory_add_reflection":
            content = tool_args.get("content", "")
            if not content:
                return json.dumps({"error": "content required"})
            importance = float(tool_args.get("importance", 1.0))
            
            memory = get_self_memory()
            reflection_id = memory.add_reflection(
                trigger="conversation",
                content=content,
                importance=importance,
                category="realization",
                conversation_id=self.context.conversation_id
            )
            return json.dumps({"added": True, "reflection_id": reflection_id})

        else:
            return json.dumps({"error": f"Unknown Discord/Bot tool: {tool_name}"})

    async def _handle_tool_result(self, chunk: JobChunk) -> None:
        """Handle a tool result chunk."""
        # Tool results are processed internally, no user-facing action needed
        pass

    async def _handle_progress(self, chunk: JobChunk) -> None:
        """Handle a progress update."""
        if not chunk.metadata:
            return

        # Track step and tokens from progress updates
        step = chunk.metadata.get("step", 0)
        if step > 0:
            self.current_step = max(self.current_step, step)

        tokens = chunk.metadata.get("tokens", 0)
        if tokens > 0:
            self.tokens_generated = max(self.tokens_generated, tokens)

        if not self.config.enable_progress_updates:
            return

        content = chunk.content
        percent = chunk.metadata.get("percent")

        # Only show significant progress updates (every 20%)
        if percent and int(percent) % 20 == 0:
            logger.debug(f"Progress: {percent}% - {content}")

    async def _handle_final(self, chunk: JobChunk) -> None:
        """Handle the final result."""
        self.final_result = chunk.content or "(no result)"
        self.is_complete = True
        self.is_running = False

        # Track tokens from final chunk
        if chunk.metadata:
            tokens = chunk.metadata.get("tokens", 0)
            if tokens > 0:
                self.tokens_generated = max(self.tokens_generated, tokens)

        logger.info(f"Agentic session complete. Final result length: {len(self.final_result)}")

        # Finalize status message
        await self._finalize_status_message("✅ Complete")

        # Send the final result to Discord
        if self._on_complete:
            await self._on_complete(self.final_result)
        else:
            # Send the final result as a message
            await self._send_message(self.final_result)

        # Check for follow-up jobs in the result
        await self._check_and_handle_followups()

        # Clear thinking reactions and add completion reaction
        try:
            await self.message.clear_reactions()
            await self.message.add_reaction("✅")
        except Exception as e:
            logger.debug(f"Failed to update reactions: {e}")

    async def _check_and_handle_followups(self) -> None:
        """Check for follow-up jobs in the final result and poll for their completion."""
        if not self.final_result:
            return

        try:
            # Try to parse the result as JSON
            result_data = json.loads(self.final_result)

            # Check if this result has a followup job
            if isinstance(result_data, dict):
                # Check for followup job in the result envelope
                followup = result_data.get("followup")
                if followup and isinstance(followup, dict):
                    followup_job_id = followup.get("job_id")
                    if followup_job_id:
                        self.followup_job_ids.append(followup_job_id)
                        logger.info(f"Detected follow-up job {followup_job_id}, will poll for results")
                        # Start polling for the follow-up job
                        asyncio.create_task(self._poll_followup_job(followup_job_id))

                # Also check tool calls for create_followup_job results
                tool_calls = result_data.get("tool_calls", [])
                for tc in tool_calls:
                    if tc.get("name") == "create_followup_job":
                        # Parse the output to get the job ID
                        output = tc.get("truncated_output", "")
                        try:
                            output_data = json.loads(output)
                            if output_data.get("success"):
                                job_id = output_data.get("job_id")
                                if job_id and job_id not in self.followup_job_ids:
                                    self.followup_job_ids.append(job_id)
                                    logger.info(f"Detected follow-up job {job_id} from tool call, will poll for results")
                                    asyncio.create_task(self._poll_followup_job(job_id))
                        except json.JSONDecodeError:
                            pass

        except json.JSONDecodeError:
            # Result is not JSON, no follow-up to process
            pass
        except Exception as e:
            logger.exception(f"Error checking for follow-up jobs: {e}")

    async def _poll_followup_job(self, followup_job_id: str) -> None:
        """Poll for a follow-up job's completion and stream results."""
        import os
        import aiohttp

        broker_url = os.environ.get("BROKER_URL", "http://127.0.0.1:8000").rstrip("/")
        bot_token = os.environ.get("BOT_TOKEN", "")

        max_wait = 600  # Maximum 10 minutes wait for follow-up
        poll_interval = 2.0
        waited = 0

        logger.info(f"Starting to poll for follow-up job {followup_job_id}")

        await self._send_message(f"⏳ Continuing work in follow-up job...")

        try:
            while waited < max_wait:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{broker_url}/jobs/{followup_job_id}",
                        headers={"X-Bot-Token": bot_token},
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            status = data.get("status")

                            if status == "done":
                                # Job is complete, get the result
                                result = data.get("result", "")
                                logger.info(f"Follow-up job {followup_job_id} completed")
                                await self._send_message(f"✅ Follow-up work complete!")
                                if result:
                                    # Try to parse and extract just the final result
                                    try:
                                        result_data = json.loads(result)
                                        final_text = result_data.get("final", result)
                                        if final_text and final_text != self.final_result:
                                            await self._send_message(final_text[:1900])
                                    except json.JSONDecodeError:
                                        if result != self.final_result:
                                            await self._send_message(result[:1900])
                                return

                            elif status == "failed":
                                error = data.get("error", "Unknown error")
                                logger.error(f"Follow-up job {followup_job_id} failed: {error}")
                                await self._send_message(f"❌ Follow-up job failed: {error[:500]}")
                                return

                            elif status == "running":
                                # Job is still running, poll for chunks if streaming
                                try:
                                    async for chunk in self.streaming_client.poll_chunks(
                                        followup_job_id,
                                        poll_interval=1.0,
                                        absolute_timeout=30,
                                    ):
                                        if chunk.chunk_type == "final":
                                            logger.info(f"Got final chunk from follow-up job {followup_job_id}")
                                            if chunk.content and chunk.content != self.final_result:
                                                await self._send_message(chunk.content[:1900])
                                            return
                                        elif chunk.chunk_type == "message":
                                            if chunk.content:
                                                await self._send_message(chunk.content[:1900])
                                except Exception as e:
                                    logger.debug(f"Error polling chunks for follow-up: {e}")

                # Wait before next poll
                await asyncio.sleep(poll_interval)
                waited += poll_interval

            # Max wait exceeded
            logger.warning(f"Follow-up job {followup_job_id} did not complete within {max_wait}s")
            await self._send_message(f"⏱️ Follow-up job is still running. You can check status later with job ID: `{followup_job_id}`")

        except Exception as e:
            logger.exception(f"Error polling follow-up job {followup_job_id}: {e}")
            await self._send_message(f"⚠️ Error checking follow-up job: {str(e)[:200]}")

    async def _handle_heartbeat(self, chunk: JobChunk) -> None:
        """Handle a heartbeat - update status message with current metrics."""
        # Update status message every few seconds to avoid rate limits
        now = time.time()
        if now - self.last_status_update >= 3.0:  # Update every 3 seconds
            await self._update_status_message()
            self.last_status_update = now

    async def _send_initial_status_message(self) -> None:
        """Send the initial status message that will be updated during processing."""
        try:
            status_text = self._format_status_message()
            self.status_message = await self.message.channel.send(status_text[:2000])
        except Exception as e:
            logger.warning(f"Failed to send initial status message: {e}")

    def _format_status_message(self) -> str:
        """Format the current status as a message string."""
        elapsed = time.time() - self.start_time if self.start_time > 0 else 0
        gpu_percent = self._get_gpu_usage()

        # Calculate tokens per second
        tokens_per_sec = 0.0
        if elapsed > 0:
            tokens_per_sec = self.tokens_generated / elapsed

        # Progress bar
        progress = min(100, (self.current_step / self.total_steps) * 100) if self.total_steps > 0 else 0
        bar_length = 10
        filled = int(bar_length * progress / 100)
        bar = "█" * filled + "░" * (bar_length - filled)

        # Format the status message
        status_lines = [
            "🤔 **Working on your request...**",
            f"",
            f"⏱️ Elapsed: {elapsed:.1f}s | 📝 Tokens: {self.tokens_generated} ({tokens_per_sec:.1f}/s)",
            f"🔄 Step: {self.current_step}/{self.total_steps} [{bar}] {progress:.0f}%",
        ]

        if gpu_percent > 0:
            status_lines.append(f"🎮 GPU: {gpu_percent:.1f}%")

        if self.job_id:
            status_lines.append(f"🆔 Job: `{self.job_id[:8]}...`")

        return "\n".join(status_lines)

    def _get_gpu_usage(self) -> float:
        """Get current GPU usage percentage. Returns 0 if unavailable."""
        try:
            # Try nvidia-smi first
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=1
            )
            if result.returncode == 0:
                usage = float(result.stdout.strip().split('\n')[0])
                self.gpu_usage_history.append(usage)
                if len(self.gpu_usage_history) > 10:
                    self.gpu_usage_history.pop(0)
                return sum(self.gpu_usage_history) / len(self.gpu_usage_history)
        except Exception:
            pass

        # Try ROCm (AMD)
        try:
            import subprocess
            result = subprocess.run(
                ["rocm-smi", "--showuse"],
                capture_output=True,
                text=True,
                timeout=1
            )
            if result.returncode == 0:
                # Parse GPU usage from rocm-smi output
                for line in result.stdout.split('\n'):
                    if '%' in line and 'GPU' in line:
                        parts = line.split()
                        for part in parts:
                            if '%' in part:
                                try:
                                    usage = float(part.replace('%', ''))
                                    self.gpu_usage_history.append(usage)
                                    if len(self.gpu_usage_history) > 10:
                                        self.gpu_usage_history.pop(0)
                                    return sum(self.gpu_usage_history) / len(self.gpu_usage_history)
                                except ValueError:
                                    continue
        except Exception:
            pass

        return 0.0

    async def _update_status_message(self) -> None:
        """Update the status message with current metrics."""
        if not self.status_message:
            return

        try:
            status_text = self._format_status_message()
            await self.status_message.edit(content=status_text[:2000])
        except Exception as e:
            logger.debug(f"Failed to update status message: {e}")

    async def _finalize_status_message(self, status: str = "✅ Complete") -> None:
        """Finalize the status message when done."""
        if not self.status_message:
            return

        try:
            elapsed = time.time() - self.start_time if self.start_time > 0 else 0
            final_text = (
                f"{status}\n"
                f"⏱️ Total time: {elapsed:.1f}s | 📝 Tokens generated: {self.tokens_generated}\n"
                f"🔄 Steps completed: {self.current_step}/{self.total_steps}"
            )
            await self.status_message.edit(content=final_text[:2000])
        except Exception as e:
            logger.debug(f"Failed to finalize status message: {e}")

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
