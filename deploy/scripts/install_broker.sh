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

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  SUDO=()
elif command -v sudo >/dev/null 2>&1; then
  SUDO=(sudo)
else
  echo "Error: this script needs root privileges for systemd and service-user setup. Re-run as root or install sudo." >&2
  exit 1
fi

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: required command '$cmd' is not installed or not in PATH." >&2
    exit 1
  fi
}

run_root() {
  "${SUDO[@]}" "$@"
}

echo "[install_broker] REPO_ROOT=$REPO_ROOT"

require_cmd python3
require_cmd systemctl

if ! getent group "$INSTALL_USER" >/dev/null 2>&1; then
  run_root groupadd "$INSTALL_USER"
  echo "[install_broker] group $INSTALL_USER created"
fi
if ! id -u "$INSTALL_USER" >/dev/null 2>&1; then
  run_root useradd -r -g "$INSTALL_USER" -s /usr/sbin/nologin "$INSTALL_USER"
  echo "[install_broker] user $INSTALL_USER created"
fi

# Create venv and install broker deps only
if [[ ! -d "$REPO_ROOT/$VENV_NAME" ]]; then
  python3 -m venv "$REPO_ROOT/$VENV_NAME"
  echo "[install_broker] venv created at $REPO_ROOT/$VENV_NAME"
fi
"$REPO_ROOT/$VENV_NAME/bin/pip" install -r "$REPO_ROOT/requirements.txt"
echo "[install_broker] dependencies installed"

# Copy systemd template (no substitution of secrets)
run_root cp "$REPO_ROOT/deploy/systemd/openclaw-broker.service.template" "/etc/systemd/system/${SERVICE_NAME}.service"
# Substitute REPO path in unit so it works regardless of where repo lives
run_root sed -i "s|/opt/openclaw/openclaw-broker|$REPO_ROOT|g" "/etc/systemd/system/${SERVICE_NAME}.service"
run_root systemctl daemon-reload
echo "[install_broker] systemd unit copied to /etc/systemd/system/${SERVICE_NAME}.service"

echo ""
echo "Next steps:"
echo "  1. Create broker env: ${SUDO[*]:+${SUDO[*]} }mkdir -p /opt/openclaw-broker && ${SUDO[*]:+${SUDO[*]} }cp $REPO_ROOT/broker/broker.env.example /opt/openclaw-broker/broker.env && ${SUDO[*]:+${SUDO[*]} }${EDITOR:-nano} /opt/openclaw-broker/broker.env"
echo "  2. Set WORKER_TOKEN and BOT_TOKEN (e.g. openssl rand -hex 32), BROKER_DB, BROKER_HOST (e.g. tailscale0 IP), BROKER_PORT"
echo "  3. Create data dir: ${SUDO[*]:+${SUDO[*]} }mkdir -p /var/lib/openclaw-broker && ${SUDO[*]:+${SUDO[*]} }chown $INSTALL_USER:$INSTALL_USER /var/lib/openclaw-broker"
echo "  4. Optional: ${SUDO[*]:+${SUDO[*]} }systemctl enable $SERVICE_NAME && ${SUDO[*]:+${SUDO[*]} }systemctl start $SERVICE_NAME"
if [[ "${1:-}" == "--enable" ]]; then
  run_root systemctl enable "$SERVICE_NAME"
  echo "[install_broker] service enabled (not started; start with: ${SUDO[*]:+${SUDO[*]} }systemctl start $SERVICE_NAME)"
fi
