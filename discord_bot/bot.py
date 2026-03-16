"""
OpenClaw Discord Bot — creates jobs from DMs and replies with results.
Only responds to DMs (or optional single channel). Allowlist: one or more Discord user IDs.
Commands: ping, capabilities, plan, approve, status, repos, repostat, last, grep, cat, whoami.
Guardrails: cooldown, max concurrent.
"""

import json
import logging
import os
import re
import sys
import time
from typing import Optional
from urllib.parse import urlparse

import discord
import requests

from discord_bot.redaction import redact_for_display as _redact_for_display

logger = logging.getLogger(__name__)

# Import conversational features (optional - graceful degradation if not available)
try:
    from .chat_commands import (
        handle_chat_command,
        handle_persona_command,
        handle_memory_command,
        handle_remember_command,
        handle_history_command,
        handle_conversations_command,
        handle_website_command,
        handle_website_post_command,
        format_thinking_as_spoilers,
    )
    from .memory import get_memory
    from .self_memory import get_self_memory
    from .personality import get_personality_engine
    from .natural_language_router import detect_intent
    from .agentic_session import (
        AgenticConfig,
        get_agentic_manager,
    )
    HAS_CONVERSATION_FEATURES = True
    HAS_NL_ROUTER = True
    HAS_AGENTIC_MODE = True
except ImportError as e:
    HAS_CONVERSATION_FEATURES = False
    HAS_NL_ROUTER = False
    HAS_AGENTIC_MODE = False
    logger.warning(f"Conversation features not available: {e}")

# --- Config from env ---
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
BROKER_URL = os.environ.get("BROKER_URL", "http://127.0.0.1:8000").strip().rstrip("/")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")  # X-Bot-Token for broker API
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID", "").strip()  # single user ID (backward compat)
ALLOWLIST_USER_ID = os.environ.get("ALLOWLIST_USER_ID", "").strip()  # optional: comma/space separated IDs
ALLOWED_CHANNEL_ID = os.environ.get("ALLOWED_CHANNEL_ID", "").strip()  # optional: single channel (empty = DMs only)
JOB_POLL_INTERVAL_SEC = float(os.environ.get("JOB_POLL_INTERVAL_SEC", "2"))
JOB_POLL_TIMEOUT_SEC = float(os.environ.get("JOB_POLL_TIMEOUT_SEC", "120"))
BOT_COOLDOWN_SECONDS = float(os.environ.get("BOT_COOLDOWN_SECONDS", "3"))
BOT_MAX_CONCURRENT = int(os.environ.get("BOT_MAX_CONCURRENT", "1"))
INSTANCE_NAME = os.environ.get("INSTANCE_NAME", "default")
WHOAMI_BROKER_URL_MODE = os.environ.get("WHOAMI_BROKER_URL_MODE", "full").strip().lower()
BOT_PRESENCE = os.environ.get("BOT_PRESENCE", "Listening to DMs").strip()

# --- Conversation/Memory Feature Config ---
MEMORY_ENABLED = os.environ.get("MEMORY_ENABLED", "true").lower() in ("true", "1", "yes")
MEMORY_DB_PATH = os.environ.get("MEMORY_DB_PATH", "discord_bot_memory.db")
SELF_MEMORY_DB_PATH = os.environ.get("SELF_MEMORY_DB_PATH", "urgo_self_memory.db")
DEFAULT_PERSONA = os.environ.get("DEFAULT_PERSONA", "helpful_assistant")
CUSTOM_PERSONAS_PATH = os.environ.get("CUSTOM_PERSONAS_PATH", "custom_personas.json")
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "none").lower()  # 'openai', 'local', 'remote', 'none'
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
CONVERSATION_TIMEOUT_MINUTES = float(os.environ.get("CONVERSATION_TIMEOUT_MINUTES", "30"))

# --- Agentic Mode Config ---
AGENTIC_MODE = os.environ.get("AGENTIC_MODE", "true").lower() in ("true", "1", "yes")
AGENTIC_AUTO_TRIGGER = os.environ.get("AGENTIC_AUTO_TRIGGER", "true").lower() in ("true", "1", "yes")
# Intelligent termination: No hard timeouts - relies on idle detection and stuck-loop detection
# AGENTIC_IDLE_TIMEOUT (default: 600s) controls max time without chunks/heartbeats
# Sessions run indefinitely as long as progress is being made
# This value is a legacy safety valve - streaming client's intelligent detection is primary
AGENTIC_MAX_STREAM_WAIT = float(os.environ.get("AGENTIC_MAX_STREAM_WAIT", "1800"))  # 30 min max as safety valve
AGENTIC_DEFAULT_MAX_STEPS = int(os.environ.get("AGENTIC_DEFAULT_MAX_STEPS", "25"))

MAX_DISPLAY_LEN = 1500

# Broker HTTP timeouts: (connect, read) in seconds — avoid hanging if broker is down
BROKER_CONNECT_TIMEOUT = 5
BROKER_READ_TIMEOUT = 15

# Allowlist: union of ALLOWED_USER_ID (single) and ALLOWLIST_USER_ID (comma/space separated)
def _normalize_allowlist_id(raw: str) -> str:
    """Strip whitespace (including CRLF) and surrounding quotes so env values match Discord IDs."""
    s = raw.strip().strip("\r\n")
    if len(s) >= 2 and (s[0] == s[-1] == '"' or s[0] == s[-1] == "'"):
        s = s[1:-1].strip()
    return s


def _parse_allowlist_ids() -> set[str]:
    ids: set[str] = set()
    if ALLOWED_USER_ID:
        n = _normalize_allowlist_id(ALLOWED_USER_ID)
        if n:
            ids.add(n)
    for part in re.split(r"[\s,]+", ALLOWLIST_USER_ID):
        if part:
            n = _normalize_allowlist_id(part)
            if n:
                ids.add(n)
    return ids


ALLOWLIST_IDS = _parse_allowlist_ids()


def redact(text: str) -> str:
    """Apply redaction and instruction-leak guard for user-facing output."""
    return _redact_for_display(text, BOT_TOKEN, DISCORD_TOKEN)


def _strip_phrase_any_case(text: str, phrase: str) -> str:
    """Remove the first occurrence of phrase from text (case-insensitive). Returns stripped result."""
    tl = text.lower()
    idx = tl.find(phrase.lower())
    if idx < 0:
        return text.strip()
    return (text[:idx] + text[idx + len(phrase) :]).strip()


def _has_url(text: str) -> bool:
    """Check if text contains a URL (http or https)."""
    return bool(re.search(r'https?://[^\s]+', text))


def _allowlist_display() -> str:
    """Summary string for whoami (allowlist status)."""
    if not ALLOWLIST_IDS:
        return "not set"
    return ", ".join(sorted(ALLOWLIST_IDS))


def whoami_broker_url_display(broker_url: str, mode: str) -> str:
    """Return the broker URL string to show in whoami. mode: full, masked, hidden."""
    if mode == "hidden":
        return "(hidden)"
    if mode == "masked":
        try:
            p = urlparse(broker_url)
            if p.scheme and p.netloc:
                return f"{p.scheme}://{p.netloc}"
            return broker_url
        except Exception:
            return "(hidden)"
    return broker_url


def format_whoami(instance_name: str, bot_user_id: str, broker_url: str, allowed_user_id: str) -> str:
    """Build whoami reply from config (testable)."""
    allowed = allowed_user_id if allowed_user_id else "not set"
    return (
        f"**Instance:** {instance_name}\n"
        f"**Bot user ID:** {bot_user_id}\n"
        f"**Broker URL:** {broker_url}\n"
        f"**Allowlisted user ID:** {allowed}"
    )


def is_allowed(channel: discord.abc.Messageable, author_id: str) -> bool:
    if str(author_id) not in ALLOWLIST_IDS:
        return False
    if not ALLOWED_CHANNEL_ID:
        return isinstance(channel, discord.DMChannel)
    return str(channel.id) == str(ALLOWED_CHANNEL_ID)


# Per-user state: last command time and active job ids (in-memory)
def _user_state(user_id: str) -> dict:
    uid = str(user_id)
    if uid not in _user_states:
        _user_states[uid] = {"last_ts": 0.0, "active_jobs": set()}
    return _user_states[uid]


_user_states: dict[str, dict] = {}


def create_job(command: str, payload: str, requires: str | None = None) -> dict:
    body: dict = {"command": command, "payload": payload}
    if requires is not None:
        body["requires"] = requires
    r = requests.post(
        f"{BROKER_URL}/jobs",
        headers={"X-Bot-Token": BOT_TOKEN},
        json=body,
        timeout=(BROKER_CONNECT_TIMEOUT, BROKER_READ_TIMEOUT),
    )
    r.raise_for_status()
    return r.json()


def get_job(job_id: str) -> dict:
    r = requests.get(
        f"{BROKER_URL}/jobs/{job_id}",
        headers={"X-Bot-Token": BOT_TOKEN},
        timeout=(BROKER_CONNECT_TIMEOUT, BROKER_READ_TIMEOUT),
    )
    r.raise_for_status()
    return r.json()


def wait_for_job_result(job_id: str) -> tuple[str, bool]:
    """
    Poll until job is done or failed or timeout.
    Returns (message, timed_out). If timed_out, message is the "still running" text.
    Uses gentle backoff: 0.5s → 1s → 2s (capped) between polls to avoid spamming the broker.
    """
    deadline = time.monotonic() + JOB_POLL_TIMEOUT_SEC
    poll_backoff_cap = min(2.0, max(0.5, JOB_POLL_INTERVAL_SEC))
    sleep_sec = 0.5
    while time.monotonic() < deadline:
        job = get_job(job_id)
        status = job.get("status", "")
        if status == "done":
            return (job.get("result") or "(no result)", False)
        if status == "failed":
            err = job.get("error") or job.get("result") or "unknown"
            return (f"Job failed: {err}", False)
        time.sleep(sleep_sec)
        sleep_sec = min(sleep_sec * 2, poll_backoff_cap)
    return (f"Still running. Job ID: {job_id} (try: status {job_id})", True)


def truncate_for_display(text: str, job_id: str) -> str:
    """If text is long, truncate and tell user to use status <id>."""
    if len(text) <= MAX_DISPLAY_LEN:
        return text
    return text[:MAX_DISPLAY_LEN] + "… (use `status " + job_id + "` for full output)."


def _format_repo_envelope(envelope: dict, job_id: str) -> str:
    """Build display string from runner repo envelope. Returns formatted text; caller applies truncate_for_display."""
    if not envelope.get("ok", True):
        return "Error: " + (envelope.get("error") or "unknown")
    data = envelope.get("data")
    truncated_note = " *(truncated)*" if envelope.get("truncated") else ""
    if data is None:
        return "(no data)" + truncated_note
    cmd = envelope.get("command", "")
    lines = []
    if cmd == "repo_list":
        repos = data.get("repos", [])
        for r in repos:
            lines.append(f"**{r.get('name', '?')}**: `{r.get('path', '')}`")
        return "\n".join(lines) if lines else "(no repos)" + truncated_note
    if cmd == "repo_status":
        lines.append(f"**Branch:** {data.get('branch', '?')}")
        lines.append(f"**Dirty:** {data.get('dirty', False)}")
        porcelain = data.get("porcelain", "")
        if porcelain:
            lines.append("```\n" + porcelain + "\n```")
        return "\n".join(lines) + truncated_note
    if cmd == "repo_last_commit":
        lines.append(f"**{data.get('hash', '?')}**")
        lines.append(f"**{data.get('author', '?')}** — {data.get('date', '?')}")
        lines.append(data.get("subject", ""))
        return "\n".join(lines) + truncated_note
    if cmd == "repo_grep":
        matches = data.get("matches", "")
        return ("```\n" + matches + "\n```") if matches else "(no matches)" + truncated_note
    if cmd == "repo_readfile":
        lines.append(f"`{data.get('path', '?')}` lines {data.get('start', 0)}-{data.get('end', 0)}:")
        lines.append("```\n" + (data.get("content") or "") + "\n```")
        return "\n".join(lines) + truncated_note
    return json.dumps(data) + truncated_note


intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
client = discord.Client(intents=intents)


async def set_bot_presence(
    text: str = "Listening to DMs",
    activity_type: str = "listening",
    status: str = "online",
) -> None:
    """
    Set the bot's Discord presence.

    Args:
        text: Activity description text.
        activity_type: One of 'playing', 'listening', 'watching', 'competing', 'custom'.
        status: One of 'online', 'idle', 'dnd', 'invisible'.
    """
    activity_map = {
        "playing": discord.ActivityType.playing,
        "listening": discord.ActivityType.listening,
        "watching": discord.ActivityType.watching,
        "competing": discord.ActivityType.competing,
        "custom": discord.ActivityType.custom,
    }
    status_map = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
        "invisible": discord.Status.invisible,
    }
    act_type = activity_map.get(activity_type.lower(), discord.ActivityType.listening)
    disc_status = status_map.get(status.lower(), discord.Status.online)
    activity = discord.Activity(type=act_type, name=text)
    await client.change_presence(activity=activity, status=disc_status)
    logger.info(f"Presence set: {activity_type} '{text}' ({status})")


@client.event
async def on_ready():
    bot_id = str(client.user.id) if client.user else "?"
    logger.info(f"logged in as {client.user} (id={bot_id})")
    logger.info(f"INSTANCE_NAME={INSTANCE_NAME} BROKER_URL={BROKER_URL}")
    
    # Set initial presence
    try:
        await set_bot_presence(BOT_PRESENCE)
    except Exception as e:
        logger.warning(f"Failed to set initial presence: {e}")
    
    # Show conversation features status
    if HAS_CONVERSATION_FEATURES:
        logger.info("Conversation features: available")
        logger.info(f"  Memory enabled: {MEMORY_ENABLED}")
        logger.info(f"  Default persona: {DEFAULT_PERSONA}")
        logger.info(f"  Embeddings: {EMBEDDING_PROVIDER}")
    else:
        logger.info("Conversation features: not available (import error)")


async def _run_job_and_reply(
    message: discord.Message,
    command: str,
    payload: str,
    reply_prefix: str = "Job created: ",
    parse_json: bool = False,
    requires: str | None = None,
) -> None:
    """Create job, wait for result, reply. Enforces guardrails and updates active_jobs."""
    user_id = str(message.author.id)
    state = _user_state(user_id)
    now_ts = time.monotonic()
    job_id: Optional[str] = None

    if now_ts - state["last_ts"] < BOT_COOLDOWN_SECONDS:
        await message.reply("Please wait a few seconds between commands.")
        return
    if len(state["active_jobs"]) >= BOT_MAX_CONCURRENT:
        await message.reply(
            f"You have the maximum number of jobs in progress ({BOT_MAX_CONCURRENT}). "
            "Wait for one to finish or use `status <id>`."
        )
        return

    try:
        async with message.channel.typing():
            job = create_job(command=command, payload=payload, requires=requires)
            job_id = job.get("id")
            if not job_id:
                await message.reply("Failed to create job (no id).")
                return
            state["active_jobs"].add(job_id)
            state["last_ts"] = now_ts

            await message.reply(f"{reply_prefix}`{job_id}`. Waiting for result…")
            result, timed_out = wait_for_job_result(job_id)
            display = result
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "ok" in parsed and "command" in parsed:
                    display = _format_repo_envelope(parsed, job_id)
                elif parse_json:
                    if command == "capabilities":
                        worker_id = parsed.get("worker_id", "?")
                        caps = parsed.get("capabilities", [])
                        display = f"Worker: `{worker_id}`\nCapabilities: {', '.join(caps)}"
                    elif command == "plan_echo":
                        plan_id = parsed.get("plan_id", "?")
                        summary = parsed.get("summary", "")
                        display = f"Plan ID: `{plan_id}`\nSummary: {summary}\nTo apply: `approve {plan_id}`"
                    elif command == "approve_echo":
                        status = parsed.get("status", "?")
                        note = parsed.get("note", "")
                        display = f"Status: {status}\n{note}" if note else f"Status: {status}"
                    elif command == "llm_task":
                        display = parsed.get("final", result)
                        if not display and parsed.get("safety"):
                            display = "(no final answer)" + (
                                " — max steps reached." if parsed.get("safety", {}).get("max_steps_reached") else ""
                            )
                        # Apply thinking block formatting to hide reasoning content
                        if HAS_CONVERSATION_FEATURES:
                            display = format_thinking_as_spoilers(display)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
            display = truncate_for_display(redact(display), job_id)
            await message.reply(display)
    except requests.RequestException as e:
        await message.reply(redact(f"Broker error: {e}"))
    except Exception as e:
        await message.reply(redact(f"Error: {e}"))
    finally:
        if job_id:
            state["active_jobs"].discard(job_id)


async def reply_in_chunks(message: discord.Message, text: str):
    """Split text into chunks if it exceeds Discord's 2000-character limit."""
    if not text:
        return
    
    chunk_size = 1900
    chunks = []
    current_chunk = ""
    
    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 1 > chunk_size:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = line + "\n"
            else:
                # A single line is longer than chunk_size, hard split
                while len(line) > chunk_size:
                    chunks.append(line[:chunk_size])
                    line = line[chunk_size:]
                current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
            
    if current_chunk:
        chunks.append(current_chunk)
        
    for i, chunk in enumerate(chunks):
        chunk_str = chunk.strip()
        if not chunk_str:
            continue
        if i == 0:
            await message.reply(chunk_str)
        else:
            await message.channel.send(chunk_str)


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    # Polite refusal in DMs when user is not allowlisted (no reply in channels to avoid spam)
    if isinstance(message.channel, discord.DMChannel) and str(message.author.id) not in ALLOWLIST_IDS:
        await message.reply("You are not authorized to use this bot.")
        return
    if not is_allowed(message.channel, message.author.id):
        return
    text = (message.content or "").strip()
    if not text:
        return
    parts = text.split(maxsplit=1)
    cmd = (parts[0] or "").lower()
    payload = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "ping":
        await _run_job_and_reply(message, "ping", payload)
        return

    if cmd == "capabilities":
        await _run_job_and_reply(message, "capabilities", "", parse_json=True)
        return

    if cmd == "plan":
        await _run_job_and_reply(
            message, "plan_echo", payload, reply_prefix="Plan job: ", parse_json=True
        )
        return

    if cmd == "approve":
        if not payload:
            await message.reply("Usage: `approve <plan_id>`")
            return
        await _run_job_and_reply(
            message, "approve_echo", payload, reply_prefix="Approval job: ", parse_json=True
        )
        return

    if cmd == "status":
        if not payload:
            await message.reply("Usage: `status <job_id>`")
            return
        job_id = payload.strip()
        try:
            job = get_job(job_id)
        except requests.RequestException as e:
            await message.reply(redact(f"Broker error: {e}"))
            return
        status = job.get("status", "?")
        lines = [f"Job `{job_id}`: **{status}**"]
        if status == "done":
            result = job.get("result") or "(no result)"
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "ok" in parsed and "command" in parsed:
                    result = _format_repo_envelope(parsed, job_id)
            except (json.JSONDecodeError, TypeError):
                pass
            lines.append(truncate_for_display(redact(result), job_id))
        elif status == "failed":
            err = job.get("error") or job.get("result") or "unknown"
            lines.append(truncate_for_display(redact(f"Error: {err}"), job_id))
        await message.reply("\n".join(lines))
        return

    if cmd == "repos":
        await _run_job_and_reply(message, "repo_list", "", reply_prefix="Repos: ")
        return

    if cmd == "repostat":
        if not payload:
            await message.reply("Usage: `repostat <repo>`")
            return
        repo = payload.strip().split()[0]
        await _run_job_and_reply(
            message,
            "repo_status",
            json.dumps({"repo": repo}),
            reply_prefix="Repo status: ",
        )
        return

    if cmd == "last":
        if not payload:
            await message.reply("Usage: `last <repo>`")
            return
        repo = payload.strip().split()[0]
        await _run_job_and_reply(
            message,
            "repo_last_commit",
            json.dumps({"repo": repo}),
            reply_prefix="Last commit: ",
        )
        return

    if cmd == "grep":
        parts = payload.strip().split(maxsplit=2)
        if len(parts) < 2:
            await message.reply("Usage: `grep <repo> <query> [path]`")
            return
        repo = parts[0]
        query = parts[1] if len(parts) > 1 else ""
        path = parts[2] if len(parts) > 2 else ""
        await _run_job_and_reply(
            message,
            "repo_grep",
            json.dumps({"repo": repo, "query": query, "path": path}),
            reply_prefix="Grep: ",
        )
        return

    if cmd == "cat":
        parts = payload.strip().split(maxsplit=3)
        if len(parts) < 2:
            await message.reply("Usage: `cat <repo> <path> [start] [end]`")
            return
        repo = parts[0]
        path = parts[1]
        start = 1
        end = 200
        if len(parts) > 2:
            try:
                start = int(parts[2])
                end = start + 199
            except ValueError:
                pass
        if len(parts) > 3:
            try:
                end = int(parts[3])
            except ValueError:
                pass
        await _run_job_and_reply(
            message,
            "repo_readfile",
            json.dumps({"repo": repo, "path": path, "start": start, "end": end}),
            reply_prefix="File: ",
        )
        return

    if cmd == "whoami":
        bot_id = str(client.user.id) if client.user else "?"
        broker_display = whoami_broker_url_display(BROKER_URL, WHOAMI_BROKER_URL_MODE)
        lines = [
            format_whoami(INSTANCE_NAME, bot_id, broker_display, _allowlist_display())
        ]
        if HAS_CONVERSATION_FEATURES and MEMORY_ENABLED:
            lines.append(f"**Memory:** enabled ({EMBEDDING_PROVIDER} embeddings)")
            lines.append(f"**Default persona:** {DEFAULT_PERSONA}")
        await message.reply("\n".join(lines))
        return

    if cmd == "presence":
        if not payload:
            await message.reply(
                "Usage: `presence [playing|listening|watching|competing] <text>`\n"
                "Example: `presence watching the stars`"
            )
            return
        # Parse activity type from first word if it matches a known type
        presence_parts = payload.strip().split(maxsplit=1)
        first_word = presence_parts[0].lower()
        known_types = ("playing", "listening", "watching", "competing")
        if first_word in known_types and len(presence_parts) > 1:
            act_type = first_word
            act_text = presence_parts[1]
        else:
            act_type = "playing"
            act_text = payload.strip()
        try:
            await set_bot_presence(act_text, act_type)
            await message.reply(f"Presence updated: **{act_type}** {act_text}")
        except Exception as e:
            await message.reply(f"Failed to update presence: {e}")
        return

    # --- Agentic Mode Command ---
    if HAS_AGENTIC_MODE and AGENTIC_MODE and cmd == "agentic":
        if not payload:
            await message.reply(
                "**Agentic Mode** - Streaming multi-turn conversations with tool calling.\n\n"
                "Usage: `agentic <your request>`\n\n"
                "This mode enables:\n"
                "- Real-time streaming responses\n"
                "- Multi-turn tool loops\n"
                "- Intermediate progress updates\n"
                "- Discord-native interactions\n\n"
                "Natural language requests with tool intents will auto-trigger agentic mode."
            )
            return

        await handle_agentic_command(message, payload)
        return

    # --- Conversational/Chat Commands ---
    if HAS_CONVERSATION_FEATURES and MEMORY_ENABLED:
        if cmd == "persona":
            async with message.channel.typing():
                response = await handle_persona_command(bot_instance(), message, payload)
            await reply_in_chunks(message, response)
            return

        if cmd == "memory":
            async with message.channel.typing():
                response = await handle_memory_command(bot_instance(), message, payload)
            await reply_in_chunks(message, response)
            return

        if cmd == "remember":
            if not payload:
                await message.reply("What should I remember? Usage: `remember <fact>`")
                return
            async with message.channel.typing():
                response = await handle_remember_command(bot_instance(), message, payload)
            await reply_in_chunks(message, response)
            return

        if cmd == "history":
            async with message.channel.typing():
                response = await handle_history_command(bot_instance(), message, payload)
            await reply_in_chunks(message, response)
            return
        
        if cmd == "conversations" or cmd == "conv":
            async with message.channel.typing():
                response = await handle_conversations_command(bot_instance(), message, payload)
            await reply_in_chunks(message, response)
            return
        
        # Website management commands
        if cmd == "website":
            async with message.channel.typing():
                response = await handle_website_command(bot_instance(), message, payload)
            await reply_in_chunks(message, response)
            return
        
        if cmd == "website_post":
            # Permission check for post creation
            if hasattr(message, 'guild') and message.guild:
                return "📝 Post creation is only available in DMs to prevent spam."
            async with message.channel.typing():
                response = await handle_website_post_command(bot_instance(), message, payload)
            await reply_in_chunks(message, response)
            return

    # Explicit help command
    if cmd in ("help", "commands"):
        help_lines = [
            "**Available Commands:**",
            "",
            "**Job Commands:**",
            "`ping <text>` - Test connectivity",
            "`capabilities` - Show worker capabilities",
            "`plan <text>` - Create execution plan",
            "`approve <plan_id>` - Approve a plan",
            "`status <job_id>` - Check job status",
            "",
            "**Repository Commands:**",
            "`repos` - List available repos",
            "`repostat <repo>` - Get repo status",
            "`last <repo>` - Show last commit",
            "`grep <repo> <query> [path]` - Search repo",
            "`cat <repo> <path> [start] [end]` - Read file",
            "",
            "**Website Commands:**",
            "`website init` - Initialize AI website",
            "`website status` - Show website stats",
            "`website regenerate` - Full site regeneration",
            "`website sync` - Sync from memory",
            "`website customize` - Show theme settings",
            "`website nginx` - Nginx status",
        ]

        if HAS_CONVERSATION_FEATURES and MEMORY_ENABLED:
            help_lines.extend([
                "",
                "**Natural Language - Just Talk to Me!**",
                "I understand natural language. Try these:",
                "• \"Show me my repos\" - List repositories",
                "• \"Find auth code in openclaw\" - Search code",
                "• \"Read the main.py file\" - View files",
                "• \"Remember I like pizza\" - Store facts",
                "• \"Search the web for Python tips\" - Web research",
                "• \"List my GitHub issues\" - GitHub operations",
                "",
                "**Agentic Mode (Streaming):**",
                "`agentic <request>` - Multi-turn streaming with tools",
                "",
                "**Conversation Commands:**",
                "`persona [name]` - Switch personality",
                "`memory [status/clear/on/off]` - Memory management",
                "`remember <fact>` - Remember a fact",
                "`history [n]` - Show conversation history",
                "`conversations [new/switch/rename/archive/resume]` - Manage conversations",
                "",
                "*(You don't need to use a command—just say what you want!)*",
            ])

        help_lines.extend([
            "",
            "**Info:**",
            "`whoami` - Show bot info",
            "`presence [type] <text>` - Set bot status (playing/listening/watching/competing)",
        ])

        await message.reply("\n".join(help_lines))
        return

    # Unified Natural Language Handler
    # Routes all non-command messages through intent detection and appropriate handlers
    if HAS_CONVERSATION_FEATURES and MEMORY_ENABLED and HAS_NL_ROUTER:
        try:
            # Detect intent from natural language
            intent_result = detect_intent(text)
            logger.info(f"Natural language intent detected: {intent_result.intent} "
                       f"(confidence: {intent_result.confidence:.2f}) for user {message.author.id}")
            
            # AGENTIC-FIRST ROUTING: Agentic mode is the DEFAULT for almost everything
            # This gives the LLM full autonomy to use tools and multi-turn reasoning

            logger.info(f"Intent detected: {intent_result.intent} (confidence: {intent_result.confidence:.2f}). "
                       f"HAS_AGENTIC={HAS_AGENTIC_MODE}, AGENTIC_MODE={AGENTIC_MODE}")

            # FORCE AGENTIC MODE for:
            # 1. Any message containing a URL (web research, browsing, etc.)
            # 2. Any intent that suggests tool usage (web_research, repo_search, file_read, etc.)
            # 3. Low confidence detection (let the LLM figure it out)
            force_agentic = False
            agentic_reason = ""

            if _has_url(text):
                force_agentic = True
                agentic_reason = "URL detected"
            elif intent_result.intent in ("web_research", "repo_search", "file_read", "repo_explore", "github_ops", "website_manage"):
                force_agentic = True
                agentic_reason = f"tool intent: {intent_result.intent}"
            elif intent_result.confidence < 0.5:
                force_agentic = True
                agentic_reason = f"low confidence ({intent_result.confidence:.2f}), letting LLM decide"

            if force_agentic and HAS_AGENTIC_MODE and AGENTIC_MODE:
                logger.info(f"AGENTIC MODE - {agentic_reason}. Giving LLM full tool autonomy.")
                await handle_agentic_command(message, text)
            elif intent_result.intent == "casual_chat" and intent_result.confidence > 0.7:
                # ONLY for clear conversational queries with HIGH confidence
                logger.info(f"Simple chat for clear casual_chat (confidence: {intent_result.confidence:.2f})")
                async with message.channel.typing():
                    response = await handle_chat_command(
                        bot_instance(), message, text,
                        intent_result=intent_result
                    )
                await reply_in_chunks(message, response)

            elif intent_result.intent == "memory_ops":
                # Memory commands - use specialized handler for consistency
                await _handle_natural_memory_command(message, intent_result, text)

            elif intent_result.intent == "conversations_manage":
                # Conversation management - specialized handler
                await _handle_natural_conversations_command(message, intent_result, text)

            elif intent_result.intent == "persona_switch":
                # Persona switch - specialized handler
                await _handle_natural_persona_command(message, intent_result, text)

            elif HAS_AGENTIC_MODE and AGENTIC_MODE:
                # DEFAULT: Agentic mode for everything else
                logger.info(f"AGENTIC MODE for '{intent_result.intent}' - defaulting to tool autonomy")
                await handle_agentic_command(message, text)

            else:
                # Fallback if agentic not available
                logger.warning(f"Agentic unavailable, using standard chat for '{intent_result.intent}'")
                async with message.channel.typing():
                    response = await handle_chat_command(
                        bot_instance(), message, text,
                        intent_result=intent_result,
                        enable_tools=True
                    )
                await reply_in_chunks(message, response)
                
        except Exception as e:
            logger.exception(f"Error in natural language handler: {e}")
            # Fall back to simple chat on error
            try:
                async with message.channel.typing():
                    response = await handle_chat_command(bot_instance(), message, text)
                await reply_in_chunks(message, response)
            except Exception as chat_error:
                logger.exception(f"Fallback chat also failed: {chat_error}")
                await message.reply("I'm having trouble understanding right now...")
        return
    
    elif HAS_CONVERSATION_FEATURES and MEMORY_ENABLED:
        # Fallback if NL router not available - use standard chat
        try:
            async with message.channel.typing():
                response = await handle_chat_command(bot_instance(), message, text)
            await reply_in_chunks(message, response)
        except Exception as e:
            logger.exception(f"Error handling natural chat: {e}")
            await message.reply("I'm having trouble thinking right now...")
        return

    # If memory is off and no known command matched
    await message.reply(f"Unknown command: `{cmd}`. Type `help` for a list of commands.")


# Natural Language Command Handlers
# These functions handle specific intents detected from natural language

async def _handle_natural_memory_command(message: discord.Message, intent_result, text: str):
    """Handle memory-related natural language commands."""
    entities = intent_result.entities
    
    # Determine subcommand based on message content
    text_lower = text.lower()
    
    # Detect RECALL questions: "do you remember X?", "can you remember X?", "what's my X?"
    # These should go to the LLM (which has memory context), NOT store a fact
    recall_patterns = [
        "do you remember", "can you remember", "do you recall",
        "what's my", "what is my", "what are my",
        "do you know my", "tell me my", "what do you remember",
    ]
    is_recall_question = any(p in text_lower for p in recall_patterns) or (
        "remember" in text_lower and text.rstrip().endswith("?")
    )
    
    if is_recall_question:
        # Route to LLM chat — it has memory facts in its system prompt
        logger.info(f"Memory recall question detected, routing to chat: {text[:80]}...")
        async with message.channel.typing():
            response = await handle_chat_command(
                bot_instance(), message, text,
                intent_result=intent_result
            )
        await reply_in_chunks(message, response)
        return
    
    if "remember" in text_lower and entities.get("fact_content"):
        # Handle remember command (imperative: "remember that X")
        response = await handle_remember_command(
            bot_instance(), message, entities["fact_content"]
        )
        await message.reply(response)
        
    elif "forget" in text_lower:
        # Handle forget command - extract what to forget
        # Use the entity or try to parse from message
        forget_what = entities.get("fact_content", "")
        if not forget_what:
            # Try to extract after "forget"
            match = re.search(r"forget\s+(?:that\s+)?(.+)", text_lower)
            if match:
                forget_what = match.group(1).strip()
        
        if forget_what:
            from .chat_commands import handle_forget_command
            response = await handle_forget_command(bot_instance(), message, forget_what)
            await message.reply(response)
        else:
            await message.reply("What would you like me to forget? Please specify.")
            
    elif "show" in text_lower or "what do you know" in text_lower or "memories" in text_lower:
        # Show memory status
        response = await handle_memory_command(
            bot_instance(), message, "status"
        )
        await message.reply(response)
        
    elif "clear" in text_lower:
        # Clear memory
        response = await handle_memory_command(
            bot_instance(), message, "clear"
        )
        await message.reply(response)
        
    else:
        # Default: route to LLM chat (safer than showing raw memory status)
        async with message.channel.typing():
            response = await handle_chat_command(
                bot_instance(), message, text,
                intent_result=intent_result
            )
        await reply_in_chunks(message, response)


async def _handle_natural_conversations_command(message: discord.Message, intent_result, text: str):
    """Handle conversation management natural language commands."""
    entities = intent_result.entities
    text_lower = text.lower()
    
    if "new" in text_lower or "start" in text_lower:
        # Create new conversation
        response = await handle_conversations_command(
            bot_instance(), message, "new", ""
        )
        await message.reply(response)
        
    elif "switch" in text_lower and entities.get("conversation_id_or_name"):
        # Switch to specific conversation
        response = await handle_conversations_command(
            bot_instance(), message, "switch", entities["conversation_id_or_name"]
        )
        await message.reply(response)
        
    elif "resume" in text_lower or "last" in text_lower:
        # Resume last conversation
        response = await handle_conversations_command(
            bot_instance(), message, "resume", ""
        )
        await message.reply(response)
        
    elif "rename" in text_lower and entities.get("conversation_id_or_name"):
        # Rename conversation
        response = await handle_conversations_command(
            bot_instance(), message, "rename", entities["conversation_id_or_name"]
        )
        await message.reply(response)
        
    else:
        # Default to listing conversations
        response = await handle_conversations_command(
            bot_instance(), message, "list", ""
        )
        await message.reply(response)


async def _handle_natural_persona_command(message: discord.Message, intent_result, text: str):
    """Handle persona switching natural language commands."""
    entities = intent_result.entities
    
    if entities.get("persona_name"):
        persona = entities["persona_name"]
        response = await handle_persona_command(
            bot_instance(), message, persona
        )
        await message.reply(response)
    else:
        # List available personas
        response = await handle_persona_command(
            bot_instance(), message, None
        )
        await message.reply(response)


async def _handle_natural_github_command(message: discord.Message, intent_result, text: str):
    """Handle GitHub-related natural language commands."""
    text_lower = text.lower()
    
    # For now, respond with helpful info about GitHub commands
    # In the future, this could route to actual GitHub tool handlers
    if "create" in text_lower and "issue" in text_lower:
        await message.reply(
            "I'll help you create a GitHub issue! However, I need a few details:\n"
            "- Which repository?\n"
            "- What's the issue title?\n"
            "- Description of the issue?\n\n"
            "Or use agentic mode: `agentic Create an issue in repo 'name' titled 'title'`"
        )
    elif "list" in text_lower and "repos" in text_lower:
        await message.reply(
            "I can list your GitHub repositories! Let me fetch that information for you..."
        )
        # Route through chat with tools enabled
        response = await handle_chat_command(
            bot_instance(), message, text,
            intent_result=intent_result,
            enable_tools=True
        )
        await reply_in_chunks(message, response)
    else:
        await message.reply(
            "I can help with GitHub operations! I can:\n"
            "- List your repositories\n"
            "- Show your issues\n"
            "- Create new issues\n\n"
            "What would you like to do?"
        )


async def _handle_natural_website_command(message: discord.Message, intent_result, text: str):
    """Handle website management natural language commands."""
    text_lower = text.lower()
    
    if "create" in text_lower and "post" in text_lower:
        await message.reply(
            "I'll help you create a blog post! Please provide:\n"
            "1. Title in quotes\n"
            "2. Content in quotes\n"
            "3. Optional category\n\n"
            "Example: `!website_post \"My Title\" \"Content here...\" philosophy`"
        )
    elif "status" in text_lower or "stats" in text_lower:
        response = await handle_website_command(
            bot_instance(), message, "status"
        )
        await message.reply(response)
    elif "regenerate" in text_lower or "rebuild" in text_lower or "refresh" in text_lower:
        response = await handle_website_command(
            bot_instance(), message, "regenerate"
        )
        await message.reply(response)
    elif "update" in text_lower or "manage" in text_lower:
        await message.reply(
            "I can help you manage your website! Available commands:\n"
            "`!website status` - Show website stats\n"
            "`!website regenerate` - Full regeneration\n"
            "`!website sync` - Sync from memory\n"
            "`!website_post \"Title\" \"Content\"` - Create blog post"
        )
    else:
        response = await handle_website_command(
            bot_instance(), message, ""
        )
        await message.reply(response)


async def _handle_natural_system_command(message: discord.Message, intent_result, text: str):
    """Handle system status and capabilities natural language commands."""
    text_lower = text.lower()
    
    if "what can you do" in text_lower or "capabilities" in text_lower or "help" in text_lower:
        # Show extended help with natural language examples
        await _show_extended_help(message)
    elif "ping" in text_lower or "status" in text_lower:
        await _run_job_and_reply(message, "ping", "")
    else:
        # Show capabilities info
        await _show_extended_help(message)


async def _show_extended_help(message: discord.Message):
    """Show help with natural language examples."""
    help_text = """I can help you with many things! Here's what I can do:

**Conversational:**
- Just chat with me naturally - I remember our conversations!
- All interactions maintain persistent personality and context

**Agentic Mode (Streaming):**
- `agentic <request>` - Multi-turn streaming with tool calling
- Real-time progress updates and intermediate results
- Automatic for complex tool requests when `AGENTIC_AUTO_TRIGGER=true`

**Repository Operations:**
- "Show me my repos" - List your repositories
- "Search for authentication in the discord_bot folder" - Search code
- "Read the main.py file from openclaw-broker" - View files
- "What repos do I have?" - Repository list

**GitHub:**
- "List my GitHub repos" - Show repositories
- "Create an issue for the memory bug" - Issue management

**Web Research:**
- "Search the web for Python best practices" - Web search
- "Look up information about machine learning" - Research

**Website Management:**
- "Update my website" - Website commands
- "Show website status" - Check status
- "Create a blog post" - Content creation

**Memory:**
- "Remember that my favorite color is blue" - Store facts
- "What do you know about me?" - Recall memories
- "Forget that I like pizza" - Remove memories

**Conversations:**
- "Show my conversations" - List saved chats
- "Start a new conversation" - Create new chat
- "Switch to conversation 2" - Change active chat

I also respond to all the traditional commands like `ping`, `repos`, `grep`, `cat`, etc.

What would you like to do?"""

    await message.reply(help_text)


async def handle_agentic_command(message: discord.Message, prompt: str):
    """
    Handle the agentic command - streaming multi-turn conversation with tool calling.
    """
    if not HAS_AGENTIC_MODE:
        await message.reply("Agentic mode is not available. Check your configuration.")
        return

    try:
        # Create agentic session
        manager = get_agentic_manager()

        conversation_id = None
        memory = None
        if MEMORY_ENABLED:
            from .memory import get_memory
            memory = get_memory()
            if memory:
                # Use the ACTIVE conversation so we maintain context across messages
                conversation_id = memory.get_active_conversation(str(message.author.id))

        # Only create a new ID if no active conversation exists
        if not conversation_id:
            conversation_id = f"{message.channel.id}_{message.author.id}_{int(time.time())}"
            if memory:
                memory.create_conversation(
                    conversation_id=conversation_id,
                    channel_id=str(message.channel.id),
                    user_id=str(message.author.id),
                    title=f"Conversation {int(time.time()) % 10000}",
                    is_group=False
                )
                memory.set_active_conversation(str(message.author.id), conversation_id, str(message.channel.id))

        # Build conversation history from memory
        conversation_history = []
        if memory:
            try:
                context = memory.get_conversation_context(
                    conversation_id=conversation_id,
                    user_id=str(message.author.id),
                    query=prompt,
                    max_tokens=2000
                )
                for msg in context.get('recent_messages', []):
                    conversation_history.append({
                        "role": msg.role,
                        "content": msg.content
                    })
            except Exception as e:
                logger.warning(f"Failed to get memory context: {e}")

        # Create session with config
        # Use polling instead of SSE for better reliability
        config = AgenticConfig(
            max_steps=AGENTIC_DEFAULT_MAX_STEPS,
            enable_thinking_display=True,
            enable_progress_updates=True,
            max_stream_wait=AGENTIC_MAX_STREAM_WAIT,
            use_sse=False,  # Use polling for better reliability
        )

        session = await manager.create_session(
            message=message,
            config=config,
            conversation_id=conversation_id,
            persona_key=DEFAULT_PERSONA,
        )

        # Set up callbacks for Discord interaction
        async def on_message(content: str):
            await reply_in_chunks(message, content)

        async def on_thinking(thought: str, step: int):
            logger.debug(f"Thinking step {step}: {thought[:100]}...")

        async def on_tool_call(tool_name: str, tool_args: dict):
            logger.info(f"Tool call: {tool_name} with args {tool_args}")
            
            # Handle BOT_ONLY self-memory tools
            if tool_name == "self_memory_add_fact":
                content = tool_args.get("content")
                category = tool_args.get("category", "other")
                if content:
                    engine = get_personality_engine()
                    engine.record_learned_fact(
                        content=content,
                        source_type="autonomous_reflection",
                        category=category
                    )
                    logger.info(f"LLM explicitly stored self-fact: {content[:50]}...")

            elif tool_name == "self_memory_add_reflection":
                content = tool_args.get("content")
                importance = tool_args.get("importance", 1.0)
                if content:
                    engine = get_personality_engine()
                    engine.record_reflection(
                        trigger="autonomous_reflection",
                        content=content,
                        importance=importance,
                        conversation_id=conversation_id
                    )
                    logger.info(f"LLM recorded self-reflection: {content[:50]}...")

        async def on_complete(final: str):
            logger.info(f"Agentic session complete, final length: {len(final)}")
            await reply_in_chunks(message, final)

        session.on_message(on_message)
        session.on_thinking(on_thinking)
        session.on_tool_call(on_tool_call)
        session.on_complete(on_complete)

        # Send initial acknowledgment - more natural than generic "agentic mode" text
        # The LLM will stream its actual response through the on_message callback
        intent_hint = ""
        if _has_url(prompt):
            intent_hint = "🔍 Looking up that information for you..."
        elif "search" in prompt.lower() or "find" in prompt.lower():
            intent_hint = "🔍 Searching for that..."
        elif "repo" in prompt.lower() or "file" in prompt.lower() or "code" in prompt.lower():
            intent_hint = "📁 Checking your repositories..."
        elif "github" in prompt.lower():
            intent_hint = "🐙 Checking GitHub..."
        else:
            intent_hint = "🤔 Working on that for you..."

        status_msg = await message.reply(intent_hint)

        # Show typing indicator while processing
        async with message.channel.typing():
            # Start the session - relies on streaming client's intelligent termination
            # Detects: idle timeout (no chunks), stuck loops, repeated failures
            # No hard time limit - runs as long as progress is being made
            try:
                final_result = await session.start(
                    prompt=prompt,
                    conversation_history=conversation_history,
                )
            except Exception as e:
                logger.exception(f"Agentic session failed: {e}")
                final_result = None
                await status_msg.edit(content=f"❌ Agentic session failed: {str(e)[:200]}")
                return

        if final_result:
            # Store in memory if enabled
            if memory:
                try:
                    memory.add_message(
                        conversation_id=conversation_id,
                        user_id=str(message.author.id),
                        role="user",
                        content=prompt,
                    )
                    memory.add_message(
                        conversation_id=conversation_id,
                        user_id=str(message.author.id),
                        role="assistant",
                        content=final_result,
                    )
                except Exception as e:
                    logger.warning(f"Failed to store in memory: {e}")
        else:
            await message.reply("❌ Agentic session failed to produce a result. Check logs for details.")

    except Exception as e:
        logger.exception(f"Error in agentic command: {e}")
        await message.reply(f"❌ Error in agentic mode: {str(e)[:200]}")


# Global bot instance reference for chat commands
_bot_instance = None

def bot_instance():
    """Get bot instance for chat commands."""
    return _bot_instance


def _init_conversation_features():
    """Initialize memory and personality systems if enabled."""
    if not HAS_CONVERSATION_FEATURES or not MEMORY_ENABLED:
        return

    try:
        # Ensure HuggingFace cache goes to a writable location.
        # Systemd services with ProtectSystem=strict only allow writes to
        # ReadWritePaths — the default ~/.cache may be on a read-only mount.
        if "HF_HOME" not in os.environ:
            hf_cache = os.path.join(os.getcwd(), ".cache", "huggingface")
            os.makedirs(hf_cache, exist_ok=True)
            os.environ["HF_HOME"] = hf_cache

        # Initialize memory with embedding provider
        embedding_provider = None

        if EMBEDDING_PROVIDER == "openai" and OPENAI_API_KEY:
            try:
                import openai
                client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
                
                async def openai_embed(text: str):
                    try:
                        response = await client.embeddings.create(
                            model=EMBEDDING_MODEL,
                            input=text[:8000]  # Token limit safety
                        )
                        import numpy as np
                        return np.array(response.data[0].embedding, dtype=np.float32)
                    except Exception as e:
                        logger.error(f"OpenAI embedding failed: {e}")
                        return None
                
                embedding_provider = openai_embed
                logger.info(f"OpenAI embeddings enabled ({EMBEDDING_MODEL})")
            except ImportError:
                logger.warning("openai package not installed, embeddings disabled")
        
        elif EMBEDDING_PROVIDER == "local":
            # Use sentence-transformers (or similar) with the specified model
            try:
                from sentence_transformers import SentenceTransformer
                # trust_remote_code=True is required for Qwen and some other modern models
                model = SentenceTransformer(EMBEDDING_MODEL, trust_remote_code=True)

                import numpy as np
                def local_embed(text: str):
                    try:
                        embedding = model.encode(text[:8000], convert_to_numpy=True)
                        return np.array(embedding, dtype=np.float32)
                    except Exception as e:
                        logger.error(f"Local embedding failed: {e}")
                        return None

                embedding_provider = local_embed
                logger.info(f"Local embeddings enabled ({EMBEDDING_MODEL})")
            except ImportError:
                logger.warning("sentence-transformers not installed, local embeddings disabled")
                logger.warning("Install with: pip install sentence-transformers")

        elif EMBEDDING_PROVIDER == "remote":
            # Offload embeddings to WSL runner via broker jobs (saves VPS CPU)
            try:
                from discord_bot.embeddings import RemoteEmbeddingProvider

                remote_provider = RemoteEmbeddingProvider(
                    broker_url=BROKER_URL,
                    bot_token=BOT_TOKEN,
                    model=EMBEDDING_MODEL,
                    timeout=30.0,
                )

                def remote_embed(text: str):
                    try:
                        # Use sync version since we're in a sync context
                        result = remote_provider.embed_sync(text)
                        if result is None:
                            return None
                        import numpy as np
                        return np.array(result, dtype=np.float32)
                    except Exception as e:
                        logger.error(f"Remote embedding failed: {e}")
                        return None

                embedding_provider = remote_embed
                logger.info(f"Remote embeddings enabled ({EMBEDDING_MODEL} via WSL runner)")
            except ImportError as e:
                logger.warning(f"Remote embeddings not available: {e}")
                logger.warning("Ensure discord_bot.embeddings module is available")

        # Health check: Test embedding provider if configured (run in background)
        if embedding_provider:
            def run_health_check():
                try:
                    import numpy as np
                    test_text = "Health check test embedding"
                    test_result = embedding_provider(test_text)
                    
                    if test_result is not None:
                        if isinstance(test_result, np.ndarray):
                            dim = len(test_result)
                        elif isinstance(test_result, list):
                            dim = len(test_result)
                        else:
                            dim = "unknown"
                        logger.info(f"Embedding health check PASSED - dimension: {dim}")
                    else:
                        logger.error("Embedding health check FAILED - provider returned None")
                except Exception as e:
                    logger.error(f"Embedding health check FAILED: {e}")
            
            # Run health check in background thread to not block startup
            import threading
            threading.Thread(target=run_health_check, daemon=True).start()
        
        # Initialize memory and personality (used by chat_commands when handling chat)
        # Convert to absolute path to ensure consistent database location in WSL
        memory_db_absolute = os.path.abspath(MEMORY_DB_PATH)
        self_memory_db_absolute = os.path.abspath(SELF_MEMORY_DB_PATH)
        logger.info(f"Using memory database at: {memory_db_absolute}")
        logger.info(f"Using self-memory database at: {self_memory_db_absolute}")
        get_memory(memory_db_absolute, embedding_provider)
        get_self_memory(self_memory_db_absolute, embedding_provider)
        engine = get_personality_engine(DEFAULT_PERSONA)

        # Load custom personas from user config (lives alongside bot.env, survives updates)
        loaded = engine.load_custom_personas(CUSTOM_PERSONAS_PATH)
        if loaded:
            logger.info(f"Loaded {loaded} custom persona(s) from {CUSTOM_PERSONAS_PATH}")

        logger.info(f"Conversation features enabled (memory: {MEMORY_DB_PATH}, persona: {DEFAULT_PERSONA})")
        
    except Exception as e:
        logger.exception(f"Failed to initialize conversation features: {e}")


def main():
    global _bot_instance
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    if not DISCORD_TOKEN or not BOT_TOKEN:
        logger.error("DISCORD_TOKEN and BOT_TOKEN must be set")
        sys.exit(1)
    if not ALLOWLIST_IDS:
        logger.error("At least one of ALLOWED_USER_ID or ALLOWLIST_USER_ID must be set")
        sys.exit(1)

    logger.info(f"Allowlist: {len(ALLOWLIST_IDS)} user ID(s) configured")
    if os.environ.get("ALLOWLIST_DEBUG", "").strip().lower() in ("1", "true", "yes"):
        for aid in sorted(ALLOWLIST_IDS):
            logger.debug(f"ALLOWLIST_IDS entry: {repr(aid)} (len={len(aid)})")
    
    # Initialize conversation features
    _init_conversation_features()
    
    # Store bot instance reference
    _bot_instance = client
    
    # log_handler=None prevents discord.py from adding a second StreamHandler
    # to the root logger (our basicConfig already configures one).
    client.run(DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
