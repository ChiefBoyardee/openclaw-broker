#!/usr/bin/env bash
# OpenClaw Runner — start script for WSL (no systemd).
# Logs to /var/log/openclaw-runner/runner.log
# Reads env from /opt/openclaw-runner/runner.env

set -e
RUNNER_ENV="${RUNNER_ENV:-/opt/openclaw-runner/runner.env}"
LOG_DIR="/var/log/openclaw-runner"
LOG_FILE="${LOG_DIR}/runner.log"

if [[ ! -f "$RUNNER_ENV" ]]; then
  echo "ERROR: env file not found: $RUNNER_ENV" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"
# Resolve repo root (parent of runner/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

set -a
source "$RUNNER_ENV"
set +a

PYTHON="python"
if [[ -x "$REPO_ROOT/.venv-runner/bin/python" ]]; then
  PYTHON="$REPO_ROOT/.venv-runner/bin/python"
fi
exec "$PYTHON" -u runner/runner.py >> "$LOG_FILE" 2>&1
