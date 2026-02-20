#!/usr/bin/env bash
# Update OpenClaw Runner on WSL: pull repo and refresh venv. You must restart the runner process yourself.
# Run from repo root on WSL. Use --no-pull to skip git pull.
# Usage: ./deploy/scripts/update_runner_wsl.sh [--no-pull]
# After running: stop the current runner (Ctrl+C or kill), then start again with runner/start.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
NO_PULL=""
for arg in "$@"; do
  [[ "$arg" == "--no-pull" ]] && NO_PULL=1
done

echo "[update_runner_wsl] REPO_ROOT=$REPO_ROOT NO_PULL=$NO_PULL"
cd "$REPO_ROOT"

if [[ -z "$NO_PULL" ]]; then
  git pull
  echo "[update_runner_wsl] git pull done"
fi

VENV="${REPO_ROOT}/.venv-runner"
if [[ -d "$VENV" ]]; then
  "$VENV/bin/pip" install -r "$REPO_ROOT/requirements.txt" -q
  echo "[update_runner_wsl] venv updated"
fi

echo "[update_runner_wsl] done. Restart the runner (e.g. stop current process, then run runner/start.sh)"
