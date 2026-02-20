# Discord bot deployment (multi-instance)

The Discord bot can run as **multiple instances** on the same VPS, each with its own token, env file, venv, and state. This uses a systemd **template** unit and an install script.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | Yes | Bot token from Discord Developer Portal (each instance needs its own Discord Application). |
| `BOT_TOKEN` | Yes | Same value as broker `X-Bot-Token` (or per-instance token if broker allows). |
| `BROKER_URL` | Yes | Broker base URL (e.g. `http://127.0.0.1:8000` or Tailscale URL). |
| `ALLOWED_USER_ID` | One of allowlist | Single Discord user ID allowed to use the bot (right-click user → Copy ID). |
| `ALLOWLIST_USER_ID` | One of allowlist | Additional user IDs, comma- or space-separated (complements `ALLOWED_USER_ID`). At least one of `ALLOWED_USER_ID` or `ALLOWLIST_USER_ID` must be set. |
| `ALLOWED_CHANNEL_ID` | No | Single channel ID to allow; leave empty for DMs only. |
| `INSTANCE_NAME` | No | Set automatically by systemd to `%i` for template units; override in `bot.env` if needed. |
| `JOB_POLL_INTERVAL_SEC` | No | Seconds between job status polls (default `2`). |
| `JOB_POLL_TIMEOUT_SEC` | No | Max seconds to wait for job result before replying "Still running…" (default `120`). |
| `BOT_COOLDOWN_SECONDS` | No | **Per-user** minimum seconds between commands (default `3`). |
| `BOT_MAX_CONCURRENT` | No | **Per-user** max jobs in progress, queued or running (default `1`). |

Broker HTTP calls use fixed connect/read timeouts so the bot does not hang if the broker is down. Job polling uses gentle backoff (0.5s → 1s → 2s) between status checks to avoid spamming the broker.

## Overview

- **Template unit:** `openclaw-discord-bot@.service` — the `%i` is the instance name (e.g. `clawhub` → `openclaw-discord-bot@clawhub`).
- **Per-instance paths:**
  - `/opt/openclaw-bot-<instance>/` — working dir, `discord_bot/` code, `venv/`, `bot.env` (you create from `bot.env.example`).
  - `/var/lib/openclaw-bot-<instance>/` — optional state dir (writable by the service).
- **Env file:** `/opt/openclaw-bot-<instance>/bot.env`. Do not commit; create from `bot.env.example` and set secrets.
- **User:** Services run as `openclaw` (created by the install script if missing).

## Streamlined onboarding (recommended)

To add a new bot by pasting tokens and config (no manual env file editing):

```bash
./deploy/onboard_bot.sh <instance_name>
```

You’ll be prompted for: **DISCORD_TOKEN**, **BOT_TOKEN**, **BROKER_URL**, **ALLOWED_USER_ID** (or ALLOWLIST_USER_ID), and optional ALLOWED_CHANNEL_ID. The script runs the install, writes `bot.env`, and optionally enables/starts the unit. Add `--enable` to start without prompting:

```bash
./deploy/onboard_bot.sh urgoclaw --enable
```

Non-interactive: set env vars and run (use `ONBOARD_START=1` or `--enable` to start without prompt):

```bash
INSTANCE_NAME=urgoclaw DISCORD_TOKEN=... BOT_TOKEN=... BROKER_URL=... ALLOWED_USER_ID=... ./deploy/onboard_bot.sh --enable
```

Env examples for broker, runner, and bot in one place: [deploy/env.examples/](../deploy/env.examples/) (see README there for VPS + WSL layout).

## Install one instance (manual)

From the repo root:

```bash
./deploy/install_bot_instance.sh <instance_name> [--enable]
```

Example:

```bash
./deploy/install_bot_instance.sh clawhub --enable
```

This will:

1. Create `openclaw` user/group if missing.
2. Create `/opt/openclaw-bot-clawhub/` and `/var/lib/openclaw-bot-clawhub/`.
3. Copy `discord_bot/` and create a venv with dependencies.
4. Copy `bot.env.example` to `/opt/openclaw-bot-clawhub/bot.env.example` (no `bot.env` — you create it).
5. Install the systemd template to `/etc/systemd/system/openclaw-discord-bot@.service` and run `daemon-reload`.
6. If `--enable`: `systemctl enable --now openclaw-discord-bot@clawhub`.

## After install: create bot.env

No secrets are created by the script. Do:

```bash
sudo cp /opt/openclaw-bot-<instance>/bot.env.example /opt/openclaw-bot-<instance>/bot.env
sudo $EDITOR /opt/openclaw-bot-<instance>/bot.env
```

Set at least:

- **DISCORD_TOKEN** — from Discord Developer Portal (each instance needs its own Discord Application and bot token).
- **BOT_TOKEN** — same as broker `X-Bot-Token` if sharing one broker; or a distinct token per instance.
- **ALLOWED_USER_ID** — Discord user ID allowed to use this bot.
- **BROKER_URL** — broker base URL (e.g. `http://127.0.0.1:8000` or Tailscale URL).

Then:

```bash
sudo chown openclaw:openclaw /opt/openclaw-bot-<instance>/bot.env
```

**INSTANCE_NAME** is set automatically by systemd to the instance name when using the template; you can override in `bot.env` if needed.

## Manage services

- Start: `sudo systemctl start openclaw-discord-bot@<instance>`
- Stop: `sudo systemctl stop openclaw-discord-bot@<instance>`
- Enable on boot: `sudo systemctl enable openclaw-discord-bot@<instance>`
- Logs: `journalctl -u openclaw-discord-bot@<instance> -f`

Example for instance `clawhub`:

```bash
journalctl -u openclaw-discord-bot@clawhub -f
```

Startup logs include the bot’s Discord username, instance name, and broker URL so you can confirm which instance is running. Tokens are never logged.

## Run locally

From the repo root:

```bash
cp discord_bot/bot.env.example discord_bot/bot.env
# Edit discord_bot/bot.env: set DISCORD_TOKEN, BOT_TOKEN, BROKER_URL, and at least one of ALLOWED_USER_ID or ALLOWLIST_USER_ID
# Optional: ALLOWED_CHANNEL_ID, JOB_POLL_*, BOT_COOLDOWN_SECONDS, BOT_MAX_CONCURRENT
export $(grep -v '^#' discord_bot/bot.env | xargs)   # Linux/macOS; on Windows set vars manually or use a .env loader
python discord_bot/bot.py
```

Ensure the broker (and optionally the runner) are running so job commands succeed.

## Example DM commands

Send these in a DM with the bot (as an allowlisted user):

| Command | Description |
|---------|-------------|
| `whoami` | Instance name, bot user ID, broker URL, allowlist status. |
| `ping hello` | Creates a job and replies with result (e.g. `pong: hello`). |
| `capabilities` | Worker ID and capabilities list from the runner. |
| `status <job_id>` | Job status and result (truncated if long; use for long output). |
| `repos` | List of repos configured on the runner. |
| `repostat <repo>` | Repo branch and dirty status. |
| `last <repo>` | Last commit for the repo. |
| `grep <repo> <query> [path]` | Search in repo (optional path prefix). |
| `cat <repo> <path> [start] [end]` | Read file lines (default 1–200). |
| `plan <text>` | Create plan; reply includes `plan_id` for use with `approve`. |
| `approve <plan_id>` | Approve a plan by ID. |

Unauthorized users (not in the allowlist) who DM the bot receive a single polite refusal message. Cooldown and max concurrent jobs apply **per user**.

## whoami command

From an allowlisted DM, send `whoami`. The bot replies with:

- Instance name  
- Bot user ID  
- Broker URL  
- Allowlisted user ID (or “not set”)

No broker call; useful to confirm which instance and config you’re talking to.

## Hardening (systemd unit)

The template unit uses:

- **NoNewPrivileges=true**, **PrivateTmp=true**
- **ProtectSystem=strict**, **ProtectHome=true**
- **ReadWritePaths=/opt/openclaw-bot-%i /var/lib/openclaw-bot-%i**

All code and working dir live under `/opt`, so the service cannot write outside those paths.

## Multiple instances

Install and run as many instances as you need, each with a different `<instance_name>` and its own `bot.env` (and thus its own Discord app/token and allowlist):

```bash
./deploy/install_bot_instance.sh clawhub --enable
./deploy/install_bot_instance.sh staging --enable
```

Create `/opt/openclaw-bot-staging/bot.env` separately with staging’s `DISCORD_TOKEN`, `ALLOWED_USER_ID`, etc., then start: `sudo systemctl start openclaw-discord-bot@staging`.
