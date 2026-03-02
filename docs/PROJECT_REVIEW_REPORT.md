# OpenClaw Broker — Project Review Report

This report provides a top-to-bottom review of the openclaw-broker repository: design, security, reliability, operations, code quality, risks, and prioritized recommendations. It is intended to be handed to a collaborator as a status and risk review.

---

## 1) Executive Summary

### What the system does today (end-to-end)

OpenClaw Broker is a small job-queue system that connects a Discord bot to one or more workers (runners). End-to-end flow:

1. **Discord** — Allowlisted users send commands (e.g. `ping`, `ask <prompt>`, `repos`, `cat <repo> <path>`) via DM or an allowed channel.
2. **Discord bot** — Parses the command, creates a job via `POST /jobs` with `X-Bot-Token`, and waits for the result by polling `GET /jobs/{id}` until the job is done, failed, or a timeout is reached.
3. **Broker** — FastAPI service with a SQLite-backed queue. It accepts job creation (bot) and job claim/result/fail (workers). On `GET /jobs/next`, it atomically requeues stale running jobs (lease expired), then assigns the oldest queued job that matches the worker’s capabilities (caps). Workers identify themselves with `X-Worker-Token` and optional `X-Worker-Caps`.
4. **Runner(s)** — Long-poll `GET /jobs/next`, execute the command (e.g. `ping`, `capabilities`, `repo_list`, `repo_status`, `repo_grep`, `repo_readfile`, `plan_echo`, `approve_echo`, `llm_task`), then `POST /jobs/{id}/result` or `POST /jobs/{id}/fail`. For `llm_task`, the runner runs an LLM tool loop (OpenAI-compatible API + tool registry) and returns a result envelope.
5. **LLM** — Used only by the runner for `llm_task`. The runner calls an OpenAI-compatible endpoint (e.g. vLLM) with tools (repo read-only tools + plan_echo/approve_echo). Config (base URL, model, API key) lives in the runner’s environment only.

Multi-worker routing is done by **caps**: jobs can require `{"caps": ["llm:vllm"]}` or `["llm:jetson"]`; only workers advertising those caps can claim them. The Discord `ask`/`urgo` commands can force routing with prefixes like `ask vllm: ...` or `ask jetson: ...`.

### What’s working well

- **Clear auth boundaries**: Bot token for create/read jobs; worker token for claim/result/fail. No auth on `/health` (liveness only).
- **Allowlist and redaction**: Only allowlisted Discord user IDs (and optional channel) can use the bot. All user-facing replies are redacted for `BOT_TOKEN` and `DISCORD_TOKEN`.
- **Atomic claim and requeue**: Broker uses a single `BEGIN IMMEDIATE` transaction to requeue stale running jobs and claim the next matching queued job, avoiding double-claim.
- **Path safety in repo tools**: Runner resolve_repo_path() and _repo_readfile() enforce allowlist and realpath-under-base; path traversal and “..” are rejected; tests cover these cases.
- **Idempotent result/fail**: Broker accepts result or fail when already done/failed and returns 200 without changing state.
- **Deploy and onboarding**: Streamlined onboard scripts (broker, bot, runner) and multi-instance Discord bot systemd template; docs (DISCORD_BOT_DEPLOY, MULTI_WORKER_LLM_SMOKE, VPS_FIREWALL, DEPLOY_AND_UPDATE) are in place.

### Top 5 risks (security / reliability / ops)

1. **Discord token compromise** — Full control of the bot (create jobs, read results). Mitigation: keep token in env only; redaction prevents leaking into replies. No additional in-app mitigation.
2. **Broker token compromise** — Anyone with `BOT_TOKEN` can create and read all jobs (and results); anyone with `WORKER_TOKEN` can claim and complete jobs. Mitigation: tokens in env files only; bind broker to Tailscale IP to limit who can reach it.
3. **Prompt injection / tool abuse** — LLM output could theoretically steer tool calls. Mitigation: tools are allowlisted; repo access is allowlist + path checks; no write or shell tools.
4. **Job flooding / DoS** — Mitigated in Sprint 1: broker-side `MAX_QUEUED_JOBS` returns 429 when at cap; per-user cooldown and max concurrent in bot remain. Set `MAX_QUEUED_JOBS` in broker.env to enable.
5. **SQLite and backup** — Mitigated in Sprint 1: broker enables WAL at startup; [BROKER_BACKUP_RETENTION.md](BROKER_BACKUP_RETENTION.md) documents backup options, retention/pruning, and WAL sidecar files.

### High-confidence readiness statement

**Sprint 1 hardening applied.** Suitable for personal or small-team use with the broker and bot on a VPS and runner(s) on trusted machines (e.g. WSL, Jetson), preferably over Tailscale. WAL, backup docs, job cap, and whoami URL masking are in place; see [RELEASE_NOTES.md](RELEASE_NOTES.md) for env vars and rollback.

### Next 3 sprints (high level)

- **Sprint 1**: Done — SQLite WAL, backup/retention doc, MAX_QUEUED_JOBS, WHOAMI_BROKER_URL_MODE, smoke script, lint in CI, caps extraction.
- **Sprint 2**: Done — WSL runner log rotation doc, smoke script (no Discord), ruff config, CI lint+tests, caps extraction and unit tests.
- **Sprint 3**: Observability — optional additional E2E coverage.

---

## 2) Architecture Overview

### Diagram (ASCII)

```text
  Discord (allowlisted users)
         |
         v
  +-------------+     X-Bot-Token      +------------------+
  | Discord Bot | ------------------> | Broker (FastAPI) |
  | (bot.py)    |   POST/GET /jobs     | SQLite queue     |
  +-------------+ <------------------ +------------------+
         ^                                      ^
         | user replies (redacted)               | GET /jobs/next
         |                                      | POST result/fail
         |                                      | X-Worker-Token
         |                             +--------+--------+
         |                             | Runner(s)      |
         |                             | runner.py     |
         |                             | llm_loop.py   |
         |                             | tool_registry |
         |                             +--------+------+
         |                                      |
         |                                      v
         |                             +------------------+
         |                             | LLM endpoint     |
         |                             | (vLLM / OpenAI- |
         |                             |  compat)         |
         +----------------------------- (result in reply)
```

### Trust boundaries and where secrets live

| Boundary | Secret / trust |
|----------|-----------------|
| Discord → Bot | Discord token (env); allowlist (env). Only allowlisted users/channel get responses. |
| Bot ↔ Broker | Shared `BOT_TOKEN` (bot and broker env). Bot creates/reads jobs. |
| Broker ↔ Runner(s) | Shared `WORKER_TOKEN` (broker and runner env). Runners claim and complete jobs. |
| Runner → LLM | `LLM_API_KEY` and `LLM_BASE_URL` only in runner env; never sent to broker or bot. |

Secrets live only in env files: `broker.env`, `bot.env` (per instance), `runner.env`. They are not committed (`.gitignore` excludes `*.env`); onboarding scripts write env files from prompts or from non-committed values.

### Multi-instance and multi-worker behavior

- **Bot**: Multi-instance via systemd template `openclaw-discord-bot@.service`; each instance has its own dir (e.g. `/opt/openclaw-bot-<instance>/`), env file, and Discord token.
- **Broker**: Single process; no horizontal scaling. Multiple workers can poll `/jobs/next`; the broker assigns at most one job per request and uses caps to match jobs to workers (e.g. `llm:vllm` vs `llm:jetson`). There is no per-worker queue; the first worker whose caps match the oldest queued job gets it.

---

## 3) Component Review

### A) Broker (FastAPI)

| Aspect | Details |
|--------|---------|
| **Responsibilities** | Job queue (create, read, claim, result, fail); atomic claim with lease; requeue of stale running jobs; capability-based filtering so only workers with matching caps can claim a job. |
| **Key endpoints** | `GET /health` (no auth); `POST /jobs` (X-Bot-Token); `GET /jobs/{job_id}` (X-Bot-Token); `GET /jobs/next` (X-Worker-Token, optional X-Worker-Id, X-Worker-Caps); `POST /jobs/{job_id}/result` (X-Worker-Token); `POST /jobs/{job_id}/fail` (X-Worker-Token). |
| **Authentication** | `require_bot_token` and `require_worker_token` Depends; direct string comparison of header to env `BOT_TOKEN` / `WORKER_TOKEN`. 401 on wrong/missing; 500 if token not configured. |
| **Failure handling and idempotency** | Result and fail are idempotent when job is already done or failed (200, no state change). Requeue of stale running jobs happens inside the same transaction as claim. |
| **Important config/env** | `BROKER_DB`, `WORKER_TOKEN`, `BOT_TOKEN`, `LEASE_SECONDS` (default 60), `BROKER_HOST`, `BROKER_PORT`. |
| **Notable implementation details** | Schema migration on startup (`migrate_db()` adds columns and indexes if missing). Caps: `_parse_worker_caps` (JSON array or comma-separated), `_job_required_caps` from job `requires` JSON; job is claimable iff required caps ⊆ worker caps (or requires empty). Single `BEGIN IMMEDIATE` transaction for requeue + select + claim. SQLite connection timeout 10s. No WAL mode set. |

### B) Runner (tool execution, repo tools, llm_task loop)

| Aspect | Details |
|--------|---------|
| **Responsibilities** | Long-poll broker `/jobs/next`; execute command (ping, capabilities, plan_echo, approve_echo, repo_*, llm_task); post result or fail with retries; enforce repo allowlist and path safety; run LLM tool loop for llm_task. |
| **Key interfaces** | Broker HTTP (GET /jobs/next, POST result/fail). Internal: `run_job(command, payload)`; for llm_task, `run_llm_tool_loop()` and `tool_registry.dispatch()`. |
| **Authentication** | Sends `X-Worker-Token`, `X-Worker-Id`, and optionally `X-Worker-Caps` (JSON array) on every broker request. Exits at startup if `WORKER_TOKEN` unset. |
| **Failure handling and idempotency** | `_post_with_retry()` for result/fail: 200 success; 4xx no retry; 5xx and RequestException retry up to 3 times with backoff. Job exception → POST fail. No lease refresh; if job runs longer than lease, broker will requeue on next poll. |
| **Important config/env** | `BROKER_URL`, `WORKER_TOKEN`, `WORKER_ID`, `RUNNER_STATE_DIR`, `POLL_INTERVAL_SEC`, `RESULT_TIMEOUT_SEC`, `RUNNER_REPOS_BASE`, `RUNNER_REPO_ALLOWLIST`, `RUNNER_CMD_TIMEOUT_SECONDS`, `RUNNER_MAX_OUTPUT_BYTES`, `RUNNER_MAX_FILE_BYTES`, `RUNNER_MAX_LINES`, `WORKER_CAPS`, `LLM_CAP`; LLM: `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_TOOL_LOOP_MAX_STEPS`, `LLM_ALLOWED_TOOLS`. |
| **Notable implementation details** | **Leases**: Runner does not refresh; completion or fail must occur before broker requeues. **Repo**: `load_allowlist()` from file; `resolve_repo_path(name)` ensures path is under `RUNNER_REPOS_BASE` (realpath). `_repo_readfile` rejects leading slash and `..`, and checks realpath under repo. Subprocess runs without shell; timeout and output truncation applied. **Tool registry**: `get_tools_schema(allowed_tools)`, `dispatch(name, args, repo_context, runner_bridge)`; bridge provides repo and plan_echo/approve_echo. **LLM loop**: `run_llm_tool_loop` builds messages, calls `chat_with_tools`, appends tool results with truncation for audit; exits on final content or max_steps. |

### C) Discord bot (commands, allowlist, rate limits, redaction)

| Aspect | Details |
|--------|---------|
| **Responsibilities** | Parse user messages; map to commands (ping, capabilities, plan, approve, status, repos, repostat, last, grep, cat, ask/urgo, whoami); create job and wait for result; enforce allowlist and channel; enforce per-user cooldown and max concurrent; redact tokens in all replies. |
| **Key interfaces** | `create_job(command, payload, requires)`, `get_job(job_id)`, `wait_for_job_result(job_id)` (poll with backoff). Broker timeouts: connect 5s, read 15s. |
| **Authentication** | Discord token for API; allowlist from `ALLOWED_USER_ID` and `ALLOWLIST_USER_ID` (at least one required); optional `ALLOWED_CHANNEL_ID` (else DMs only). Bot uses `BOT_TOKEN` for broker. |
| **Failure handling and idempotency** | All user-facing strings passed through `redact()` (BOT_TOKEN, DISCORD_TOKEN replaced with `***`). Truncation for display. On broker errors, reply with redacted error message. |
| **Important config/env** | `DISCORD_TOKEN`, `BOT_TOKEN`, `BROKER_URL`, `ALLOWED_USER_ID`, `ALLOWLIST_USER_ID`, `ALLOWED_CHANNEL_ID`, `JOB_POLL_INTERVAL_SEC`, `JOB_POLL_TIMEOUT_SEC`, `BOT_COOLDOWN_SECONDS`, `BOT_MAX_CONCURRENT`, `INSTANCE_NAME`. |
| **Notable implementation details** | **Allowlist**: Union of single `ALLOWED_USER_ID` and comma/space-separated `ALLOWLIST_USER_ID`. **Rate limits**: Per-user cooldown (`BOT_COOLDOWN_SECONDS`), max concurrent jobs (`BOT_MAX_CONCURRENT`). **Caps routing**: `ask vllm: ...` / `ask jetson: ...` set `requires` to `{"caps":["llm:vllm"]}` or `["llm:jetson"]`. **whoami** returns instance name, bot user ID, broker URL, and allowlist summary; broker URL is not redacted (optional improvement if URL is sensitive). |

### D) Deploy scripts and systemd templates

| Aspect | Details |
|--------|---------|
| **Scripts** | `deploy/onboard_broker.sh` (install broker if needed, write broker.env, optional start); `deploy/onboard_bot.sh <instance>` (install bot instance, write bot.env, optional start); `deploy/onboard_runner.sh` (write runner/runner.env only). Install: `deploy/scripts/install_broker.sh`, `deploy/scripts/install_discord_bot.sh`, `deploy/install_bot_instance.sh`, `deploy/install_runner_systemd.sh`, `deploy/scripts/install_runner.sh` (WSL venv only). Update: `deploy/scripts/update_vps.sh`, `deploy/scripts/update_runner_wsl.sh`, `deploy/scripts/update_runner_jetson.sh`. |
| **Systemd templates** | **Broker**: `deploy/systemd/openclaw-broker.service.template` — User=openclaw, EnvironmentFile=/opt/openclaw-broker/broker.env, WorkingDirectory/ExecStart use REPO_ROOT (substituted by install script). **Bot**: `deploy/systemd/openclaw-discord-bot@.service` — User=openclaw, INSTANCE_NAME=%i, EnvironmentFile=/opt/openclaw-bot-%i/bot.env, WorkingDirectory/ExecStart per instance; hardening (NoNewPrivileges, PrivateTmp, ProtectSystem=strict, etc.). **Runner**: `deploy/systemd/openclaw-runner.service.template` — EnvironmentFile=/opt/openclaw-runner-jetson/runner.env (or overridden), WorkingDirectory/ExecStart REPO_ROOT_PLACEHOLDER replaced by install script; no User in template (runs as root unless set). |
| **WSL vs Jetson** | WSL: no systemd; use `runner/start.sh` and env from `RUNNER_ENV` (e.g. runner/runner.env or /opt/openclaw-runner/runner.env); logs to file (e.g. /var/log/openclaw-runner/runner.log). Jetson: systemd unit installed by install_runner_systemd.sh; runner.env in install dir (e.g. /opt/openclaw-runner-jetson/runner.env). |

---

## 4) Security Review (Threat Model)

### Threat enumeration and assessment

| Threat | Severity | Current mitigations | Suggested improvements |
|--------|----------|---------------------|-------------------------|
| **Discord token compromise** | High | Token in env only; redaction in replies. | Rotate token immediately; restrict bot to DMs or single server. No in-app secret rotation. |
| **Broker BOT_TOKEN compromise** | High | Token in env; broker can be bound to Tailscale IP. | Rotate BOT_TOKEN and update all bot instances; consider broker-side rate limit or job cap to limit abuse. |
| **Broker WORKER_TOKEN compromise** | High | Token in env; workers typically on trusted hosts. | Rotate WORKER_TOKEN and update all runners; bind broker to Tailscale so only tailnet can reach it. |
| **Rogue tailnet device** | Medium | Tailscale ACLs can restrict which nodes reach broker port. | Document Tailscale policy (e.g. allow only specific tags or nodes to reach broker:8000). |
| **Prompt injection via LLM** | Medium | Tools are read-only and allowlisted; repo path checks. | Keep tool set minimal; consider max token or step limits (already max_steps). Monitor for odd tool patterns. |
| **Tool abuse (path traversal, repo escape)** | Medium | resolve_repo_path() and _repo_readfile() enforce allowlist and realpath under base; ".." and leading slash rejected; tests cover these. | No change required; maintain tests. |
| **Denial-of-service (job flooding)** | Medium | Bot: per-user cooldown and max concurrent. | Add broker-side rate limit (e.g. max jobs per minute per BOT_TOKEN) or global queue cap; document as P1. |

### No secrets in git; no token strings in logs

- **Git**: `.gitignore` excludes `*.env`, `.env`, `.env.*`; only `*.env.example` and `!.env.example` are allowed. Env examples contain placeholders only.
- **Logs**: Broker does not log request bodies or tokens. Bot redacts before sending any reply (and replies could be logged by Discord or logging middleware). Runner logs only status codes and exception messages to stderr; no token value is printed. LLM API key is used only inside the runner process and not logged.

### Redaction coverage and remaining leak vectors

- **Redaction**: Bot replaces `BOT_TOKEN` and `DISCORD_TOKEN` with `***` in every user-facing string (replies, errors, status, whoami content except broker URL). Job results from broker are redacted before reply.
- **Remaining vectors**: (1) **whoami** exposes `BROKER_URL` — if that URL is considered sensitive (e.g. internal Tailscale host), consider masking or redacting (P2). (2) Job **result** and **error** are stored in broker DB and returned to anyone with BOT_TOKEN; if an LLM or tool ever returned a secret, it would live in the DB — acceptable for personal/small-team if prompts and tools don’t expose secrets. (3) Runner stderr could in theory capture broker error body (e.g. "bad worker token") but not the token value itself.

---

## 5) Reliability & Correctness Review

### Job lifecycle states and transitions

- **States**: `queued` (on create) → `running` (on claim) → `done` or `failed` (on result or fail).
- **Transitions**: Create sets status to `queued`. Claim sets `started_at`, `lease_until`, `worker_id`, status to `running`, and clears result/error/finished_at. Result sets status to `done`, `finished_at`, result, and clears lease. Fail sets status to `failed`, error, `finished_at`, and clears lease. Requeue (stale running): status back to `queued`, clear started_at, lease_until, worker_id, result, error, finished_at.

### Leases, requeue behavior, and edge cases

- **Lease**: Set at claim to `now + LEASE_SECONDS` (default 60). Runner does not refresh the lease. If the runner does not post result/fail before the next time any worker calls `/jobs/next`, the broker will requeue that job in the same transaction (UPDATE ... WHERE status='running' AND lease_until < now).
- **Double claim**: Prevented by atomic UPDATE ... WHERE id=? AND status='queued' with rowcount check; only one worker can transition a given job to running.
- **Stale running**: Handled by requeue on every `/jobs/next`; the job is then eligible for claim again by any worker with matching caps. If the original worker later posts result/fail, the broker accepts it idempotently (already done/failed) or, if the job was requeued and claimed again, the second worker’s result/fail applies (first worker’s late POST would get 400 for “job not in running state” if job was already done/failed by second worker — current code returns 200 for “already done/failed” so a late POST from first worker would still be 200 and leave state unchanged, which is correct).

### Retry behavior (runner and bot)

- **Runner**: `_post_with_retry` for result and fail POSTs: 3 attempts, backoff [0.5, 1.0, 2.0] seconds on 5xx or RequestException; 4xx is terminal (no retry). Main loop: on RequestException or other exception, log and sleep POLL_INTERVAL_SEC, then continue.
- **Bot**: Single attempt for POST /jobs; GET /jobs/{id} polled with backoff (0.5s → 1s → 2s capped) until job done/failed or JOB_POLL_TIMEOUT_SEC (default 120s). No retry of create.

### Broker correctness under multi-worker polling

- Single broker process; SQLite `BEGIN IMMEDIATE` serializes the requeue+claim transaction. Multiple workers polling concurrently each get a job (or null) without double-claim. Caps filter: first worker whose caps match the oldest queued job gets it; ordering is by created_at, then first matching in the LIMIT 50 window.

### Deadlocks or starvation in cap-based matching

- No deadlock: single transaction, no cross-worker locking. **Starvation**: If worker A has caps that match the oldest job and worker B has different caps, A can repeatedly claim the next job so B’s jobs (e.g. requiring llm:jetson) wait until A’s jobs are drained. This is expected behavior when jobs have different cap requirements; document as known.

### Data integrity (SQLite)

- **Locking**: Connection timeout 10s; BEGIN IMMEDIATE for claim path. Default journal mode (DELETE) is used; WAL not enabled — under heavy write load, consider enabling WAL (P1).
- **DB growth**: No automatic pruning of old jobs; table can grow. Backup and retention policy not documented (P1).

---

## 6) Operations & Deployment Review

### VPS deployment steps and risks

- **Steps**: Clone repo; run `./deploy/onboard_broker.sh` (install broker, broker.env, optional start); run `./deploy/onboard_bot.sh <instance>` per bot (install, bot.env, optional start). See docs/DISCORD_BOT_DEPLOY.md and deploy/env.examples/README.md.
- **Risks**: Broker.env and bot.env are overwritten by onboard scripts (tokens must be re-pasted or set via env if re-running). Firewall: broker port (e.g. 8000) must be allowed (Tailscale and/or firewalld); see docs/VPS_FIREWALL.md.

### WSL runner limitations (no systemd) and how it’s managed

- No systemd on WSL; runner is started manually (e.g. `runner/start.sh` or `python -m runner.runner`). Env from runner.env (e.g. runner/runner.env or RUNNER_ENV). Logs: start.sh can redirect to a file (e.g. /var/log/openclaw-runner/runner.log); log rotation is not scripted in the repo (P2).

### Jetson runner systemd template

- `deploy/install_runner_systemd.sh` creates venv, copies runner.env from runner-jetson.env.example only if file does not exist, substitutes REPO_ROOT and env path in openclaw-runner.service.template, installs to /etc/systemd/system. Service: openclaw-runner; EnvironmentFile points to install-dir runner.env (e.g. /opt/openclaw-runner-jetson/runner.env).

### Logging strategy and log rotation

- Broker: no explicit log file; uvicorn/FastAPI default (stderr). Bot: same. Runner: stderr; when run via start.sh, output can be redirected to a file. WSL file logs: rotation (e.g. logrotate) not provided (P2).

### Firewalld / Tailscale binding assumptions

- Broker listens on BROKER_HOST:BROKER_PORT (e.g. Tailscale IP for tailnet-only). VPS_FIREWALL.md describes opening port 8000 in Tailscale zone and/or cloud security group. Workers need network path to broker (Tailscale or public IP).

### Onboarding scripts: token preservation and idempotency

- **onboard_broker.sh**: Overwrites broker.env each run; does not preserve existing tokens unless provided via env (e.g. non-interactive with WORKER_TOKEN/BOT_TOKEN set). Install step is skipped if broker systemd unit already exists.
- **onboard_bot.sh**: Runs install_bot_instance.sh then overwrites bot.env; tokens must be provided again or via env. Install is idempotent (user, dirs, venv, template).
- **onboard_runner.sh**: Writes runner/runner.env; overwrites. No systemd install.
- **install_runner_systemd.sh**: Does not overwrite existing runner.env; only copies example if file missing. Safe for re-runs.

### How to safely upgrade

- **VPS**: Pull repo; run `bash deploy/scripts/update_vps.sh` (optionally with --no-pull). Restarts broker and all bot instances; schema migration runs on broker startup. No manual DB step if migration is backward-compatible (add column only).
- **Jetson**: Pull; run `bash deploy/scripts/update_runner_jetson.sh`; `sudo systemctl restart openclaw-runner`.
- **WSL**: Pull; run `bash deploy/scripts/update_runner_wsl.sh`; manually restart the runner process (stop start.sh, start again).

---

## 7) Code Quality & Maintainability Review

### Module layout and cohesion

- **broker**: Single module `app.py` (routes, DB, auth, caps). Cohesive.
- **runner**: `runner.py` (poll, run_job, repo commands, bridge for llm_task), `llm_loop.py` (tool loop), `llm_client.py` (single chat_with_tools call), `llm_config.py` (env), `tool_registry.py` (definitions and dispatch). Clear split between job loop, repo, and LLM.
- **discord_bot**: Single `bot.py` (commands, allowlist, broker client, redaction). Acceptable for current size.

### Test coverage by component

- **Broker**: test_broker_protocol.py — health, create, get, claim, requeue, result/fail idempotency, caps filtering, worker_id.
- **Runner**: test_runner_repo.py — allowlist, resolve_repo_path (path traversal, absolute outside base, not allowlisted), repo_readfile validation and path rejection, repo_grep (rg vs git grep). test_llm_runner.py — llm_loop envelope and one-tool flow (mocked). test_llm_task_e2e.py — job create/claim/result with mocked LLM.
- **Bot**: test_bot_helpers.py — truncate, format_repo_envelope, is_allowed, redact. test_bot_whoami.py — format_whoami.
- **Tool registry**: test_tool_registry.py — get_tools_schema, parse_tool_args, dispatch (repo_list, plan_echo, rejections).

No full E2E (Discord API + broker + runner) or integration test that runs real broker + runner + bot in process. CI runs pytest on push/PR (see DEPLOY_AND_UPDATE.md).

### Lint / style consistency

- Not run in this review. Recommend adding a linter (e.g. ruff or flake8) and running in CI (P2).

### Complexity hotspots

- **Broker**: `next_job` — requeue + caps parsing + select + claim in one transaction; caps logic could be extracted for readability (P2 refactor).
- **Runner**: `run_job` — long if/elif for commands; llm_task branch builds bridge and calls run_llm_tool_loop; acceptable.
- **llm_loop**: Tool call handling, message accumulation, truncation; well-scoped.

### Suggested refactors (high ROI only)

- Extract broker caps parsing and matching into a small helper module or functions (optional, P2).
- No large refactors recommended; structure is adequate for current scope.

### Documentation vs code

- **README** (Components table and Runner section): Lists Discord commands including `ask` and `urgo`; runner command list remains as-is (llm_task documented in MULTI_WORKER_LLM_SMOKE). Caps logic is in `bbroker/caps.py` (Sprint 1).

---

## 8) Findings & Recommendations

### P0 — Must fix before proceeding

- **None identified.** No critical security bug (token leak, path escape) or data-corruption bug found. If a P0 is discovered later (e.g. token in logs), fix immediately and re-assess.

### P1 — Should fix soon

- **Addressed in Sprint 1:** SQLite WAL (enabled at broker startup), backup/retention doc ([BROKER_BACKUP_RETENTION.md](BROKER_BACKUP_RETENTION.md)), broker-side job cap (`MAX_QUEUED_JOBS`), whoami URL masking (`WHOAMI_BROKER_URL_MODE`: full / masked / hidden). No remaining P1 items from the original review.

### P2 — Nice-to-have

| Item | Why it matters | Suggested change | Effort | Risk of change |
|------|----------------|-------------------|--------|----------------|
| WSL runner log rotation | Prevents log files from growing unbounded. | Add logrotate config or doc snippet for runner log path. Doc: [WSL_RUNNER_LOGS.md](WSL_RUNNER_LOGS.md). | S | Low |
| Additional E2E coverage | Smoke script (scripts/smoke.py) exists; further coverage optional. | Extend smoke or add integration tests for additional flows. | M | Low |

*Sprint 1 also delivered: lint in CI (ruff), smoke script, caps extraction to broker/caps.py.*

---

## 9) Appendix

### Inventory of env vars

**Broker** (broker.env / broker/app.py):

- BROKER_DB, WORKER_TOKEN, BOT_TOKEN, LEASE_SECONDS (default 60), BROKER_HOST, BROKER_PORT
- MAX_QUEUED_JOBS (optional; unset = no limit; 429 when queued+running at cap)

**Runner** (runner.env / runner/runner.py, llm_config.py):

- BROKER_URL, WORKER_TOKEN, WORKER_ID, RUNNER_STATE_DIR, POLL_INTERVAL_SEC, RESULT_TIMEOUT_SEC  
- RUNNER_REPOS_BASE, RUNNER_REPO_ALLOWLIST, RUNNER_CMD_TIMEOUT_SECONDS, RUNNER_MAX_OUTPUT_BYTES, RUNNER_MAX_FILE_BYTES, RUNNER_MAX_LINES  
- WORKER_CAPS, LLM_CAP  
- LLM_PROVIDER, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_TOOL_LOOP_MAX_STEPS, LLM_ALLOWED_TOOLS  

**Discord bot** (bot.env / discord_bot/bot.py):

- DISCORD_TOKEN, BOT_TOKEN, BROKER_URL  
- ALLOWED_USER_ID, ALLOWLIST_USER_ID, ALLOWED_CHANNEL_ID  
- JOB_POLL_INTERVAL_SEC, JOB_POLL_TIMEOUT_SEC, BOT_COOLDOWN_SECONDS, BOT_MAX_CONCURRENT, INSTANCE_NAME
- WHOAMI_BROKER_URL_MODE (optional; full / masked / hidden; default full)  

### Commands exposed to Discord

- ping, capabilities, plan, approve, status, repos, repostat, last, grep, cat, ask, urgo, whoami  

(Usage hints: status \<job_id\>, repostat \<repo\>, last \<repo\>, grep \<repo\> \<query\> [path], cat \<repo\> \<path\> [start] [end], ask \<prompt\>, urgo \<prompt\>; ask/urgo support vllm: / jetson: prefix for caps routing.)

### Allowed tools for LLM tool calling (tool_registry)

- repo_list, repo_status, repo_last_commit, repo_grep, repo_readfile, plan_echo, approve_echo  

(Controlled by runner env LLM_ALLOWED_TOOLS; default is the set above.)

### Relevant file paths

| Role | Env / state |
|------|-------------|
| Broker | broker.env: e.g. /opt/openclaw-broker/broker.env. DB: BROKER_DB default /var/lib/openclaw-broker/broker.db. |
| Bot (per instance) | bot.env: /opt/openclaw-bot-\<instance\>/bot.env. State: /var/lib/openclaw-bot-\<instance\>/ (optional). |
| Runner (WSL) | runner.env: e.g. runner/runner.env or /opt/openclaw-runner/runner.env (RUNNER_ENV). State: RUNNER_STATE_DIR default /var/lib/openclaw-runner/state; plans under state/plans. |
| Runner (Jetson) | runner.env: e.g. /opt/openclaw-runner-jetson/runner.env. Same state dir semantics. |
| Repo allowlist | RUNNER_REPO_ALLOWLIST (e.g. /etc/openclaw/repos.json) or fallback RUNNER_STATE_DIR/repos.json. |

---

*End of report.*
