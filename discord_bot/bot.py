"""
OpenClaw Discord Bot — creates jobs from DMs and replies with results.
Only responds to DMs (or optional single channel). Allowlists one Discord user ID.
Commands: ping, capabilities, plan, approve, status. Guardrails: cooldown, max concurrent.
"""

import json
import os
import sys
import time
from typing import Optional

import discord
import requests

# --- Config from env ---
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
BROKER_URL = os.environ.get("BROKER_URL", "http://127.0.0.1:8000").rstrip("/")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")  # X-Bot-Token for broker API
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID", "")  # single user ID allowed to use bot
ALLOWED_CHANNEL_ID = os.environ.get("ALLOWED_CHANNEL_ID", "")  # optional: single channel (empty = DMs only)
JOB_POLL_INTERVAL_SEC = float(os.environ.get("JOB_POLL_INTERVAL_SEC", "2"))
JOB_POLL_TIMEOUT_SEC = float(os.environ.get("JOB_POLL_TIMEOUT_SEC", "120"))
BOT_COOLDOWN_SECONDS = float(os.environ.get("BOT_COOLDOWN_SECONDS", "3"))
BOT_MAX_CONCURRENT = int(os.environ.get("BOT_MAX_CONCURRENT", "1"))

MAX_DISPLAY_LEN = 1500


def is_allowed(channel: discord.abc.Messageable, author_id: str) -> bool:
    if not ALLOWED_USER_ID or str(author_id) != str(ALLOWED_USER_ID):
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


def create_job(command: str, payload: str) -> dict:
    r = requests.post(
        f"{BROKER_URL}/jobs",
        headers={"X-Bot-Token": BOT_TOKEN},
        json={"command": command, "payload": payload},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_job(job_id: str) -> dict:
    r = requests.get(
        f"{BROKER_URL}/jobs/{job_id}",
        headers={"X-Bot-Token": BOT_TOKEN},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def wait_for_job_result(job_id: str) -> tuple[str, bool]:
    """
    Poll until job is done or failed or timeout.
    Returns (message, timed_out). If timed_out, message is the "still running" text.
    """
    deadline = time.monotonic() + JOB_POLL_TIMEOUT_SEC
    while time.monotonic() < deadline:
        job = get_job(job_id)
        status = job.get("status", "")
        if status == "done":
            return (job.get("result") or "(no result)", False)
        if status == "failed":
            err = job.get("error") or job.get("result") or "unknown"
            return (f"Job failed: {err}", False)
        time.sleep(JOB_POLL_INTERVAL_SEC)
    return (f"Still running. Job ID: {job_id} (try: status {job_id})", True)


def truncate_for_display(text: str, job_id: str) -> str:
    """If text is long, truncate and tell user to use status <id>."""
    if len(text) <= MAX_DISPLAY_LEN:
        return text
    return text[:MAX_DISPLAY_LEN] + "… (use `status " + job_id + "` for full output)."


intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"[bot] logged in as {client.user}")


async def _run_job_and_reply(
    message: discord.Message,
    command: str,
    payload: str,
    reply_prefix: str = "Job created: ",
    parse_json: bool = False,
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
        job = create_job(command=command, payload=payload)
        job_id = job.get("id")
        if not job_id:
            await message.reply("Failed to create job (no id).")
            return
        state["active_jobs"].add(job_id)
        state["last_ts"] = now_ts

        await message.reply(f"{reply_prefix}`{job_id}`. Waiting for result…")
        result, timed_out = wait_for_job_result(job_id)
        display = truncate_for_display(result, job_id)
        if parse_json:
            try:
                data = json.loads(result)
                if command == "capabilities":
                    worker_id = data.get("worker_id", "?")
                    caps = data.get("capabilities", [])
                    display = f"Worker: `{worker_id}`\nCapabilities: {', '.join(caps)}"
                elif command == "plan_echo":
                    plan_id = data.get("plan_id", "?")
                    summary = data.get("summary", "")
                    display = f"Plan ID: `{plan_id}`\nSummary: {summary}\nTo apply: `approve {plan_id}`"
                elif command == "approve_echo":
                    status = data.get("status", "?")
                    note = data.get("note", "")
                    display = f"Status: {status}\n{note}" if note else f"Status: {status}"
            except (json.JSONDecodeError, KeyError):
                pass
        await message.reply(display)
    except requests.RequestException as e:
        await message.reply(f"Broker error: {e}")
    except Exception as e:
        await message.reply(f"Error: {e}")
    finally:
        if job_id:
            state["active_jobs"].discard(job_id)


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
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
            await message.reply(f"Broker error: {e}")
            return
        status = job.get("status", "?")
        lines = [f"Job `{job_id}`: **{status}**"]
        if status == "done":
            result = job.get("result") or "(no result)"
            lines.append(truncate_for_display(result, job_id))
        elif status == "failed":
            err = job.get("error") or job.get("result") or "unknown"
            lines.append(truncate_for_display(f"Error: {err}", job_id))
        await message.reply("\n".join(lines))
        return

    await message.reply(
        "Unknown command. Use: `ping <text>`, `capabilities`, `plan <text>`, `approve <plan_id>`, `status <job_id>`"
    )


def main():
    if not DISCORD_TOKEN or not BOT_TOKEN or not ALLOWED_USER_ID:
        print("[bot] ERROR: DISCORD_TOKEN, BOT_TOKEN, and ALLOWED_USER_ID must be set", file=sys.stderr)
        sys.exit(1)
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
