# OpenClaw Broker

A small, secure job queue: **broker** (FastAPI + SQLite), **runner** (worker that executes jobs), and **Discord bot** (create jobs from DMs and get results). Built for self-hosted use with optional Tailscale-only binding.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)  
**Requirements:** Python 3.9+

---

## Table of contents

- [Components](#components)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Test with curl](#test-with-curl)
- [API response shapes](#api-response-shapes)
- [Production deployment](#production-deployment)
- [Project structure](#project-structure)
- [Documentation](#documentation)

---

## Components

| Component    | Role |
|-------------|------|
| **Broker**  | FastAPI app: `GET /health`, `POST /jobs`, `GET /jobs/{id}`, `GET /jobs/next`, `POST /jobs/{id}/result`, `POST /jobs/{id}/fail`. Auth via `X-Bot-Token` and `X-Worker-Token`. Jobs support `failed` status, leases, and worker identity; stale running jobs are requeued. |
| **Runner**  | Worker process: polls `GET /jobs/next` (sends `X-Worker-Id`), runs jobs (`ping`, `capabilities`, `plan_echo`, `approve_echo`, `repo_list`, `repo_status`, `repo_last_commit`, `repo_grep`, `repo_readfile`), posts results or failures. For WSL or a dedicated worker machine. See [docs/RUNNER_REPO_CONFIG.md](docs/RUNNER_REPO_CONFIG.md) for repo allowlist and env. |
| **Discord bot** | Listens in DMs (or one channel); allowlisted user can send `ping`, `capabilities`, `plan <text>`, `approve <plan_id>`, `status <id>`, `repos`, `repostat <repo>`, `last <repo>`, `grep <repo> <query> [path]`, `cat <repo> <path> [start] [end]`, `whoami`. Guardrails: cooldown and max concurrent jobs per user. |

---

## Quick start

1. **Clone and set up a virtualenv**

   ```bash
   git clone https://github.com/ChiefBoyardee/openclaw-broker.git
   cd openclaw-broker
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Start the broker** (terminal 1)

   ```bash
   cp broker/broker.env.example broker/broker.env
   # Edit broker.env: set WORKER_TOKEN and BOT_TOKEN (e.g. openssl rand -hex 32)
   export BROKER_DB=./broker.db
   export WORKER_TOKEN=your_worker_token
   export BOT_TOKEN=your_bot_token
   uvicorn broker.app:app --reload --host 127.0.0.1 --port 8000
   ```

3. **Start the runner** (terminal 2)

   ```bash
   cp runner/runner.env.example runner/runner.env
   # Set BROKER_URL=http://127.0.0.1:8000 and WORKER_TOKEN to match broker
   export $(grep -v '^#' runner/runner.env | xargs)
   python runner/runner.py
   ```

4. **Start the Discord bot** (terminal 3)

   ```bash
   cp discord_bot/bot.env.example discord_bot/bot.env
   # Set DISCORD_TOKEN, BOT_TOKEN, ALLOWED_USER_ID, BROKER_URL
   export $(grep -v '^#' discord_bot/bot.env | xargs)
   python discord_bot/bot.py
   ```

5. **Test:** DM the bot `ping hello`; you should get a reply with the job result (e.g. `pong: hello`).

---

## Configuration

### Tokens

Generate strong random tokens for `WORKER_TOKEN` and `BOT_TOKEN`:

```bash
openssl rand -hex 32
```

Use the same `BOT_TOKEN` in the broker and in the Discord bot env. Use the same `WORKER_TOKEN` in the broker and in the runner env.

### Broker

- **`LEASE_SECONDS`** (optional, default `60`): When a worker claims a job, the broker sets a lease; if the worker dies, the job is requeued after the lease expires.

### Runner

- **`WORKER_ID`** (optional, default: hostname): Sent as `X-Worker-Id` on all broker requests; broker stores it on the job when claimed.
- **`RUNNER_STATE_DIR`** (optional, default `/var/lib/openclaw-runner/state`): Plan files for `plan_echo` / `approve_echo` are stored under `RUNNER_STATE_DIR/plans/`.
- **Commands:** `ping`, `capabilities`, `plan_echo`, `approve_echo`, `repo_list`, `repo_status`, `repo_last_commit`, `repo_grep`, `repo_readfile`. Repo commands require an allowlist and env; see [docs/RUNNER_REPO_CONFIG.md](docs/RUNNER_REPO_CONFIG.md) for `repos.json` format and `RUNNER_REPOS_BASE`, `RUNNER_REPO_ALLOWLIST`, timeouts, and output caps.

### Discord bot

- **Required:** `DISCORD_TOKEN`, `BOT_TOKEN`, `BROKER_URL`; at least one of **`ALLOWED_USER_ID`** (single ID) or **`ALLOWLIST_USER_ID`** (comma/space-separated IDs).
- **Optional:** `ALLOWED_CHANNEL_ID` (single channel; empty = DMs only), `INSTANCE_NAME`, `JOB_POLL_INTERVAL_SEC`, `JOB_POLL_TIMEOUT_SEC`, **`BOT_COOLDOWN_SECONDS`** (default `3`, per user), **`BOT_MAX_CONCURRENT`** (default `1`, per user).
- Full env table, run locally, example DM commands, and multi-instance deploy: [docs/DISCORD_BOT_DEPLOY.md](docs/DISCORD_BOT_DEPLOY.md). Smoke test: [docs/DISCORD_BOT_SMOKE.md](docs/DISCORD_BOT_SMOKE.md). **Env examples** (broker, runner, bot) and **streamlined onboarding**: [deploy/env.examples/](deploy/env.examples/), [deploy/onboard_bot.sh](deploy/onboard_bot.sh).

---

## Test with curl

Replace `YOUR_BOT_TOKEN`, `YOUR_WORKER_TOKEN`, and `JOB_ID` with real values.

**Health (no auth):**

```bash
curl -s http://127.0.0.1:8000/health
```

**Create job (bot token):**

```bash
curl -s -X POST http://127.0.0.1:8000/jobs \
  -H "X-Bot-Token: YOUR_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command":"ping","payload":"hello"}'
```

**Get next job (worker token; optional `X-Worker-Id`):**

```bash
curl -s http://127.0.0.1:8000/jobs/next \
  -H "X-Worker-Token: YOUR_WORKER_TOKEN" \
  -H "X-Worker-Id: my-worker"
```

**Post result (worker token):**

```bash
curl -s -X POST http://127.0.0.1:8000/jobs/JOB_ID/result \
  -H "X-Worker-Token: YOUR_WORKER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"result":"pong: hello"}'
```

**Post failure (worker token):**

```bash
curl -s -X POST http://127.0.0.1:8000/jobs/JOB_ID/fail \
  -H "X-Worker-Token: YOUR_WORKER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"error":"worker error message"}'
```

**Get job (bot token):**

```bash
curl -s http://127.0.0.1:8000/jobs/JOB_ID -H "X-Bot-Token: YOUR_BOT_TOKEN"
```

---

## API response shapes

Clients (bot, runner, future UIs) can rely on this contract:

| Endpoint | Response shape |
|----------|-----------------|
| **GET /health** | `{"ok": true, "ts_bound": true}` |
| **POST /jobs** | `{"id": "<uuid>", "status": "queued"}` |
| **GET /jobs/{id}** | Top-level job object (no wrapper). Keys: `id`, `created_at`, `started_at`, `finished_at`, `lease_until`, `status`, `command`, `payload`, `result`, `error`, `worker_id`. `status` is one of `queued`, `running`, `done`, `failed`. When `failed`, `error` is set. |
| **GET /jobs/next** | `{"job": <job object>}` or `{"job": null}`. Same job shape as GET /jobs/{id}. Send `X-Worker-Id` to record which worker claimed the job. |
| **POST /jobs/{id}/result** | `{"ok": true, "status": "done"}` or idempotent 200 with `"note"` when already done/failed. |
| **POST /jobs/{id}/fail** | `{"ok": true, "status": "failed"}` or idempotent 200 with `"note"` when already done/failed. |

---

## Production deployment

- **VPS (broker + Discord bot):** Clone to e.g. `/opt/openclaw/openclaw-broker`. **Streamlined:** run `./deploy/onboard_broker.sh` then `./deploy/onboard_bot.sh <instance>` for each bot (see [deploy/env.examples/](deploy/env.examples/)). **Manual:** Run `deploy/scripts/install_broker.sh`. For the Discord bot, the preferred approach is **multi-instance**: use the systemd template and install one instance per name (e.g. `clawhub`, `staging`) with `./deploy/install_bot_instance.sh <instance_name> [--enable]`. Each instance gets isolated dirs under `/opt/openclaw-bot-<instance>/` and `/var/lib/openclaw-bot-<instance>/`; env file is `/opt/openclaw-bot-<instance>/bot.env` (create from `bot.env.example`, never commit). Each instance needs its own Discord Application and `DISCORD_TOKEN` (and typically its own `BOT_TOKEN` and allowlist). Example: `./deploy/install_bot_instance.sh clawhub --enable` then `journalctl -u openclaw-discord-bot@clawhub -f`. See [docs/DISCORD_BOT_DEPLOY.md](docs/DISCORD_BOT_DEPLOY.md) for details. Single-instance legacy: `deploy/scripts/install_discord_bot.sh`. Create broker env and `/var/lib/openclaw-broker`; set `BROKER_HOST` to your Tailscale IP for tailnet-only binding. To configure and start the broker non-interactively on the VPS, run `./deploy/scripts/configure_and_start_broker.sh` (optionally `export BROKER_HOST=100.x.x.x` first). **After pulling updates:** run `bash deploy/scripts/update_vps.sh` to refresh deps and restart broker and all bot instances (see [docs/DEPLOY_AND_UPDATE.md](docs/DEPLOY_AND_UPDATE.md)).
- **WSL runner:** Run `deploy/scripts/install_runner.sh`, create `runner.env` from `runner/runner.env.example` with `BROKER_URL` and `WORKER_TOKEN`, then run `runner/start.sh` or `python runner/runner.py`. **After pulling:** run `bash deploy/scripts/update_runner_wsl.sh` then restart the runner.
- **VPS ↔ worker:** If the runner is off-VPS (e.g. WSL), open **TCP 8000** in your cloud provider’s firewall so the worker can reach the broker. See [docs/VPS_FIREWALL.md](docs/VPS_FIREWALL.md).

See [SECURITY.md](SECURITY.md) for token handling and tailnet-only binding.

---

## Project structure

```
openclaw-broker/
├── broker/              # FastAPI app
│   ├── app.py
│   └── broker.env.example
├── runner/
│   ├── runner.py
│   ├── runner.env.example
│   └── start.sh
├── discord_bot/
│   ├── bot.py
│   └── bot.env.example
├── deploy/
│   ├── systemd/         # openclaw-discord-bot@.service (multi-instance), openclaw-broker.service.template
│   ├── install_bot_instance.sh   # Install one bot instance (multi-instance deploy)
│   ├── onboard_broker.sh         # Onboard broker: install, tokens, broker.env, optional start
│   ├── onboard_runner.sh         # Onboard runner: paste BROKER_URL + WORKER_TOKEN, writes runner.env
│   ├── onboard_bot.sh            # Onboard new bot: paste tokens, creates bot.env and optionally starts
│   ├── env.examples/             # Broker, runner, bot env examples + README (VPS + WSL)
│   └── scripts/         # install_broker.sh, install_runner.sh, update_vps.sh, update_runner_*.sh
├── docs/
├── tests/
├── requirements.txt
├── README.md
├── SECURITY.md
└── LICENSE
```

---

## Documentation

- [SECURITY.md](SECURITY.md) — Token handling, tailnet-only binding, file permissions.
- [docs/DEPLOY_AND_UPDATE.md](docs/DEPLOY_AND_UPDATE.md) — CI (pytest on push/PR), update scripts after pull, optional CD (deploy VPS from GitHub Actions).
- [docs/DISCORD_BOT_DEPLOY.md](docs/DISCORD_BOT_DEPLOY.md) — Multi-instance Discord bot deployment (systemd template, env locations, whoami).
- [docs/PUSHING_TO_GITHUB.md](docs/PUSHING_TO_GITHUB.md) — Sanitization checklist and push steps.
- [docs/RUNNER_REPO_CONFIG.md](docs/RUNNER_REPO_CONFIG.md) — Defaults for future repo commands (search tool, repo paths, allowlist).

---

## License

[MIT](LICENSE)
