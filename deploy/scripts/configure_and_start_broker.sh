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

echo "[configure_broker] BROKER_HOST=$BROKER_HOST BROKER_PORT=$BROKER_PORT REPO_ROOT=$REPO_ROOT"

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
curl -s "http://${BROKER_HOST}:${PORT}/health" && echo "" || echo "Health check failed or wrong host/port."
echo "[configure_broker] If workers run off-VPS, open TCP ${PORT} in the cloud firewall. See docs/VPS_FIREWALL.md"
