# OpenClaw Broker — Complete Installation Guide

This guide walks you through setting up OpenClaw from scratch. Whether you want a quick local test or a full production deployment with Discord, this document covers everything.

---

## Table of Contents

1. [What You're Building](#what-youre-building)
2. [Prerequisites](#prerequisites)
3. [Start Here](#start-here)
4. [Phase 1: Local Setup (Test Everything Works)](#phase-1-local-setup-test-everything-works)
5. [Phase 2: Create Your Discord Bot](#phase-2-create-your-discord-bot)
6. [Phase 3: Recommended Production Deployment (VPS + Broker + Bot)](#phase-3-recommended-production-deployment-vps--broker--bot)
7. [Phase 4: Add the Runner (Worker)](#phase-4-add-the-runner-worker)
8. [Phase 5: Optional — Repos, LLM, Multi-Worker](#phase-5-optional--repos-llm-multi-worker)
9. [Updating After Code Changes](#updating-after-code-changes)
10. [Removing and Reinstalling the Discord Bot (Fresh Install)](#removing-and-reinstalling-the-discord-bot-fresh-install)
11. [Overwrite and single-service behavior](#overwrite-and-single-service-behavior)
12. [Troubleshooting](#troubleshooting)

---

## What You're Building

OpenClaw has three main pieces:

| Piece | What it does |
|-------|---------------|
| **Broker** | A job queue server. The bot creates jobs; runners claim and complete them. |
| **Runner** | A worker that executes jobs (ping, file search, LLM tasks). Can run on your laptop (WSL), Jetson, or another machine. |
| **Discord Bot** | Lets you send commands via Discord DMs (e.g. `ping hello`, natural language chat) and receive results. |

**Flow:** You DM the bot → Bot creates a job on the broker → Runner picks up the job → Runner posts the result → Bot replies to you.

---

## Prerequisites

### Required

- **Python 3.9+** — Check with `python3 --version`
- **Git** — To clone the repo
- **A Discord account** — For creating the bot and testing commands

### For Production (VPS Deployment)

- **A Linux VPS** — e.g. DigitalOcean, Linode, or any Ubuntu/Debian server
- **Optional but recommended:** [Tailscale](https://tailscale.com) — For secure, private networking between your VPS and runner (no port opening on the public internet)

### For Optional LLM Features

- **An OpenAI-compatible API** — e.g. [vLLM](https://docs.vllm.ai/) on WSL, or a local model on Jetson

---

## Start Here

### Recommended production topology

Use this deployment shape unless you specifically want something else:

- **VPS:** broker + Discord bot instance(s)
- **WSL / Jetson / worker box:** runner
- **Optional LLM:** on the runner host, or reachable from that runner via an OpenAI-compatible API

This guide uses that topology throughout Phase 3 and Phase 4.

### Alternate topology

If you intentionally want **WSL to run broker + LLM + runner** and **the VPS to run only the Discord bot**, use [docs/COMMANDS_WSL_AND_VPS.md](COMMANDS_WSL_AND_VPS.md). Treat that as an alternate runbook, not the default beginner path.

### Token and env handoff

| Value | Generated where | Used by |
|-------|------------------|---------|
| `WORKER_TOKEN` | Broker setup | Broker + every runner that should claim jobs from that broker |
| `BOT_TOKEN` | Broker setup | Broker + every Discord bot instance that should submit jobs to that broker |
| `DISCORD_TOKEN` | Discord Developer Portal | One bot instance only |
| `BROKER_URL` | Derived from broker host/port | Runner + Discord bot |
| `ALLOWED_USER_ID` | Your Discord account | Discord bot allowlist |

**Important:** bot instances talking to the same broker share the broker's `BOT_TOKEN`. They do **not** share `DISCORD_TOKEN`; each Discord Application has its own `DISCORD_TOKEN`.

---

## Phase 1: Local Setup (Test Everything Works)

Start here to verify all components work before deploying to production.

### Step 1.1 — Clone and prepare the project

```bash
git clone https://github.com/ChiefBoyardee/openclaw-broker.git
cd openclaw-broker

# Create virtual environment and install dependencies
python3 -m venv .venv

# Activate (choose one for your OS):
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Windows CMD:
.venv\Scripts\activate.bat

pip install -r requirements.txt
```

### Step 1.2 — Generate tokens

You need two secret tokens (shared between components):

```bash
# Run twice and save each output
openssl rand -hex 32   # → use as WORKER_TOKEN
openssl rand -hex 32   # → use as BOT_TOKEN
```

**Keep these safe** — you’ll paste them into config files.

### Step 1.3 — Start the broker (Terminal 1)

```bash
# From repo root with venv activated
cp broker/broker.env.example broker/broker.env

# Edit broker/broker.env: set WORKER_TOKEN and BOT_TOKEN
# Or export them:
export BROKER_DB=./broker.db
export WORKER_TOKEN=your_worker_token_here
export BOT_TOKEN=your_bot_token_here

uvicorn broker.app:app --reload --host 127.0.0.1 --port 8000
```

Leave this running. You should see `Uvicorn running on http://127.0.0.1:8000`.

### Step 1.4 — Start the runner (Terminal 2)

```bash
# New terminal, same repo, venv activated
cp runner/runner.env.example runner/runner.env

# Edit runner/runner.env:
#   BROKER_URL=http://127.0.0.1:8000
#   WORKER_TOKEN=<same as broker>

# Load env and run
export $(grep -v '^#' runner/runner.env | xargs)   # Linux/macOS
# Windows: set variables manually or use a .env loader

python runner/runner.py
```

You should see the runner polling for jobs.

### Step 1.5 — Verify with curl (optional)

Open a third terminal:

```bash
# Health check (no auth)
curl -s http://127.0.0.1:8000/health
# Expected: {"ok":true,"ts_bound":true}

# Create a job (replace YOUR_BOT_TOKEN)
curl -s -X POST http://127.0.0.1:8000/jobs \
  -H "X-Bot-Token: YOUR_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command":"ping","payload":"hello"}'
# Expected: {"id":"...","status":"queued"}
```

The runner should claim the job and the broker will report it as done. You can also run the built-in smoke test:

```bash
python scripts/smoke.py
# Expected: Smoke OK
```

**If Phase 1 works**, broker and runner are functioning. Next, add the Discord bot.

---

## Phase 2: Create Your Discord Bot

You need a Discord Application and bot token. This is a one-time setup.

### Step 2.1 — Create a Discord Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** → give it a name (e.g. "OpenClaw Bot") → Create
3. Open **Bot** in the left sidebar
4. Click **Add Bot**
5. Under **Token**, click **Reset Token** (or **Copy**) and save it — this is your `DISCORD_TOKEN`
6. **Important:** Disable **Public Bot** if you want invite-only access. Enable **Message Content Intent** (required for the bot to read your DMs)

### Step 2.2 — Get your Discord User ID

The bot only responds to users you explicitly allow (allowlist). You need your own user ID:

1. In Discord: **User Settings → Advanced** → enable **Developer Mode**
2. Right‑click your username (in a server or DM list) → **Copy User ID**
3. Save this — it’s your `ALLOWED_USER_ID`

### Step 2.3 — Invite the bot to DM you

1. In the Developer Portal, open **OAuth2 → URL Generator**
2. Scopes: check **bot**
3. Bot Permissions: check **Send Messages**, **Read Message History**, **Read Messages/View Channels**
4. Copy the generated URL and open it in a browser
5. Choose a server or skip — you can use DMs without adding the bot to a server

### Step 2.4 — Start the Discord bot locally (Terminal 3)

With broker and runner still running:

```bash
cp discord_bot/bot.env.example discord_bot/bot.env

# Edit discord_bot/bot.env and set:
#   DISCORD_TOKEN=<from Developer Portal>
#   BOT_TOKEN=<same as broker>
#   BROKER_URL=http://127.0.0.1:8000
#   ALLOWED_USER_ID=<your Discord user ID>

# Load env and run
export $(grep -v '^#' discord_bot/bot.env | xargs)   # Linux/macOS
python discord_bot/bot.py
```

**On Windows:** Set the variables in PowerShell or use a .env loader, then run `python discord_bot/bot.py`.

### Step 2.5 — Test via Discord

1. Open Discord and send a DM to your bot
2. Send: `whoami` — you should get instance info and broker URL
3. Send: `ping hello` — you should get `pong: hello`

If you get a reply, **the full pipeline works locally.**

---

## Phase 3: Recommended Production Deployment (VPS + Broker + Bot)

For production, the broker and Discord bot run on a VPS (e.g. Ubuntu). The runner can run on the same machine or elsewhere (Phase 4).

### Step 3.1 — Prepare the VPS

- SSH into your VPS
- Ensure Python 3.9+ is installed: `python3 --version`
- Clone the repo, e.g. to `/opt/openclaw/openclaw-broker`:

```bash
sudo mkdir -p /opt/openclaw
sudo chown $USER:$USER /opt/openclaw
git clone https://github.com/ChiefBoyardee/openclaw-broker.git /opt/openclaw/openclaw-broker
cd /opt/openclaw/openclaw-broker
```

**Optional (Tailscale):** Install Tailscale on the VPS and your runner machine(s). Then use the VPS Tailscale IP (e.g. `100.x.x.x`) for `BROKER_HOST` so the broker is reachable only on your tailnet.

### Step 3.2 — Onboard the broker

```bash
cd /opt/openclaw/openclaw-broker

# If scripts aren't executable (e.g. cloned from Windows):
bash deploy/onboard_broker.sh
```

The script will:

- Install the broker (venv, systemd unit)
- Ask for bind address (use `127.0.0.1` for same-host only, or your Tailscale IP for remote access)
- Ask for port (default `8000`)
- Generate or accept `WORKER_TOKEN` and `BOT_TOKEN`
- Write `/opt/openclaw-broker/broker.env`
- Optionally enable and start the service

**Save the printed output** — you need `WORKER_TOKEN`, `BOT_TOKEN`, and `BROKER_URL` for the runner and bot.

**Non-interactive example:**

```bash
BROKER_HOST=100.x.x.x BROKER_PORT=8443 ./deploy/onboard_broker.sh --enable
```

### Step 3.3 — Open firewall (if runner is on another machine)

If the runner will run off the VPS, the broker port must be reachable:

- **Tailscale:** See [docs/VPS_FIREWALL.md](VPS_FIREWALL.md) for Tailscale policy and firewalld
- **Public internet:** Open inbound **TCP 8000** (or your port) in your cloud provider’s firewall (DigitalOcean, Linode, AWS, etc.)

### Step 3.4 — Onboard the Discord bot

```bash
./deploy/onboard_bot.sh mybot
# Or: bash deploy/onboard_bot.sh mybot
```

You’ll be prompted for:

- `DISCORD_TOKEN` — from Discord Developer Portal
- `BOT_TOKEN` — same as broker
- `BROKER_URL` — e.g. `http://127.0.0.1:8000` (same host) or `http://100.x.x.x:8443` (Tailscale)
- `ALLOWED_USER_ID` — your Discord user ID
- Optional: `ALLOWED_CHANNEL_ID` (leave empty for DMs only)

When asked, enable and start the bot. Then:

```bash
journalctl -u openclaw-discord-bot@mybot -f
```

to watch logs. DM the bot `whoami` to confirm it’s running.

---

## Phase 4: Add the Runner (Worker)

The runner executes jobs. It can run on:

- **WSL** (Windows) — no systemd, start manually or via a script
- **Jetson / Linux** — systemd service
- **Same VPS as broker** — optional, but common setup is broker+bot on VPS, runner elsewhere

### Option A — Runner on WSL

1. Clone the repo on WSL and install:

```bash
cd /path/to/openclaw-broker
bash deploy/scripts/install_runner.sh
```

1. Create runner env:

```bash
./deploy/onboard_runner.sh
```

When prompted, paste `BROKER_URL` and `WORKER_TOKEN` from the broker onboarding output.

If the script isn’t executable: `bash deploy/onboard_runner.sh`

1. Start the runner:

```bash
# Default repo-local env created by onboard_runner.sh:
./runner/start.sh

# Or foreground:
export $(grep -v '^#' runner/runner.env | xargs)
python runner/runner.py

# Or use a non-default env path:
RUNNER_ENV=/path/to/runner.env ./runner/start.sh
```

1. Verify: From Discord, send `capabilities`. You should see the runner’s ID and capabilities.

### Option B — Runner on Jetson (or Linux with systemd)

1. Clone the repo on the Jetson
1. Install the systemd service:

```bash
./deploy/install_runner_systemd.sh
```

1. Edit the runner env (e.g. `/opt/openclaw-runner-jetson/runner.env`):

- `BROKER_URL` — broker address (Tailscale or VPS IP)
- `WORKER_TOKEN` — from broker onboarding

1. Enable and start:

```bash
sudo systemctl enable openclaw-runner
sudo systemctl start openclaw-runner
sudo journalctl -u openclaw-runner -f
```

---

## Phase 5: Optional — Repos, LLM, Multi-Worker

### Repo commands (repos, grep, cat)

For `repos`, `grep`, `cat`, etc., the runner needs a repo allowlist:

1. Create a JSON file, e.g. `/etc/openclaw/repos.json`:

```json
{
  "openclaw-broker": "openclaw-broker",
  "my-project": "../my-project"
}
```

1. In runner env, set:

```bash
RUNNER_REPOS_BASE=/home/you/src
RUNNER_REPO_ALLOWLIST=/etc/openclaw/repos.json
```

Paths in the allowlist are relative to `RUNNER_REPOS_BASE` or absolute (must stay under base). See [docs/RUNNER_REPO_CONFIG.md](RUNNER_REPO_CONFIG.md).

### LLM Configuration

For agentic mode and conversational features, the runner needs an OpenAI-compatible LLM endpoint:

1. Set in runner env:

```bash
LLM_PROVIDER=openai_compat
LLM_BASE_URL=http://127.0.0.1:8000/v1   # Your vLLM or similar
LLM_API_KEY=                             # Often empty for local
LLM_MODEL=your-model-name
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=4096
```

1. Verify the endpoint:

```bash
curl -s http://127.0.0.1:8000/v1/models | head
```

See [docs/MULTI_WORKER_LLM_SMOKE.md](MULTI_WORKER_LLM_SMOKE.md) for multi-worker caps and routing.

---

## Updating After Code Changes

After `git pull`, run the appropriate path for the topology you are actually using:

| Where | Script |
|-------|--------|
| VPS (broker + bots) | `bash deploy/scripts/update_vps.sh` |
| VPS (bot only; broker lives elsewhere) | `git pull`, then refresh each bot instance and restart `openclaw-discord-bot@<instance>` |
| Jetson runner | `bash deploy/scripts/update_runner_jetson.sh` then `sudo systemctl restart openclaw-runner` |
| WSL runner | `bash deploy/scripts/update_runner_wsl.sh` then restart the runner process |

See [docs/DEPLOY_AND_UPDATE.md](DEPLOY_AND_UPDATE.md) for details.

---

## Removing and Reinstalling the Discord Bot (Fresh Install)

If you already have a Discord bot installed on the VPS and want to remove it so you can install the latest version from scratch, use the steps below.

### 1. Find existing bot installations

**Systemd units (instance-based, current design):**

```bash
# List all OpenClaw Discord bot units (running or not)
systemctl list-units 'openclaw-discord-bot*' --all

# Or list unit files (shows template and any instantiated instances)
systemctl list-unit-files 'openclaw-discord-bot*'
```

Each instance appears as `openclaw-discord-bot@<instance_name>` (e.g. `openclaw-discord-bot@mybot`).

**Install directories:**

- **Per-instance (current):** `/opt/openclaw-bot-<instance_name>/` (code, venv, `bot.env`) and `/var/lib/openclaw-bot-<instance_name>/` (state, e.g. memory DB).
- **Legacy single-instance:** If you used an older `install_discord_bot.sh` flow, you may have `/opt/openclaw-discord-bot/` and a non-template unit `openclaw-discord-bot.service` (no `@`).

Check for existing dirs:

```bash
ls -la /opt/openclaw-bot-*
ls -la /var/lib/openclaw-bot-*
# Legacy single-instance:
ls -la /opt/openclaw-discord-bot 2>/dev/null || true
```

The **repo** (source code used for install/updates) is usually at `/opt/openclaw/openclaw-broker`. You do not need to remove it to do a “fresh bot install”; the install scripts overwrite each bot instance’s copy of the code.

### 2. Remove a specific bot instance

Replace `<instance_name>` with the name you used (e.g. `mybot`, `urgoclaw`).

```bash
INSTANCE=mybot   # your instance name

# Stop and disable the service
sudo systemctl stop "openclaw-discord-bot@${INSTANCE}"
sudo systemctl disable "openclaw-discord-bot@${INSTANCE}"

# Remove instance directories (code, venv, env, state)
sudo rm -rf "/opt/openclaw-bot-${INSTANCE}"
sudo rm -rf "/var/lib/openclaw-bot-${INSTANCE}"
```

If you remove **all** bot instances and want to remove the shared systemd template as well:

```bash
sudo rm -f /etc/systemd/system/openclaw-discord-bot@.service
sudo systemctl daemon-reload
```

### 3. Remove a legacy single-instance install

If you have the older setup (unit `openclaw-discord-bot.service`, no `@`):

```bash
sudo systemctl stop openclaw-discord-bot
sudo systemctl disable openclaw-discord-bot
sudo rm -f /etc/systemd/system/openclaw-discord-bot.service
sudo systemctl daemon-reload
sudo rm -rf /opt/openclaw-discord-bot   # if it exists
```

### 4. Fresh install after removal

From the repo on the VPS (e.g. `/opt/openclaw/openclaw-broker`):

```bash
cd /opt/openclaw/openclaw-broker
git pull
./deploy/onboard_bot.sh mybot
```

Use a new instance name or the same one you removed; when the instance dir is gone, the script creates it from scratch. When asked, enable and start the bot, then confirm with `whoami` in Discord.

---

## Overwrite and single-service behavior

- **Reusing the same instance name:** If you run `./deploy/onboard_bot.sh mybot` and `/opt/openclaw-bot-mybot/` already exists, the install script **overwrites** that instance: it replaces the bot code and venv and rewrites `bot.env`. There is only one systemd unit per instance name (`openclaw-discord-bot@mybot`), so only one service runs for that name. After re-onboarding, enable/start (or restart) the unit so it runs the new code:  
  `sudo systemctl enable --now openclaw-discord-bot@mybot` (or restart if already enabled).
- **Ports:** The Discord bot does **not** listen on a port; it connects out to Discord and to the broker. Uniqueness is by **instance name** (systemd unit), not by port. Multiple bot instances (different names) can run on the same host; each has its own `DISCORD_TOKEN` and unit (e.g. `openclaw-discord-bot@mybot`, `openclaw-discord-bot@urgoclaw`).
- **Broker:** The broker is a separate service and binds to a port (e.g. 8000). Only one broker process should use that port; the bot does not conflict with it.

---

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| **Job never completes; "Still running…"** | No runner connected, or runner can’t reach broker. Start the runner and confirm `BROKER_URL` and `WORKER_TOKEN` are correct. |
| **Connection refused to broker** | Broker not running or wrong host/port. On VPS: `systemctl status openclaw-broker` and `curl -s http://127.0.0.1:8000/health` |
| **Bot doesn’t respond** | Check allowlist: your `ALLOWED_USER_ID` must match your Discord user ID. Enable Developer Mode and copy ID again. |
| **"Invalid token" from broker** | `BOT_TOKEN` and `WORKER_TOKEN` must match between broker, bot, and runner. Re-copy from broker onboarding output. |
| **repos empty or grep fails** | Create allowlist at `RUNNER_REPO_ALLOWLIST` and set `RUNNER_REPOS_BASE`. Paths must exist and be git repos. |
| **LLM task fails** | Verify `LLM_BASE_URL` (include `/v1`), `LLM_MODEL`, and that the LLM endpoint responds to `/v1/models` |

### Quick health checks

```bash
# Broker
curl -s http://YOUR_BROKER_URL/health
# Expected: {"ok":true,"ts_bound":true}

# Discord checks
# DM the bot: whoami
# DM the bot: ping hello
# DM the bot: capabilities
# DM the bot: chat Hello

# Smoke test (local)
python scripts/smoke.py
# Expected: Smoke OK
```

---

## Summary Checklist

- [ ] Python 3.9+, Git, Discord account
- [ ] Cloned repo, created venv, installed requirements
- [ ] Generated `WORKER_TOKEN` and `BOT_TOKEN`
- [ ] Broker running (local or VPS)
- [ ] Discord Application created, bot token and your user ID saved
- [ ] Runner running (local, WSL, or Jetson)
- [ ] Firewall opened if broker and runner are on different machines
- [ ] DM’d bot `ping hello` and got `pong: hello`
- [ ] (Optional) Repo allowlist and LLM config for advanced commands

For more detail on specific areas, see the [Documentation](README.md#documentation) section in the main README.
