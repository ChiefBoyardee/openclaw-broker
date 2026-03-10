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
    )
    from .memory import get_memory
    from .personality import get_personality_engine
    HAS_CONVERSATION_FEATURES = True
except ImportError:
    HAS_CONVERSATION_FEATURES = False

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

# --- Conversation/Memory Feature Config ---
MEMORY_ENABLED = os.environ.get("MEMORY_ENABLED", "true").lower() in ("true", "1", "yes")
MEMORY_DB_PATH = os.environ.get("MEMORY_DB_PATH", "discord_bot_memory.db")
DEFAULT_PERSONA = os.environ.get("DEFAULT_PERSONA", "helpful_assistant")
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "none").lower()  # 'openai', 'local', 'none'
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
CONVERSATION_TIMEOUT_MINUTES = float(os.environ.get("CONVERSATION_TIMEOUT_MINUTES", "30"))

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


@client.event
async def on_ready():
    bot_id = str(client.user.id) if client.user else "?"
    logger.info(f"logged in as {client.user} (id={bot_id})")
    logger.info(f"INSTANCE_NAME={INSTANCE_NAME} BROKER_URL={BROKER_URL}")
    
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

    if cmd in ("ask", "urgo"):
        if not payload:
            await message.reply("Usage: `ask <prompt>` or `urgo <prompt>`")
            return
        prompt_text = payload.strip()
        # Forced routing: vllm: / vllm / jetson: / jetson (strip prefix so LLM does not see it)
        prompt_for_llm = prompt_text
        requires = None
        pl = prompt_text.lower()
        if pl.startswith("vllm:") or pl.startswith("vllm ") or " preferred vllm" in pl:
            if pl.startswith("vllm:"):
                prompt_for_llm = prompt_text[5:].lstrip()
            elif pl.startswith("vllm "):
                prompt_for_llm = prompt_text[5:].lstrip()
            else:
                prompt_for_llm = _strip_phrase_any_case(prompt_text, " preferred vllm")
            if not prompt_for_llm.strip():
                await message.reply("Please provide a prompt (e.g. `ask vllm: your question here`).")
                return
            payload_obj = {"prompt": prompt_for_llm, "preferred": "llm:vllm"}
            requires = '{"caps":["llm:vllm"]}'
        elif pl.startswith("jetson:") or pl.startswith("jetson ") or " preferred jetson" in pl:
            if pl.startswith("jetson:"):
                prompt_for_llm = prompt_text[7:].lstrip()
            elif pl.startswith("jetson "):
                prompt_for_llm = prompt_text[7:].lstrip()
            else:
                prompt_for_llm = _strip_phrase_any_case(prompt_text, " preferred jetson")
            if not prompt_for_llm.strip():
                await message.reply("Please provide a prompt (e.g. `ask jetson: your question here`).")
                return
            payload_obj = {"prompt": prompt_for_llm, "preferred": "llm:jetson"}
            requires = '{"caps":["llm:jetson"]}'
        else:
            payload_obj = {"prompt": prompt_for_llm}
        await _run_job_and_reply(
            message,
            "llm_task",
            json.dumps(payload_obj),
            reply_prefix="LLM job: ",
            parse_json=True,
            requires=requires,
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

    # --- Conversational/Chat Commands ---
    if HAS_CONVERSATION_FEATURES and MEMORY_ENABLED:
        if cmd == "chat":
            if not payload:
                await message.reply("Start a conversation! Usage: `chat <your message>`")
                return
            response = await handle_chat_command(bot_instance(), message, payload)
            await reply_in_chunks(message, response)
            return

        if cmd == "persona":
            response = await handle_persona_command(bot_instance(), message, payload)
            await reply_in_chunks(message, response)
            return

        if cmd == "memory":
            response = await handle_memory_command(bot_instance(), message, payload)
            await reply_in_chunks(message, response)
            return

        if cmd == "remember":
            if not payload:
                await message.reply("What should I remember? Usage: `remember <fact>`")
                return
            response = await handle_remember_command(bot_instance(), message, payload)
            await reply_in_chunks(message, response)
            return

        if cmd == "history":
            response = await handle_history_command(bot_instance(), message, payload)
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
            "**LLM Commands:**",
            "`ask <prompt>` - Ask LLM (one-shot)",
            "`urgo <prompt>` - Urgent LLM request",
        ]

        if HAS_CONVERSATION_FEATURES and MEMORY_ENABLED:
            help_lines.extend([
                "",
                "**Conversation Commands:**",
                "`persona [name]` - Switch personality",
                "`memory [status/clear/on/off]` - Memory management",
                "`remember <fact>` - Remember a fact",
                "`history [n]` - Show conversation history",
                "",
                "*(You don't need to use a command to talk to me—just say anything!)*",
            ])

        help_lines.extend([
            "",
            "**Info:**",
            "`whoami` - Show bot info",
        ])

        await message.reply("\n".join(help_lines))
        return

    # Fallback: treat unrecognized text as a natural conversational message
    if HAS_CONVERSATION_FEATURES and MEMORY_ENABLED:
        try:
            # Pass the entire original text as the message content
            response = await handle_chat_command(bot_instance(), message, text)
            await reply_in_chunks(message, response)
        except Exception as e:
            logger.exception(f"Error handling natural chat: {e}")
            await message.reply("I'm having trouble thinking right now...")
        return

    # If memory is off and no known command matched
    await message.reply(f"Unknown command: `{cmd}`. Type `help` for a list of commands.")


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
            # Try to use sentence-transformers or similar
            try:
                from sentence_transformers import SentenceTransformer
                model = SentenceTransformer('all-MiniLM-L6-v2')
                
                import numpy as np
                def local_embed(text: str):
                    try:
                        embedding = model.encode(text[:8000], convert_to_numpy=True)
                        return np.array(embedding, dtype=np.float32)
                    except Exception as e:
                        logger.error(f"Local embedding failed: {e}")
                        return None
                
                embedding_provider = local_embed
                logger.info("Local embeddings enabled (sentence-transformers)")
            except ImportError:
                logger.warning("sentence-transformers not installed, local embeddings disabled")
                logger.warning("Install with: pip install sentence-transformers")
        
        # Initialize memory and personality (used by chat_commands when handling chat)
        get_memory(MEMORY_DB_PATH, embedding_provider)
        get_personality_engine(DEFAULT_PERSONA)

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
    
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
