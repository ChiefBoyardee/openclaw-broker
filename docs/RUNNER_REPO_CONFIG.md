# Runner repo configuration (Sprint 3+)

The runner can run **read-only** repo commands (`repo_list`, `repo_status`, `repo_last_commit`, `repo_grep`, `repo_readfile`). Repos must be allowlisted; all paths are validated. No writes (no git add/commit/push, no patch/apply).

## Repo allowlist: `repos.json`

The allowlist is a JSON object mapping **short repo names** to **paths** (relative to `RUNNER_REPOS_BASE` or absolute).

### Location

- **Primary:** `RUNNER_REPO_ALLOWLIST` (default `/etc/openclaw/repos.json`).
- **Fallback:** If the primary path is missing or unreadable, the runner uses `RUNNER_STATE_DIR/repos.json`.

When running as root, prefer `/etc/openclaw/repos.json`. Otherwise use the state-dir fallback and ensure the file exists and is readable.

### Format

Keys are short names (e.g. `knucklebot`, `urgo_ai`). Values are either:

- **Relative path** — resolved as `join(RUNNER_REPOS_BASE, value)`.
- **Absolute path** — allowed only if its realpath is inside `RUNNER_REPOS_BASE` (or equals it).

Each repo path must exist and be a git repo (have a `.git` directory). Commands that use a repo name will fail with "repo not allowlisted" if the name is not in the allowlist, or "not a git repo" if the path has no `.git`.

### Example

```json
{
  "knucklebot": "knucklebot",
  "urgo_ai": "urgo/urgo_ai",
  "openclaw": "/home/jay/src/openclaw-broker"
}
```

With `RUNNER_REPOS_BASE=/home/jay/src`:

- `knucklebot` → `/home/jay/src/knucklebot`
- `urgo_ai` → `/home/jay/src/urgo/urgo_ai`
- `openclaw` → `/home/jay/src/openclaw-broker` (absolute but under base)

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RUNNER_REPOS_BASE` | `/home/jay/src` | Base directory for repos; relative allowlist entries are joined with this. |
| `RUNNER_REPO_ALLOWLIST` | `/etc/openclaw/repos.json` | Path to allowlist JSON. Fallback: `RUNNER_STATE_DIR/repos.json` if missing/unreadable. |
| `RUNNER_CMD_TIMEOUT_SECONDS` | `15` | Timeout for git/rg subprocesses. |
| `RUNNER_MAX_OUTPUT_BYTES` | `20000` | Max bytes for command output (e.g. status porcelain, grep matches). |
| `RUNNER_MAX_FILE_BYTES` | `200000` | Max file size for `repo_readfile`. |
| `RUNNER_MAX_LINES` | `400` | Max line range / lines returned for `repo_readfile`. |

## Runner commands (read-only)

| Command | Payload | Description |
|---------|---------|-------------|
| `repo_list` | `""` | List allowlisted repos that exist and are git repos. |
| `repo_status` | `{"repo":"<name>"}` | Branch, dirty flag, and `git status --porcelain=v1` output. |
| `repo_last_commit` | `{"repo":"<name>"}` | Last commit hash, author, date, subject. |
| `repo_grep` | `{"repo":"<name>","query":"<string>","path":"<optional>"}` | Search with `rg` (preferred) or `git grep`; output capped. |
| `repo_readfile` | `{"repo":"<name>","path":"<file>","start":1,"end":200}` | Read file line range; path must be relative, no `..`; size and line count capped. |

Results are returned as a JSON envelope (see runner code). The Discord bot maps DM commands to these: `repos`, `repostat <repo>`, `last <repo>`, `grep <repo> <query> [path]`, `cat <repo> <path> [start] [end]`.

## Safety

- **Read-only:** No git write operations.
- **No shell:** All subprocess calls use `argv` list and `shell=False`.
- **Allowlist:** Only allowlisted repo names; paths must stay under `RUNNER_REPOS_BASE` for absolute entries.
- **Path traversal:** `repo_readfile` rejects paths with `..` or leading `/`; resolved path must be under repo root.
- **Timeouts and caps:** Commands use `RUNNER_CMD_TIMEOUT_SECONDS`; output and file size/line limits are enforced.
