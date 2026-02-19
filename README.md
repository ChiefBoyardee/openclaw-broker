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
| **Runner**  | Worker process: polls `GET /jobs/next` (sends `X-Worker-Id`), runs jobs (`ping`, `capabilities`, `plan_echo`, `approve_echo`), posts results or failures. For WSL or a dedicated worker machine. |
| **Discord bot** | Listens in DMs (or one channel); allowlisted user can send `ping`, `capabilities`, `plan <text>`, `approve <plan_id>`, `status <id>`. Guardrails: cooldown and max concurrent jobs per user. |

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
- **Commands:** `ping`, `capabilities`, `plan_echo`, `approve_echo`. See [docs/RUNNER_REPO_CONFIG.md](docs/RUNNER_REPO_CONFIG.md) for future repo-command defaults (Sprint 3+).

### Discord bot

- **`BOT_COOLDOWN_SECONDS`** (optional, default `3`): Minimum seconds between commands per user.
- **`BOT_MAX_CONCURRENT`** (optional, default `1`): Max jobs in progress (queued or running) per user.

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

- **VPS (broker + Discord bot):** Clone to e.g. `/opt/openclaw/openclaw-broker`. Run `deploy/scripts/install_broker.sh` and `deploy/scripts/install_discord_bot.sh`. Create env files from the `.env.example` templates; set `BROKER_HOST` to your Tailscale IP for tailnet-only binding. Create `/var/lib/openclaw-broker` for the SQLite DB. Start with `sudo systemctl start openclaw-broker openclaw-discord-bot`.
- **WSL runner:** Run `deploy/scripts/install_runner.sh`, create `runner.env` from `runner/runner.env.example` with `BROKER_URL` and `WORKER_TOKEN`, then run `runner/start.sh` or `python runner/runner.py`.

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
│   ├── systemd/         # Service templates
│   └── scripts/         # install_broker.sh, install_discord_bot.sh, install_runner.sh
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
- [docs/PUSHING_TO_GITHUB.md](docs/PUSHING_TO_GITHUB.md) — Sanitization checklist and push steps.
- [docs/RUNNER_REPO_CONFIG.md](docs/RUNNER_REPO_CONFIG.md) — Defaults for future repo commands (search tool, repo paths, allowlist).

---

## License

[MIT](LICENSE)
