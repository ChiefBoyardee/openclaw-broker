# Sprint 1 — Ops + Hardening (PR description)

Paste the sections below into the GitHub PR description.

---

## Summary (what/why)

- Enable SQLite WAL and synchronous=NORMAL at broker startup to reduce lock contention.
- Add optional broker job cap (`MAX_QUEUED_JOBS`); when set, reject new job creation with 429 when queued+running >= cap.
- Add optional whoami broker URL masking (`WHOAMI_BROKER_URL_MODE`: full | masked | hidden).
- Add backup/retention doc (BROKER_BACKUP_RETENTION.md), release notes, and ops checklist.

---

## Risk assessment

- **WAL:** Low risk; standard SQLite setting; rollback by reverting broker startup change.
- **Job cap:** Opt-in; unset = no limit; 429 response is safe (no token/traceback).
- **whoami:** Opt-in; default remains full URL; masked/hidden reduce URL exposure only when configured.

---

## Rollout steps

- Deploy code as usual (e.g. pull + `deploy/scripts/update_vps.sh` for VPS).
- **Env (optional):** set `MAX_QUEUED_JOBS` (e.g. 100) in broker env if you want a cap; set `WHOAMI_BROKER_URL_MODE=masked` or `hidden` in bot env if you want to hide broker URL in whoami.
- **Defaults:** no new required env; WAL enabled automatically; cap and whoami mode default to "no limit" and "full".

---

## Validation steps

- Run `pytest tests/ -v --tb=short`.
- Run `python scripts/smoke.py` (exit 0, "Smoke OK").
- Optionally: test 429 when at cap; test whoami with masked/hidden.

---

## Rollback steps

- **Job cap:** Unset `MAX_QUEUED_JOBS`.
- **whoami:** Set `WHOAMI_BROKER_URL_MODE=full` or remove.
- **WAL:** Revert broker commit that adds `enable_wal()` (only if you must return to default journal mode).
