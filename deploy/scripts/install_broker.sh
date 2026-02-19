#!/usr/bin/env bash
# Install OpenClaw Broker on VPS: venv, requirements, systemd template copy.
# Does NOT enable/start the service unless --enable is passed.
# No secrets in this script; use broker.env (from broker.env.example).

set -e
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
INSTALL_USER="${INSTALL_USER:-openclaw}"
INSTALL_DIR="${INSTALL_DIR:-/opt/openclaw}"
SERVICE_NAME="openclaw-broker"
VENV_NAME=".venv-broker"

echo "[install_broker] REPO_ROOT=$REPO_ROOT"

# Create venv and install broker deps only
if [[ ! -d "$REPO_ROOT/$VENV_NAME" ]]; then
  python3 -m venv "$REPO_ROOT/$VENV_NAME"
  echo "[install_broker] venv created at $REPO_ROOT/$VENV_NAME"
fi
"$REPO_ROOT/$VENV_NAME/bin/pip" install -r "$REPO_ROOT/requirements.txt"
echo "[install_broker] dependencies installed"

# Copy systemd template (no substitution of secrets)
sudo cp "$REPO_ROOT/deploy/systemd/openclaw-broker.service.template" "/etc/systemd/system/${SERVICE_NAME}.service"
# Substitute REPO path in unit so it works regardless of where repo lives
sudo sed -i "s|/opt/openclaw/openclaw-broker|$REPO_ROOT|g" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
echo "[install_broker] systemd unit copied to /etc/systemd/system/${SERVICE_NAME}.service"

echo ""
echo "Next steps:"
echo "  1. Create broker env: sudo mkdir -p /opt/openclaw-broker && sudo cp $REPO_ROOT/broker/broker.env.example /opt/openclaw-broker/broker.env && sudo ${EDITOR:-nano} /opt/openclaw-broker/broker.env"
echo "  2. Set WORKER_TOKEN and BOT_TOKEN (e.g. openssl rand -hex 32), BROKER_DB, BROKER_HOST (e.g. tailscale0 IP), BROKER_PORT"
echo "  3. Create data dir: sudo mkdir -p /var/lib/openclaw-broker && sudo chown $INSTALL_USER:$INSTALL_USER /var/lib/openclaw-broker"
echo "  4. Optional: sudo systemctl enable $SERVICE_NAME && sudo systemctl start $SERVICE_NAME"
if [[ "${1:-}" == "--enable" ]]; then
  sudo systemctl enable "$SERVICE_NAME"
  echo "[install_broker] service enabled (not started; start with: sudo systemctl start $SERVICE_NAME)"
fi
