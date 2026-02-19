# Runner repo configuration (Sprint 3+)

When implementing `repo.*` commands (repo.list, repo.status, repo.search, etc.), use these defaults unless you override them.

## Search tool

- **Default:** Use **ripgrep** (`rg`) for search (e.g. `repo.search`).
- **Fallback:** If `rg` is not installed or not on PATH, use `git grep`.

## Repo paths (WSL)

- **Default recommendation:** Repos live under `/home/jay/src/...` (or your WSL user’s home, e.g. `/home/<user>/src`).
- Override via env (e.g. `RUNNER_REPOS_BASE=/home/jay/src`) when implementing.

## Repo allowlist

- **Option A (simple):** `RUNNER_STATE_DIR/repos.json` — same state dir as plan files; runner process must be able to read/write it.
- **Option B (more secure):** `/etc/openclaw/repos.json` — use when the runner runs as root or a dedicated user with read access; keeps allowlist outside writable state.
- **Default:** Use **`/etc/openclaw/repos.json`** if the runner is run as root anyway; otherwise `RUNNER_STATE_DIR/repos.json` is fine.

These are design defaults only; no code in the repo implements them until Sprint 3.
