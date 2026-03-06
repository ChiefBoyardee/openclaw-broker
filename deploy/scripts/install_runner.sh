#!/usr/bin/env bash
# Install OpenClaw Runner (e.g. on WSL): venv, requirements, start.sh + env template.
# Does NOT start the runner. No secrets in this script; use runner.env (from runner.env.example).

set -e
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
RUNNER_ENV_DIR="${RUNNER_ENV_DIR:-$REPO_ROOT/runner}"
RUNNER_LOG_DIR="${RUNNER_LOG_DIR:-/var/log/openclaw-runner}"
VENV_NAME=".venv-runner"
RUNNER_ENV_FILE="$RUNNER_ENV_DIR/runner.env"

echo "[install_runner] REPO_ROOT=$REPO_ROOT"

if [[ ! -d "$REPO_ROOT/$VENV_NAME" ]]; then
  python3 -m venv "$REPO_ROOT/$VENV_NAME"
  echo "[install_runner] venv created at $REPO_ROOT/$VENV_NAME"
fi
"$REPO_ROOT/$VENV_NAME/bin/pip" install -r "$REPO_ROOT/requirements.txt"
echo "[install_runner] dependencies installed"

# Suggest creating env and log dirs (RUNNER_ENV_DIR can be overridden for system-wide installs)
echo ""
echo "Next steps:"
echo "  1. Create env file: mkdir -p $RUNNER_ENV_DIR && cp $REPO_ROOT/runner/runner.env.example $RUNNER_ENV_FILE && ${EDITOR:-nano} $RUNNER_ENV_FILE"
echo "  2. Set BROKER_URL, WORKER_TOKEN (same as broker)"
echo "  3. Create log dir if you want a custom location: mkdir -p $RUNNER_LOG_DIR"
echo "     Or set RUNNER_LOG_DIR in $RUNNER_ENV_FILE and start.sh will create it if writable"
echo "  4. Run onboarding instead of editing by hand: cd $REPO_ROOT && bash deploy/onboard_runner.sh"
echo "     Or start directly: cd $REPO_ROOT && RUNNER_ENV=$RUNNER_ENV_FILE $REPO_ROOT/runner/start.sh"
echo "     Or run in background: cd $REPO_ROOT && nohup env RUNNER_ENV=$RUNNER_ENV_FILE bash $REPO_ROOT/runner/start.sh &"
echo "  (start.sh logs to $RUNNER_LOG_DIR/runner.log by default)"
