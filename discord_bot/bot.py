"""
OpenClaw Discord Bot — creates jobs from DMs and replies with results.
Only responds to DMs (or optional single channel). Allowlist: one or more Discord user IDs.
Commands: ping, capabilities, plan, approve, status, repos, repostat, last, grep, cat, whoami.
Guardrails: cooldown, max concurrent.
"""

import json
import os
import re
import sys
import time
from typing import Optional

import discord
import requests

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

MAX_DISPLAY_LEN = 1500

# Broker HTTP timeouts: (connect, read) in seconds — avoid hanging if broker is down
BROKER_CONNECT_TIMEOUT = 5
BROKER_READ_TIMEOUT = 15

# Allowlist: union of ALLOWED_USER_ID (single) and ALLOWLIST_USER_ID (comma/space separated)
def _parse_allowlist_ids() -> set[str]:
    ids: set[str] = set()
    if ALLOWED_USER_ID:
        ids.add(ALLOWED_USER_ID)
    for part in re.split(r"[\s,]+", ALLOWLIST_USER_ID):
        if part:
            ids.add(part)
    return ids


ALLOWLIST_IDS = _parse_allowlist_ids()


def redact(text: str) -> str:
    """Replace any occurrence of configured tokens with *** so they are never logged."""
    out = text
    if BOT_TOKEN:
        out = out.replace(BOT_TOKEN, "***")
    if DISCORD_TOKEN:
        out = out.replace(DISCORD_TOKEN, "***")
    return out


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
    print(f"[bot] logged in as {client.user} (id={bot_id})")
    print(f"[bot] INSTANCE_NAME={INSTANCE_NAME} BROKER_URL={BROKER_URL}")


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
        await message.reply(
            format_whoami(INSTANCE_NAME, bot_id, BROKER_URL, _allowlist_display())
        )
        return

    await message.reply(
        "Unknown command. Use: `ping <text>`, `capabilities`, `plan <text>`, `approve <plan_id>`, "
        "`status <job_id>`, `repos`, `repostat <repo>`, `last <repo>`, `grep <repo> <query> [path]`, "
        "`cat <repo> <path> [start] [end]`, `ask <prompt>`, `urgo <prompt>`, `whoami`"
    )


def main():
    if not DISCORD_TOKEN or not BOT_TOKEN:
        print("[bot] ERROR: DISCORD_TOKEN and BOT_TOKEN must be set", file=sys.stderr)
        sys.exit(1)
    if not ALLOWLIST_IDS:
        print("[bot] ERROR: At least one of ALLOWED_USER_ID or ALLOWLIST_USER_ID must be set", file=sys.stderr)
        sys.exit(1)
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
