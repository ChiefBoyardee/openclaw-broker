#!/usr/bin/env bash
# Install OpenClaw Runner as systemd service (e.g. on Jetson Orin).
# Uses REPO_ROOT (clone of openclaw-broker), creates venv, env from runner-jetson.env.example,
# installs openclaw-runner.service. Does NOT start the service unless --enable is passed.
# No secrets in this script; edit runner.env after copy.

set -e
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RUNNER_INSTALL_DIR="${RUNNER_INSTALL_DIR:-/opt/openclaw-runner-jetson}"
VENV_NAME=".venv-runner"
SERVICE_NAME="openclaw-runner"

echo "[install_runner_systemd] REPO_ROOT=$REPO_ROOT RUNNER_INSTALL_DIR=$RUNNER_INSTALL_DIR"

# Venv and deps
if [[ ! -d "$REPO_ROOT/$VENV_NAME" ]]; then
  python3 -m venv "$REPO_ROOT/$VENV_NAME"
  echo "[install_runner_systemd] venv created at $REPO_ROOT/$VENV_NAME"
fi
"$REPO_ROOT/$VENV_NAME/bin/pip" install -r "$REPO_ROOT/requirements.txt"
echo "[install_runner_systemd] dependencies installed"

# Env file (operator must edit with BROKER_URL, WORKER_TOKEN, LLM_*, etc.)
sudo mkdir -p "$RUNNER_INSTALL_DIR"
if [[ ! -f "$RUNNER_INSTALL_DIR/runner.env" ]]; then
  sudo cp "$REPO_ROOT/deploy/env.examples/runner-jetson.env.example" "$RUNNER_INSTALL_DIR/runner.env"
  echo "[install_runner_systemd] copied runner.env from runner-jetson.env.example; edit with your values"
else
  echo "[install_runner_systemd] $RUNNER_INSTALL_DIR/runner.env already exists (not overwritten)"
fi

# Systemd unit: substitute REPO_ROOT and EnvironmentFile path
sudo sed -e "s|REPO_ROOT_PLACEHOLDER|$REPO_ROOT|g" \
  -e "s|/opt/openclaw-runner-jetson/runner.env|$RUNNER_INSTALL_DIR/runner.env|g" \
  "$REPO_ROOT/deploy/systemd/openclaw-runner.service.template" \
  > /tmp/openclaw-runner.service.$$
sudo mv /tmp/openclaw-runner.service.$$ "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
echo "[install_runner_systemd] systemd unit installed at /etc/systemd/system/${SERVICE_NAME}.service"

echo ""
echo "Next steps:"
echo "  1. Edit runner env: sudo ${EDITOR:-nano} $RUNNER_INSTALL_DIR/runner.env"
echo "     Set BROKER_URL, WORKER_TOKEN, WORKER_ID, WORKER_CAPS=llm:jetson,repo_tools, LLM_BASE_URL, LLM_MODEL"
echo "  2. Optional: sudo systemctl enable $SERVICE_NAME && sudo systemctl start $SERVICE_NAME"
if [[ "${1:-}" == "--enable" ]]; then
  sudo systemctl enable "$SERVICE_NAME"
  echo "[install_runner_systemd] service enabled (start with: sudo systemctl start $SERVICE_NAME)"
fi
