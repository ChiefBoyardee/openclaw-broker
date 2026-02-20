# OpenClaw env examples

One-place reference for all component env files. **Do not commit real `.env` or `*.env` files** — only the `.example` files live in git.

## Quick start (VPS)

From the repo root on the VPS:

1. **Broker (one-time)** — install, generate tokens, create `broker.env`, optional start:
   ```bash
   ./deploy/onboard_broker.sh
   ```
   Or with Tailscale and custom port: `BROKER_HOST=100.x.x.x BROKER_PORT=8443 ./deploy/onboard_broker.sh --enable`  
   Save the printed `WORKER_TOKEN`, `BOT_TOKEN`, and `BROKER_URL` for the runner and bots.

2. **Discord bot (per instance)** — paste tokens and allowlist ID:
   ```bash
   ./deploy/onboard_bot.sh <instance_name>
   ```
   Use the `BOT_TOKEN` and `BROKER_URL` from step 1.

3. **Runner (WSL/worker)** — from repo root on WSL, run `./deploy/onboard_runner.sh` and paste `BROKER_URL` and `WORKER_TOKEN` from step 1 (or set them in env). This creates `runner/runner.env`. Then run `python runner/runner.py` or `runner/start.sh`.

## Layout

| Component | Env file | Where it lives |
|-----------|----------|----------------|
| **Broker** | [broker.env.example](broker.env.example) | VPS: `/opt/openclaw-broker/broker.env` (or path used by systemd) |
| **Runner** | [runner.env.example](runner.env.example) | WSL/worker: e.g. `runner/runner.env` or `/opt/openclaw-runner/runner.env` |
| **Discord bot** | [bot.env.example](bot.env.example) | VPS per instance: `/opt/openclaw-bot-<instance>/bot.env` |

## Our environment (VPS + WSL)

- **VPS:** Broker + one or more Discord bot instances. Broker bound to Tailscale IP (e.g. `http://100.x.x.x:8443`).
- **WSL:** Runner; connects to broker over Tailscale or opened firewall (TCP 8000 or your port).

### Broker (VPS)

- Generate tokens once: `openssl rand -hex 32` for each of `WORKER_TOKEN` and `BOT_TOKEN`.
- Set `BROKER_HOST` to your Tailscale IP (e.g. `100.64.0.1`) and `BROKER_PORT=8443` if not 8000.
- Use the same `BOT_TOKEN` in every bot instance that should talk to this broker.

### Runner (WSL)

- `BROKER_URL=http://<VPS_TAILSCALE_IP>:8443` (or `:8000` if you use 8000).
- `WORKER_TOKEN` = broker’s `WORKER_TOKEN`.

### Discord bot (VPS, per instance)

- Each instance = one Discord Application → one `DISCORD_TOKEN`.
- `BOT_TOKEN` = broker’s `BOT_TOKEN`.
- `BROKER_URL=http://127.0.0.1:8000` (if broker is on same host) or `http://<VPS_TAILSCALE_IP>:8443` if you use Tailscale and a different port.
- `ALLOWED_USER_ID` or `ALLOWLIST_USER_ID` = your Discord user ID (right‑click your user → Copy ID; Developer Mode must be on).

Use the **onboarding scripts** so you rarely edit env files by hand:

- **Broker:** `./deploy/onboard_broker.sh` — installs broker, prompts for bind address/port, generates or accepts tokens, writes `broker.env`, optionally starts. Use `--enable` to start without prompting.
- **Runner:** `./deploy/onboard_runner.sh` — prompts for `BROKER_URL` and `WORKER_TOKEN` (from broker), writes `runner/runner.env`. No sudo; run on WSL or worker machine.
- **Bot:** `./deploy/onboard_bot.sh <instance_name>` — installs one bot instance, prompts for `DISCORD_TOKEN`, `BOT_TOKEN`, `BROKER_URL`, and allowlist ID(s), writes `bot.env`, optionally starts.
