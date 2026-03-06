#!/usr/bin/env bash
# One-shot: create broker.env (with generated tokens), data dir, and start openclaw-broker.
# Run as root on the VPS after install_broker.sh. No prompts.
# Optional: set BROKER_HOST, BROKER_PORT before running (e.g. export BROKER_HOST=100.97.94.35 for Tailscale).
# Idempotent: if broker.env already has non-placeholder tokens, they are kept; only BROKER_HOST/BROKER_PORT are updated.

set -e
BROKER_HOST="${BROKER_HOST:-0.0.0.0}"
BROKER_PORT="${BROKER_PORT:-8000}"
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BROKER_ENV="/opt/openclaw-broker/broker.env"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: required command '$cmd' is not installed or not in PATH." >&2
    exit 1
  fi
}

echo "[configure_broker] BROKER_HOST=$BROKER_HOST BROKER_PORT=$BROKER_PORT REPO_ROOT=$REPO_ROOT"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Error: run this script as root. It writes /opt, /var/lib, and starts a systemd service." >&2
  exit 1
fi
require_cmd openssl
require_cmd curl
require_cmd systemctl

if ! getent group openclaw >/dev/null 2>&1; then
  groupadd openclaw
  echo "[configure_broker] group openclaw created."
fi
if ! id -u openclaw >/dev/null 2>&1; then
  useradd -r -g openclaw -s /usr/sbin/nologin openclaw
  echo "[configure_broker] user openclaw created."
fi

if [[ ! "$BROKER_PORT" =~ ^[0-9]+$ ]]; then
  echo "Error: BROKER_PORT must be numeric. Got: $BROKER_PORT" >&2
  exit 1
fi

mkdir -p /opt/openclaw-broker
if [[ ! -f "$BROKER_ENV" ]]; then
  cp "$REPO_ROOT/broker/broker.env.example" "$BROKER_ENV"
  WORKER_TOKEN=$(openssl rand -hex 32)
  BOT_TOKEN=$(openssl rand -hex 32)
  sed -i "s|WORKER_TOKEN=.*|WORKER_TOKEN=$WORKER_TOKEN|" "$BROKER_ENV"
  sed -i "s|BOT_TOKEN=.*|BOT_TOKEN=$BOT_TOKEN|" "$BROKER_ENV"
  echo "[configure_broker] Generated tokens; broker.env created."
  echo "  Save these for the Discord bot and runner: WORKER_TOKEN=$WORKER_TOKEN BOT_TOKEN=$BOT_TOKEN"
else
  # Keep existing tokens; only update host/port
  sed -i "s|BROKER_HOST=.*|BROKER_HOST=$BROKER_HOST|" "$BROKER_ENV"
  sed -i "s|BROKER_PORT=.*|BROKER_PORT=$BROKER_PORT|" "$BROKER_ENV"
  echo "[configure_broker] broker.env exists; updated BROKER_HOST and BROKER_PORT only."
fi

mkdir -p /var/lib/openclaw-broker
chown openclaw:openclaw /var/lib/openclaw-broker
# Ensure broker.db if present is writable by openclaw (e.g. after a previous root-run)
[ -f /var/lib/openclaw-broker/broker.db ] && chown openclaw:openclaw /var/lib/openclaw-broker/broker.db

# Read port for health check (in case it was changed)
PORT=$(grep -E '^BROKER_PORT=' "$BROKER_ENV" 2>/dev/null | cut -d= -f2- | tr -d '"' || echo "8000")
systemctl start openclaw-broker
echo "[configure_broker] openclaw-broker started."
sleep 1
systemctl status openclaw-broker --no-pager || true
if ! curl -s "http://${BROKER_HOST}:${PORT}/health"; then
  echo "Health check failed. Next checks:" >&2
  echo "  systemctl status openclaw-broker --no-pager" >&2
  echo "  journalctl -u openclaw-broker -n 50 --no-pager" >&2
  echo "  cat $BROKER_ENV" >&2
else
  echo ""
fi
echo "[configure_broker] If workers run off-VPS, open TCP ${PORT} in the cloud firewall. See docs/VPS_FIREWALL.md"
