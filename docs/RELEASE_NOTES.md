# Release / rollout notes

Short notes for deployers when upgrading. See [DEPLOY_AND_UPDATE.md](DEPLOY_AND_UPDATE.md) for how to update.

---

## Sprint 1 (ops + hardening)

### New env vars (optional; safe defaults)

| Component | Variable | Default | Description |
|-----------|----------|---------|-------------|
| Broker | `MAX_QUEUED_JOBS` | unset or 0 (no limit) | Max queued + running jobs; `POST /jobs` returns 429 when at cap. Unset or `0` = no limit. |
| Bot | `WHOAMI_BROKER_URL_MODE` | `full` | whoami broker URL: `full`, `masked` (scheme+host only), or `hidden` (shows "(hidden)"). |

### Behavior changes

- **Broker:** SQLite runs in **WAL** mode at startup (reduces lock contention). No config change needed.
- **Broker:** If you set `MAX_QUEUED_JOBS`, clients that create jobs when the queue is at cap will receive **429** with body `{"detail": "job queue limit reached"}`. No token or stack trace in the response.
- **Bot:** whoami shows full broker URL by default; set `WHOAMI_BROKER_URL_MODE=masked` or `hidden` to avoid exposing the URL.

### Rollback

- **WAL:** Revert the broker commit that enables WAL if you need default journal mode (unusual).
- **Job cap:** Unset `MAX_QUEUED_JOBS` to remove the limit.
- **whoami:** Set `WHOAMI_BROKER_URL_MODE=full` or remove the var to show full URL again.

### Validation checklist

1. Run `pytest tests/ -v --tb=short` — all pass.
2. Run `python scripts/smoke.py` — exit 0 and "Smoke OK".
3. Optional: set `MAX_QUEUED_JOBS=2`, create two jobs, third create returns 429 with body containing "job queue limit reached" and no token.
4. Optional: set `WHOAMI_BROKER_URL_MODE=masked` or `hidden`, send whoami in DM, confirm output matches mode (no path for masked, "(hidden)" for hidden).

See also [BROKER_BACKUP_RETENTION.md](BROKER_BACKUP_RETENTION.md) (Ops checklist) and [DISCORD_BOT_SMOKE.md](DISCORD_BOT_SMOKE.md).

---

## Sprint 3 (security hardening)

### New env vars (optional; safe defaults)

| Component | Variable | Default | Description |
|-----------|----------|---------|-------------|
| Broker | `RATE_LIMIT_JOBS_PER_MIN` | unset (no limit) | Max job creates per minute per BOT_TOKEN. 429 when exceeded. |
| Broker | `MAX_REQUEST_BODY_BYTES` | 524288 (512KB) | Reject request body larger than this (413). |
| Broker | `BROKER_BIND_PUBLIC` | unset | Set to `1` to suppress warning when `BROKER_HOST=0.0.0` |
| Runner | `LLM_MAX_OUTPUT_BYTES` | 65536 (64KB) | Max bytes per tool result before truncation. |
| Runner | `LLM_MAX_TOOL_ARG_BYTES` | 4096 (4KB) | Reject tool call args larger than this. |
| Runner | `RUNNER_REDACT_OUTPUT` | 1 | Scrub credential patterns from results/errors before storing in broker. Set to `0` to disable. |

### Behavior changes

- **Broker:** Command allowlist enforced; unknown commands return 400. Payload max 256KB; requires max 2KB. Over-sized body returns 413.
- **Broker:** Sliding-window rate limit per BOT_TOKEN when `RATE_LIMIT_JOBS_PER_MIN` is set. 429 body: `{"detail": "rate limit exceeded"}`.
- **Broker:** Startup warning when `BROKER_HOST=0.0.0` unless `BROKER_BIND_PUBLIC=1`.
- **Bot:** Expanded redaction (sk-, ghp_, xoxb-, AIza, PEM keys) + instruction-leak warning banner.
- **Runner:** LLM system prompt hardened; URL-like tool args rejected; policy refusal after 3 consecutive errors.
- **Runner:** Credential scrubbing on results/errors before posting to broker (configurable).
- **CI:** `pip-audit` job added; dependencies pinned in requirements.txt.

### New docs and scripts

- [TOKEN_ROTATION_AND_INCIDENT_RESPONSE.md](TOKEN_ROTATION_AND_INCIDENT_RESPONSE.md) — token rotation, post-incident checklist, file permissions.
- [SECURITY_CADENCE.md](SECURITY_CADENCE.md) — monthly audit cadence, critical CVE fast-track.
- [SECURITY_OBSERVABILITY.md](SECURITY_OBSERVABILITY.md) — audit events, anomaly hints.
- `scripts/prune_jobs.py` — prune old done/failed jobs (`--dry-run`, `--days`, `--yes`). Run backup first.

### Rollback

- Unset `RATE_LIMIT_JOBS_PER_MIN` to remove rate limit.
- Set `MAX_REQUEST_BODY_BYTES` large or unset (default 512KB).
- Set `RUNNER_REDACT_OUTPUT=0` to disable runner-side redaction.
