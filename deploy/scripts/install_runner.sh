#!/usr/bin/env bash
# Install OpenClaw Runner (e.g. on WSL): venv, requirements, start.sh + env template.
# Does NOT start the runner. No secrets in this script; use runner.env (from runner.env.example).

set -e
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
RUNNER_ENV_DIR="${RUNNER_ENV_DIR:-/opt/openclaw-runner}"
RUNNER_LOG_DIR="${RUNNER_LOG_DIR:-/var/log/openclaw-runner}"
VENV_NAME=".venv-runner"

echo "[install_runner] REPO_ROOT=$REPO_ROOT"

if [[ ! -d "$REPO_ROOT/$VENV_NAME" ]]; then
  python3 -m venv "$REPO_ROOT/$VENV_NAME"
  echo "[install_runner] venv created at $REPO_ROOT/$VENV_NAME"
fi
"$REPO_ROOT/$VENV_NAME/bin/pip" install -r "$REPO_ROOT/requirements.txt"
echo "[install_runner] dependencies installed"

# Suggest creating env and log dirs (may need sudo on WSL)
echo ""
echo "Next steps:"
echo "  1. Create env dir and file: sudo mkdir -p $RUNNER_ENV_DIR && sudo cp $REPO_ROOT/runner/runner.env.example $RUNNER_ENV_DIR/runner.env && sudo $EDITOR $RUNNER_ENV_DIR/runner.env"
echo "  2. Set BROKER_URL, WORKER_TOKEN (same as broker)"
echo "  3. Create log dir: sudo mkdir -p $RUNNER_LOG_DIR (optional; start.sh will create if writable)"
echo "  4. Run: cd $REPO_ROOT && RUNNER_ENV=$RUNNER_ENV_DIR/runner.env $REPO_ROOT/runner/start.sh"
echo "     Or run in background: nohup bash $REPO_ROOT/runner/start.sh &"
echo "  (start.sh logs to $RUNNER_LOG_DIR/runner.log by default)"
