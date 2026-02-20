#!/usr/bin/env bash
# Update OpenClaw Runner on Jetson (or any systemd host): pull repo, refresh venv, restart service.
# Run from repo root on the Jetson. Use --no-pull to skip git pull.
# Usage: ./deploy/scripts/update_runner_jetson.sh [--no-pull]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
NO_PULL=""
for arg in "$@"; do
  [[ "$arg" == "--no-pull" ]] && NO_PULL=1
done

echo "[update_runner_jetson] REPO_ROOT=$REPO_ROOT NO_PULL=$NO_PULL"
cd "$REPO_ROOT"

if [[ -z "$NO_PULL" ]]; then
  git pull
  echo "[update_runner_jetson] git pull done"
fi

if [[ -d "$REPO_ROOT/.venv-runner" ]]; then
  "$REPO_ROOT/.venv-runner/bin/pip" install -r "$REPO_ROOT/requirements.txt" -q
  echo "[update_runner_jetson] venv updated"
fi

sudo systemctl restart openclaw-runner
echo "[update_runner_jetson] openclaw-runner restarted; done"
