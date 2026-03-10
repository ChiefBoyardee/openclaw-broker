# Alternate Runbook: WSL (Broker + LLM + Runner) and VPS (Discord Bot)

Use this only when you intentionally want **WSL** to run the broker, LLM, and runner, while the **VPS** runs only the Discord bot.  
Goal: Discord bot on latest version, LLM running so you can chat with the bot using natural language.

For the recommended beginner topology (`VPS = broker + bot`, `WSL = runner`), use [docs/INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md) instead.

---

## Prerequisites

- **WSL:** Rocky Linux 9, logged in as **root** (no `sudo` needed).
- **VPS:** Rocky Linux 9, user that **can** use `sudo`.
- **Network:** VPS must reach the broker on WSL (e.g. **Tailscale** on both: WSL broker binds to Tailscale IP; VPS uses `BROKER_URL=http://100.x.x.x:8000`). If broker and bot are on the same host, use `http://127.0.0.1:8000`.
- **Discord:** One Discord Application, Bot token, and your **User ID** (Developer Mode → right‑click you → Copy ID).

---

## Part A — WSL (Rocky 9, root): Broker + Runner + LLM

Run these on the WSL box. Use a single install directory; below we use `/opt/openclaw/openclaw-broker`.

## A.1 — Clone and prepare repo

```bash
mkdir -p /opt/openclaw
cd /opt/openclaw
git clone https://github.com/ChiefBoyardee/openclaw-broker.git openclaw-broker
cd openclaw-broker
```

## A.2 — Broker: venv, env file, and tokens

```bash
cd /opt/openclaw/openclaw-broker

python3 -m venv .venv-broker
.venv-broker/bin/pip install -r requirements.txt

# Generate tokens (save both; you need them for runner and VPS bot)
WORKER_TOKEN=$(openssl rand -hex 32)
BOT_TOKEN=$(openssl rand -hex 32)
echo "WORKER_TOKEN=$WORKER_TOKEN"
echo "BOT_TOKEN=$BOT_TOKEN"

mkdir -p /var/lib/openclaw-broker
```

Create broker env. Use **Tailscale IP** (e.g. `100.x.x.x`) so the VPS bot can reach this broker; if only local, use `127.0.0.1`:

```bash
mkdir -p /opt/openclaw-broker
cat > /opt/openclaw-broker/broker.env << EOF
BROKER_DB=/var/lib/openclaw-broker/broker.db
WORKER_TOKEN=$WORKER_TOKEN
BOT_TOKEN=$BOT_TOKEN
BROKER_HOST=100.x.x.x
BROKER_PORT=8000
EOF
```

Replace `100.x.x.x` with your WSL Tailscale IP (or `0.0.0.0` to bind all interfaces; then set `BROKER_BIND_PUBLIC=1` to silence the warning).

## A.3 — Runner: install and configure

```bash
cd /opt/openclaw/openclaw-broker
bash deploy/scripts/install_runner.sh
```

Create `runner/runner.env` (use the same `WORKER_TOKEN` and your broker URL; if broker is on this host use `http://127.0.0.1:8000`):

```bash
export BROKER_URL="http://127.0.0.1:8000"
export WORKER_TOKEN="<paste WORKER_TOKEN from A.2>"
bash deploy/onboard_runner.sh
```

Or paste when prompted:

```bash
bash deploy/onboard_runner.sh
# Enter BROKER_URL (e.g. http://127.0.0.1:8000), then WORKER_TOKEN, then optional WORKER_ID.
```

## A.4 — LLM (llama.cpp, no sudo)

This uses the project’s WSL + llama.cpp path; run as root but install is `--user`-style so no system dirs needed.

```bash
cd /opt/openclaw/openclaw-broker
BROKER_URL=http://127.0.0.1:8000 WORKER_TOKEN="<same WORKER_TOKEN>" ./deploy/install_wsl_llamacpp.sh --user
```

Follow prompts (model download if needed). If you have a GGUF already:

```bash
MODEL_PATH=/path/to/your.gguf BROKER_URL=http://127.0.0.1:8000 WORKER_TOKEN="<same WORKER_TOKEN>" ./deploy/install_wsl_llamacpp.sh --user
```

The script configures the runner to use the local llama.cpp server and writes the default repo-local env file at `runner/runner.env`.

## A.5 — Start broker (Terminal 1)

```bash
cd /opt/openclaw/openclaw-broker
set -a
source /opt/openclaw-broker/broker.env
set +a
.venv-broker/bin/python broker/app.py
```

Leave this running. You should see the broker listening on the chosen host/port.

## A.6 — Start LLM server (Terminal 2)

If `install_wsl_llamacpp.sh` put the server under `$HOME` or `/opt/llama-cpp-server`:

```bash
# If script created a user-mode install:
~/.local/llama-cpp-server/start-server.sh
# Or, for a system install:
/opt/llama-cpp-server/start-server.sh
```

Use the path printed at the end of `install_wsl_llamacpp.sh`. Leave this running.

## A.7 — Start runner (Terminal 3)

```bash
cd /opt/openclaw/openclaw-broker
./runner/start.sh
```

Or foreground (no log file):

```bash
cd /opt/openclaw/openclaw-broker
export $(grep -v '^#' runner/runner.env | xargs)
.venv-runner/bin/python -u runner/runner.py
```

## A.8 — Quick checks on WSL

```bash
curl -s http://127.0.0.1:8000/health
# Expect: {"ok":true,"ts_bound":true}

curl -s http://127.0.0.1:8000/v1/models
# Expect: list of models (LLM server)
```

Save **WORKER_TOKEN** and **BOT_TOKEN**; the VPS bot needs **BOT_TOKEN** and **BROKER_URL** pointing at this WSL broker (e.g. `http://<WSL_TAILSCALE_IP>:8000`).

---

## Part B — VPS (Rocky 9, with sudo): Discord bot only

Run these on the VPS. Broker is on WSL; bot will use `BROKER_URL` to that broker (e.g. Tailscale).

## B.1 — Clone repo

```bash
sudo mkdir -p /opt/openclaw
sudo chown "$USER:$USER" /opt/openclaw
git clone https://github.com/ChiefBoyardee/openclaw-broker.git /opt/openclaw/openclaw-broker
cd /opt/openclaw/openclaw-broker
```

## B.2 — Onboard the Discord bot (one instance)

You need: **DISCORD_TOKEN** (Discord Developer Portal → Bot), **BOT_TOKEN** (from WSL A.2), **BROKER_URL** (WSL broker, e.g. `http://100.x.x.x:8000`), **ALLOWED_USER_ID** (your Discord user ID).

```bash
cd /opt/openclaw/openclaw-broker
bash deploy/onboard_bot.sh mybot
```

When prompted, enter:

- **DISCORD_TOKEN:** from Discord Developer Portal
- **BOT_TOKEN:** same as on WSL (from A.2)
- **BROKER_URL:** e.g. `http://100.x.x.x:8000` (WSL Tailscale IP and port) or `http://127.0.0.1:8000` if broker were on this VPS
- **ALLOWED_USER_ID:** your Discord user ID
- **ALLOWLIST_USER_ID / ALLOWED_CHANNEL_ID:** optional; leave empty if you only use DMs

When asked, enable and start the bot (e.g. `y`).

## B.3 — Watch bot logs

```bash
journalctl -u openclaw-discord-bot@mybot -f
```

## B.4 — Test in Discord

DM the bot:

- `whoami` — instance and broker URL
- `ping hello` — should get `pong: hello`
- `capabilities` — should show the WSL runner (and its caps, e.g. `llm:llamacpp`)
- `Hello, say hi in one word.` — should go to WSL LLM and reply (natural language)

---

## Updating to latest version

## WSL (broker + runner + LLM)

```bash
cd /opt/openclaw/openclaw-broker
git pull
.venv-broker/bin/pip install -r requirements.txt -q
.venv-runner/bin/pip install -r requirements.txt -q
```

Then restart **broker**, **LLM server**, and **runner** (stop and start the three processes).

## VPS (Discord bot only)

The project’s `update_vps.sh` assumes the broker also runs on the VPS. If you run **only the bot** on the VPS, use:

```bash
cd /opt/openclaw/openclaw-broker
git pull
```

Then update each bot instance and restart:

```bash
INSTANCE=mybot
sudo rm -rf /opt/openclaw-bot-${INSTANCE}/discord_bot
sudo cp -r /opt/openclaw/openclaw-broker/discord_bot /opt/openclaw-bot-${INSTANCE}/
sudo cp /opt/openclaw/openclaw-broker/requirements.txt /opt/openclaw-bot-${INSTANCE}/
sudo chown -R openclaw:openclaw /opt/openclaw-bot-${INSTANCE}/discord_bot /opt/openclaw-bot-${INSTANCE}/requirements.txt
sudo -u openclaw /opt/openclaw-bot-${INSTANCE}/venv/bin/pip install -r /opt/openclaw-bot-${INSTANCE}/requirements.txt -q
sudo systemctl restart "openclaw-discord-bot@${INSTANCE}"
```

Replace `mybot` with your instance name. Repeat for each instance.

---

## Summary

| Where | What runs | Main commands |
|-------|-----------|----------------|
| **WSL (root)** | Broker, LLM server, Runner | Clone → broker.env + tokens → install runner → install_wsl_llamacpp.sh --user → start broker, then LLM server, then runner |
| **VPS (sudo)** | Discord bot only | Clone → onboard_bot.sh mybot → journalctl for logs |

**Tokens:** Generate once on WSL (A.2). Use **BOT_TOKEN** and **BROKER_URL** (WSL broker URL) on the VPS in `onboard_bot.sh`. Use **WORKER_TOKEN** in WSL runner env and keep it secret.

**Chat with bot:** After broker, runner, and LLM are up on WSL and the bot is up on VPS, use Discord natural language (or add routing hints like "preferred llamacpp" if you have multiple workers).
