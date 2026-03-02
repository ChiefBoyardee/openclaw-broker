# Security observability

Structured audit events and anomaly hints for OpenClaw.

---

## Audit events

The broker and runner emit structured log lines (to stderr). No secrets are logged.

### Broker events

| Event | When |
|-------|------|
| `job_created` | Job successfully created |
| `job_rejected` | Create rejected (rate_limit, queue_cap, body_too_large, invalid_command, payload_too_large, requires_too_large) |
| `job_claimed` | Worker claimed a job |
| `job_done` | Worker posted result |
| `job_failed` | Worker posted fail |

### Runner events

| Event | When |
|-------|------|
| `llm_task_policy_refused` | LLM tool loop short-circuited after repeated policy violations |

---

## Anomaly hints

Review logs when you see:

- **Spikes in 429s** — Rate limit or queue cap hit; possible abuse or misconfiguration.
- **Repeated `llm_task_policy_refused`** — Prompt injection or policy-violation attempts.
- **Sudden job create rate increase** — Review allowlist and broker binding; ensure broker is not exposed publicly.

---

## See also

- [TOKEN_ROTATION_AND_INCIDENT_RESPONSE.md](TOKEN_ROTATION_AND_INCIDENT_RESPONSE.md)
- [BROKER_BACKUP_RETENTION.md](BROKER_BACKUP_RETENTION.md)
