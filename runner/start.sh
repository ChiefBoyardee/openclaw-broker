#!/usr/bin/env bash
# OpenClaw Runner — start script for WSL (no systemd).
# Logs to RUNNER_LOG_DIR/runner.log (defaults to /var/log/openclaw-runner when writable).
# Reads env from RUNNER_ENV (defaults to runner/runner.env in the repo).
# Consider logrotate for LOG_FILE (e.g. /etc/logrotate.d/openclaw-runner) to avoid unbounded growth.

set -e
# Resolve repo root (parent of runner/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_RUNNER_ENV="$REPO_ROOT/runner/runner.env"

if [[ -z "${RUNNER_ENV:-}" ]]; then
  if [[ -f "$DEFAULT_RUNNER_ENV" ]]; then
    RUNNER_ENV="$DEFAULT_RUNNER_ENV"
  else
    RUNNER_ENV="/opt/openclaw-runner/runner.env"
  fi
fi

if [[ ! -f "$RUNNER_ENV" ]]; then
  echo "ERROR: env file not found: $RUNNER_ENV" >&2
  echo "Expected the repo-local default at $DEFAULT_RUNNER_ENV or set RUNNER_ENV=/path/to/runner.env." >&2
  exit 1
fi

cd "$REPO_ROOT"

set -a
source "$RUNNER_ENV"
set +a

LOG_DIR="${RUNNER_LOG_DIR:-}"
if [[ -z "$LOG_DIR" ]]; then
  if mkdir -p /var/log/openclaw-runner 2>/dev/null; then
    LOG_DIR="/var/log/openclaw-runner"
  else
    LOG_DIR="${HOME:-$REPO_ROOT}/.local/state/openclaw-runner"
    mkdir -p "$LOG_DIR"
  fi
else
  mkdir -p "$LOG_DIR"
fi
LOG_FILE="${LOG_FILE:-$LOG_DIR/runner.log}"

PYTHON="python"
if [[ -x "$REPO_ROOT/.venv-runner/bin/python" ]]; then
  PYTHON="$REPO_ROOT/.venv-runner/bin/python"
fi
exec "$PYTHON" -u runner/runner.py >> "$LOG_FILE" 2>&1
