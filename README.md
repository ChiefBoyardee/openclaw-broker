# OpenClaw Broker

Secure **broker + worker runner + Discord bot** system: a FastAPI job queue (SQLite-backed), a runner that long-polls for jobs and posts results, and a Discord bot that creates jobs from DMs and replies with results.

## Components

| Component   | Role |
|------------|------|
| **Broker** | FastAPI app: `GET /health`, `POST /jobs`, `GET /jobs/{id}`, `GET /jobs/next`, `POST /jobs/{id}/result`, `POST /jobs/{id}/fail`. Auth via `X-Bot-Token` and `X-Worker-Token`. Jobs support `failed` status and leases; stale running jobs are requeued. |
| **Runner** | Worker process: polls `GET /jobs/next` (sends `X-Worker-Id`), runs the job (`ping`, `capabilities`, `plan_echo`, `approve_echo`), posts `POST /jobs/{id}/result` or `/fail`. For WSL or worker machines. |
| **Discord bot** | Listens to DMs (or one channel); allowlisted user can send `ping`, `capabilities`, `plan <text>`, `approve <plan_id>`, `status <id>`. Guardrails: cooldown and max concurrent jobs per user. |

## Requirements

- Python 3.9+
- See `requirements.txt` for dependencies (FastAPI, uvicorn, pydantic, requests, discord.py).

## Local dev quickstart

1. **Clone and venv**
   ```bash
   cd openclaw-broker
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Broker**
   ```bash
   cp broker/broker.env.example broker/broker.env
   # Edit broker.env: set WORKER_TOKEN and BOT_TOKEN (e.g. openssl rand -hex 32)
   export BROKER_DB=./broker.db
   export WORKER_TOKEN=your_worker_token
   export BOT_TOKEN=your_bot_token
   python broker/app.py
   # Or: uvicorn broker.app:app --reload --host 127.0.0.1 --port 8000
   ```

3. **Runner** (second terminal)
   ```bash
   cp runner/runner.env.example runner/runner.env
   # Set BROKER_URL=http://127.0.0.1:8000 and same WORKER_TOKEN
   export $(grep -v '^#' runner/runner.env | xargs)
   python runner/runner.py
   ```

4. **Discord bot** (third terminal)
   ```bash
   cp discord_bot/bot.env.example discord_bot/bot.env
   # Set DISCORD_TOKEN, BOT_TOKEN, ALLOWED_USER_ID, BROKER_URL
   export $(grep -v '^#' discord_bot/bot.env | xargs)
   python discord_bot/bot.py
   ```

5. **Test:** DM the bot `ping hello`; you should get a reply with the job result (e.g. `pong: hello`).

## Generate tokens

Use strong random tokens for `WORKER_TOKEN` and `BOT_TOKEN`:

```bash
openssl rand -hex 32
```

Use the same `BOT_TOKEN` in the broker and in the Discord bot env. Use the same `WORKER_TOKEN` in the broker and in the runner env.

**Broker:** Optional `LEASE_SECONDS` (default 60). When a worker claims a job, the broker sets a lease; if the worker dies, the job is requeued after the lease expires.

**Runner:** Optional `WORKER_ID` (default: hostname). Sent as `X-Worker-Id` on all broker requests; broker stores it on the job when claimed. Optional `RUNNER_STATE_DIR` (default `/var/lib/openclaw-runner/state`); plan files for `plan_echo`/`approve_echo` are stored under `RUNNER_STATE_DIR/plans/`. For future repo commands (Sprint 3+), see [docs/RUNNER_REPO_CONFIG.md](docs/RUNNER_REPO_CONFIG.md) (search tool, repo paths, allowlist location).

**Commands (runner):** `ping`, `capabilities` (returns worker id + capability list), `plan_echo` (payload = plan text; creates a plan file and returns plan_id), `approve_echo` (payload = plan_id; reads plan file and returns approval; scaffold only, no-op).

**Discord bot:** Optional `BOT_COOLDOWN_SECONDS` (default 3) and `BOT_MAX_CONCURRENT` (default 1). Per-user cooldown between commands and max jobs in progress (queued or running).

## Test with curl

- Health (no auth):
  ```bash
  curl -s http://127.0.0.1:8000/health
  ```
- Create job (bot token):
  ```bash
  curl -s -X POST http://127.0.0.1:8000/jobs \
    -H "X-Bot-Token: YOUR_BOT_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"command":"ping","payload":"hello"}'
  ```
- Get next job (worker token; optional `X-Worker-Id` to tag the claim):
  ```bash
  curl -s http://127.0.0.1:8000/jobs/next \
    -H "X-Worker-Token: YOUR_WORKER_TOKEN" \
    -H "X-Worker-Id: my-worker"
  ```
- Post result (worker token):
  ```bash
  curl -s -X POST http://127.0.0.1:8000/jobs/JOB_ID/result \
    -H "X-Worker-Token: YOUR_WORKER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"result":"pong: hello"}'
  ```
- Post failure (worker token):
  ```bash
  curl -s -X POST http://127.0.0.1:8000/jobs/JOB_ID/fail \
    -H "X-Worker-Token: YOUR_WORKER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"error":"worker error message"}'
  ```
- Get job (bot token):
  ```bash
  curl -s http://127.0.0.1:8000/jobs/JOB_ID -H "X-Bot-Token: YOUR_BOT_TOKEN"
  ```

## API response shapes

Response bodies are documented so clients (bot, runner, future UIs) can rely on a stable contract.

- **GET /health** — `{"ok": true, "ts_bound": true}`

- **POST /jobs** — `{"id": "<uuid>", "status": "queued"}`

- **GET /jobs/{id}** — **Top-level job object** (no wrapper). All keys present; use `null` when absent:
  - `id`, `created_at`, `started_at`, `finished_at`, `lease_until`, `status`, `command`, `payload`, `result`, `error`, `worker_id`
  - `status` is one of: `queued`, `running`, `done`, `failed`. When `failed`, `error` is set. `worker_id` is set when a worker claims the job (optional `X-Worker-Id` header).

- **GET /jobs/next** — `{"job": <job object>}` or `{"job": null}`. When present, `<job object>` uses the same shape as GET /jobs/{id}. Send `X-Worker-Id` to record which worker claimed the job.

- **POST /jobs/{id}/result** — `{"ok": true, "status": "done"}` or (if already done/failed) idempotent 200 with same or `"note"` field.

- **POST /jobs/{id}/fail** — `{"ok": true, "status": "failed"}` or (if already done/failed) idempotent 200 with same or `"note"` field.

For this MVP the bot and runner use these shapes as-is. If you add another UI or client later, consider making all responses either consistently wrapped (e.g. always `{"job": ...}`) or consistently unwrapped; the current mix (unwrapped job for GET /jobs/{id}, wrapped for GET /jobs/next) is intentional and works well for the existing clients.

## Production deployment outline

- **VPS (broker + Discord bot):**
  - Clone repo to e.g. `/opt/openclaw/openclaw-broker`.
  - Run `deploy/scripts/install_broker.sh` and `deploy/scripts/install_discord_bot.sh` (optionally with `--enable` to enable the unit).
  - Create env files from the `.env.example` templates (see install script output): broker at `/opt/openclaw-broker/broker.env`, bot at `/opt/openclaw-discord-bot/bot.env`. Set `BROKER_HOST` to your Tailscale IP for tailnet-only binding.
  - Create `/var/lib/openclaw-broker` and ensure the broker user can write the SQLite DB.
  - Start: `sudo systemctl start openclaw-broker openclaw-discord-bot`.

- **WSL runner:**
  - Clone repo (or copy runner + `requirements.txt`). Run `deploy/scripts/install_runner.sh` (creates venv, no systemd).
  - Create `/opt/openclaw-runner/runner.env` from `runner/runner.env.example` with `BROKER_URL` (broker’s Tailscale URL) and `WORKER_TOKEN`.
  - Run `runner/start.sh` (logs to `/var/log/openclaw-runner/runner.log`); or run `python runner/runner.py` in a terminal/screen.

See `SECURITY.md` for token handling and tailnet-only binding.

## Repo structure

```
openclaw-broker/
  broker/           # FastAPI app
  runner/            # Worker runner + start.sh + runner.env.example
  discord_bot/       # Discord bot + bot.env.example
  deploy/
    systemd/         # Service templates (broker, discord bot)
    scripts/         # install_broker.sh, install_discord_bot.sh, install_runner.sh
  requirements.txt
  README.md
  SECURITY.md
  .gitignore
  LICENSE
```

## Checklist: copy existing working files into this repo

If you already have a working prototype and want to drop it into this skeleton:

- [ ] **Broker:** Replace or merge `broker/app.py` with your broker logic; keep or adapt env vars to match `broker/broker.env.example`.
- [ ] **Runner:** Replace or merge `runner/runner.py` with your runner (and any new commands beyond `ping`); align `runner/runner.env.example` with your env.
- [ ] **Discord bot:** Replace or merge `discord_bot/bot.py` with your bot (commands, allowlist, channel logic); align `discord_bot/bot.env.example`.
- [ ] **Env files:** Copy your real `broker.env`, `bot.env`, `runner.env` into the deploy paths (e.g. `/opt/openclaw-broker/broker.env`) — do not commit them.
- [ ] **Deploy:** Adjust `deploy/systemd/*.template` and `deploy/scripts/*.sh` if your paths or service names differ.
- [ ] **Dependencies:** Update `requirements.txt` if you use extra packages.
- [ ] **Tokens:** Regenerate or reuse your existing `WORKER_TOKEN` and `BOT_TOKEN`; ensure broker, bot, and runner all use the same tokens where required.
