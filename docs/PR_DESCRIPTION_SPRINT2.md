# Sprint 2 — Reliability + Maintainability (PR description)

Paste the sections below into the GitHub PR description.

---

## Summary (what/why)

- **WSL runner log rotation:** Document log path (`/var/log/openclaw-runner/runner.log`), logrotate sample config, and install/apply/dry-run steps in [WSL_RUNNER_LOGS.md](WSL_RUNNER_LOGS.md).
- **Smoke script:** Minimal end-to-end check of broker + simulated worker/bot; in-process broker with temp DB, no Discord or external services. Hardened with clear assertion messages and fail-path robustness (step 3 uses job id from claim).
- **Ruff lint in CI:** New `lint` job runs `ruff check broker discord_bot runner tests scripts` with minimal config (E/F, line-length 120, per-file ignores for tests/scripts). Test job unchanged; optional pip cache added for faster runs.
- **Caps extraction:** Worker/job caps parsing and matching moved to `broker/caps.py` with unit tests; broker uses the caps module for all parsing/matching. Behavior-preserving refactor.

---

## How to run smoke locally

From repo root:

```bash
python scripts/smoke.py
```

- **Success:** exit 0 and a single line `Smoke OK`.
- **Failure:** exit 1 and `Smoke failed: <reason>` printed to stderr.
- No env required (default tokens); optional `WORKER_TOKEN` / `BOT_TOKEN` if you want to override.

---

## CI changes

- **New `lint` job:** Runs `ruff check broker discord_bot runner tests scripts` on Python 3.12. No optional services.
- **Test job:** Unchanged (pytest on 3.11 and 3.12). Optional pip cache added (key: `pip-${{ runner.os }}-${{ hashFiles('requirements.txt') }}`) to speed repeated runs.
- Lint and tests do not require Discord or a live broker.

---

## Risk / rollback

- **Caps refactor:** Same logic as before, moved to a module; behavior-preserving. Rollback: revert `broker/caps.py` and restore in-app caps helpers in `broker/app.py`.
- **CI:** Revert the lint job (or the whole workflow) in `.github/workflows/ci.yml` if needed; tests remain valid without lint.
