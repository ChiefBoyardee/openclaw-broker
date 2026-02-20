# Multi-Worker LLM Smoke Runbook (Sprint 5)

This runbook brings the `llm_task` system online with two workers (WSL vLLM + Jetson Orin): caps/routing, LLM endpoint checks, repo allowlists, runner config, and Discord smoke tests.

---

## 1. Prerequisites

- **VPS:** Broker and Discord bot are running via systemd and reachable (e.g. over Tailscale).
- **Workers:** WSL and Jetson have network reachability to the broker URL (e.g. `http://<VPS_TAILSCALE_IP>:8443`).
- **LLM endpoints:** Each worker has a local OpenAI-compatible endpoint (vLLM or other) that you will configure below.

---

## 2. Capability (caps) scheme and routing

### Canonical caps

| Worker   | Caps (comma-separated)     |
|----------|----------------------------|
| WSL      | `repo_tools`, `llm:vllm`   |
| Jetson   | `repo_tools`, `llm:jetson` |

- **`repo_tools`:** Runner can run repo commands (repos, grep, readfile, etc.). The runner adds this automatically if not set.
- **`llm:vllm` / `llm:jetson`:** Identifies which LLM backend this worker uses; the broker uses this to route jobs that request a specific cap.

### Setting caps per worker

In each runner’s env file set:

- **WSL:** `WORKER_CAPS=repo_tools,llm:vllm`
- **Jetson:** `WORKER_CAPS=repo_tools,llm:jetson`

The broker accepts `X-Worker-Caps` as either a **comma-separated list** or a **JSON array** (e.g. `["llm:vllm","repo_tools"]`). The runner sends a JSON array by default.

### Routing rules

- **Default (no routing):** `ask <text>` or `urgo <text>` — job has no `requires`; **either** worker can claim it (FIFO).
- **Force vLLM:** `ask vllm: <text>` or `ask vllm <text>` — job has `requires {"caps":["llm:vllm"]}`; only a worker with `llm:vllm` can claim it.
- **Force Jetson:** `ask jetson: <text>` or `ask jetson <text>` — job has `requires {"caps":["llm:jetson"]}`; only a worker with `llm:jetson` can claim it.

The routing prefix (`vllm:`, `vllm `, `jetson:`, `jetson `) is stripped before the prompt is sent to the LLM.

---

## 3. Env snippets (WSL vs Jetson)

### WSL runner (vLLM)

Start from [deploy/env.examples/runner-wsl.env.example](../deploy/env.examples/runner-wsl.env.example). Copy to e.g. `/opt/openclaw-runner/runner.env` or `runner/runner.env` and set:

```bash
# Broker (VPS over Tailscale)
BROKER_URL=http://<VPS_TAILSCALE_IP>:8443
WORKER_TOKEN=<from broker onboarding>

# Identity and caps
WORKER_ID=wsl-vllm
WORKER_CAPS=llm:vllm,repo_tools

# LLM (OpenAI-compatible vLLM on WSL)
LLM_PROVIDER=openai_compat
LLM_BASE_URL=http://127.0.0.1:<port>/v1
LLM_API_KEY=
LLM_MODEL=<your-vllm-model-name>
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=4096
LLM_TOOL_LOOP_MAX_STEPS=6
# LLM_ALLOWED_TOOLS=repo_list,repo_status,repo_last_commit,repo_grep,repo_readfile,plan_echo,approve_echo  # optional; default is all

# Repo
RUNNER_REPOS_BASE=/home/jay/src
RUNNER_REPO_ALLOWLIST=/etc/openclaw/repos.json
# Or fallback: leave unset to use RUNNER_STATE_DIR/repos.json

# Optional
# POLL_INTERVAL_SEC=10
# RESULT_TIMEOUT_SEC=300
```

Run the runner: from repo root, `runner/start.sh` (or set `RUNNER_ENV` if the file is elsewhere). Logs go to `/var/log/openclaw-runner/runner.log`.

### Jetson runner

Start from [deploy/env.examples/runner-jetson.env.example](../deploy/env.examples/runner-jetson.env.example). Install the systemd service from repo root on the Jetson:

```bash
./deploy/install_runner_systemd.sh
```

Edit the env file (default `/opt/openclaw-runner-jetson/runner.env`):

```bash
BROKER_URL=http://<VPS_TAILSCALE_IP>:8443
WORKER_TOKEN=<from broker onboarding>

WORKER_ID=jetson-llm
WORKER_CAPS=llm:jetson,repo_tools

LLM_PROVIDER=openai_compat
LLM_BASE_URL=http://127.0.0.1:<port>/v1
LLM_API_KEY=
LLM_MODEL=<your-jetson-model-name>
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=2048
LLM_TOOL_LOOP_MAX_STEPS=6

RUNNER_REPOS_BASE=/home/nvidia/src
RUNNER_REPO_ALLOWLIST=/etc/openclaw/repos.json
```

Then:

```bash
sudo systemctl enable openclaw-runner
sudo systemctl start openclaw-runner
```

---

## 4. LLM endpoint sanity (OpenAI-compat)

Before relying on `llm_task`, confirm each endpoint responds.

- **Base URL:** Use `http://127.0.0.1:<port>/v1` (no trailing slash is fine; the client appends paths).
- **Model name:** Set `LLM_MODEL` to the exact model name returned by the server.
- **API key:** Usually empty for local vLLM/Jetson; set `LLM_API_KEY=` or omit.

### Curl checks

```bash
# List models
curl -s http://127.0.0.1:<port>/v1/models | head

# Minimal chat completion (adjust model name)
curl -s http://127.0.0.1:<port>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<model-name>","messages":[{"role":"user","content":"Hi"}],"max_tokens":10}'
```

Expect JSON from `/v1/models` and a 200 with content from the completion call. If the Jetson endpoint uses a different model string, document it in the runbook after verification.

### Optional dry run

From a host with the runner and env configured, trigger one `ask` from Discord (or a local job) to confirm the runner can complete a trivial `llm_task`.

---

## 5. Repo allowlist

Both workers need an allowlist so `repos`, `grep`, and `repo_readfile` work.

### Where to create the allowlist

- **WSL:** `/etc/openclaw/repos.json` (if runner runs as root) or `${RUNNER_STATE_DIR}/repos.json` (e.g. `/var/lib/openclaw-runner/state/repos.json`). Set `RUNNER_REPO_ALLOWLIST` to the chosen path.
- **Jetson:** Prefer `/etc/openclaw/repos.json`; set `RUNNER_REPO_ALLOWLIST=/etc/openclaw/repos.json`.

### Minimum content

Ensure `RUNNER_REPOS_BASE` contains the repo directory, then create the allowlist with at least:

```json
{"openclaw-broker": "openclaw-broker"}
```

If the repo is at `RUNNER_REPOS_BASE/openclaw-broker`, that entry maps the logical name `openclaw-broker` to the path `openclaw-broker` under the base. Use a full path in the value if you prefer (must still be under `RUNNER_REPOS_BASE`).

### Acceptance

- From Discord: `repos` returns `openclaw-broker`.
- From Discord: `grep openclaw-broker LEASE_SECONDS` returns matches.

---

## 6. Runner bring-up checklist

1. **WSL:** Copy env from runner-wsl.env.example, set BROKER_URL, WORKER_TOKEN, WORKER_ID=wsl-vllm, WORKER_CAPS=llm:vllm,repo_tools, LLM_*, repo vars. Run `runner/start.sh`; confirm logs in `/var/log/openclaw-runner/runner.log`.
2. **Jetson:** Run `./deploy/install_runner_systemd.sh`, edit `runner.env` in install dir, set WORKER_ID=jetson-llm, WORKER_CAPS=llm:jetson,repo_tools, LLM_*. Enable and start `openclaw-runner`.
3. **Broker logs:** Confirm polling from both worker IDs (e.g. logs showing `/jobs/next` and worker_id).
4. **Discord:** `capabilities` should list `llm_task` and the LLM caps.

---

## 7. Discord smoke commands (non-LLM first)

Run from Discord DM (or allowed channel):

| Command                     | Expected |
|----------------------------|----------|
| `ping hello`               | Success; pong. |
| `capabilities`             | JSON with worker_id, capabilities (including llm_task, llm:vllm or llm:jetson), version. |
| `repos`                    | List including openclaw-broker. |
| `repostat openclaw-broker` | Repo status. |

All should return without “Still running…”. Check broker/bot logs for no token strings and no repeated requeues.

---

## 8. Multi-worker LLM smoke (routing + tool use)

Run from Discord:

| Command | Expected |
|--------|----------|
| `ask What repos are configured on this worker?` | Either worker claims; response mentions repos (via tool call) or answers. |
| `ask vllm: Search for "LEASE_SECONDS" and summarize what it does` | Only WSL (llm:vllm) claims; tool calls (e.g. repo_grep/readfile) and summary. |
| `ask jetson: Search for "WORKER_CAPS" and summarize how it is used` | Only Jetson (llm:jetson) claims. |
| `ask vllm: Read ../../etc/passwd` | Job fails with a safe error (path must be relative and not contain .. or path outside repo); bot shows redacted error, no secrets. |

Confirm: routing matches `requires`; tool calls obey allowlists; failures post via `/fail` and display redacted; no job thrash (jobs stay queued until a compatible worker is up).

---

## 9. Observability and failure handling

### Where to look

- **Broker:** `/jobs/next`, `/result`, `/fail` in logs; job status and worker_id.
- **Bot:** Journald (or console); ensure no token strings in replies (BOT_TOKEN and DISCORD_TOKEN are redacted in user-facing output).
- **Runners:** WSL: `/var/log/openclaw-runner/runner.log`; Jetson: `journalctl -u openclaw-runner -f`. Tool calls and results appear in runner logs.

### Controlled failure test

1. Stop Jetson runner: `sudo systemctl stop openclaw-runner`.
2. Send `ask jetson: What is 2+2?`
3. Expect: job stays queued; bot eventually replies “Still running… job id …”.
4. Restart Jetson: `sudo systemctl start openclaw-runner`.
5. Expect: same job is claimed by Jetson and completes (or a new ask completes). Lease/requeue should not lose the job.

---

## 10. Troubleshooting table

| Symptom | Likely cause | Where to look |
|--------|----------------|----------------|
| Job never completes; “Still running…” | No runner connected, or no runner with matching caps | Broker: jobs stuck queued; runner logs: both workers polling? |
| Connection refused to broker | Broker not listening on that host/port | VPS: `systemctl status openclaw-broker`, `curl -s http://127.0.0.1:8000/health` (or your BROKER_URL) |
| Token strings in bot output | Redaction bug | bot code: `redact()` and BOT_TOKEN/DISCORD_TOKEN |
| Wrong worker claims job | requires/caps mismatch | Broker: job `requires`; runner X-Worker-Caps; broker routing logic |
| LLM task fails “LLM not configured” | LLM_BASE_URL or LLM_MODEL unset/wrong | Runner env: LLM_BASE_URL must include /v1; LLM_MODEL set |
| repos empty or grep fails | Allowlist missing or wrong path | RUNNER_REPO_ALLOWLIST and RUNNER_REPOS_BASE; allowlist file exists and JSON valid |
| Path traversal attempt returns error | Expected; runner blocks .. and path outside repo | Safe error in bot reply; no file content leaked |

---

## 11. Manager “must not miss” checks

- **LLM_BASE_URL** includes `/v1` (e.g. `http://127.0.0.1:8000/v1`) if the OpenAI client expects it.
- **Caps format:** Broker accepts comma-separated or JSON array for `X-Worker-Caps`; ensure runner and broker use a consistent format (runner sends JSON array).
- **BOT_TOKEN** (broker auth) ≠ **DISCORD_TOKEN**; both must be set and redacted in user-facing bot output.
- **Workers must not claim jobs they can’t satisfy:** Broker only assigns a job to a worker whose caps include the job’s `requires`; verify with forced routing tests.

---

## Report-back after completion

- Paste or link this runbook (or [docs/MULTI_WORKER_LLM_SMOKE.md](MULTI_WORKER_LLM_SMOKE.md)).
- Provide one screenshot or log snippet showing: WSL worker claimed an `llm:vllm` job; Jetson worker claimed an `llm:jetson` job.
- Confirm whether the Jetson endpoint is truly OpenAI-compatible and which model string was used.
