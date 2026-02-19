#!/usr/bin/env bash
# One-shot: create broker.env (with generated tokens), data dir, and start openclaw-broker.
# Run as root on the VPS after install_broker.sh. No prompts.
# Optional: set BROKER_HOST before running (e.g. export BROKER_HOST=100.97.94.35 for Tailscale).

set -e
BROKER_HOST="${BROKER_HOST:-0.0.0.0}"
REPO_ROOT="${REPO_ROOT:-/opt/openclaw-broker-src}"

echo "[configure_broker] BROKER_HOST=$BROKER_HOST REPO_ROOT=$REPO_ROOT"

mkdir -p /opt/openclaw-broker
cp "$REPO_ROOT/broker/broker.env.example" /opt/openclaw-broker/broker.env

WORKER_TOKEN=$(openssl rand -hex 32)
BOT_TOKEN=$(openssl rand -hex 32)

sed -i "s|WORKER_TOKEN=.*|WORKER_TOKEN=$WORKER_TOKEN|" /opt/openclaw-broker/broker.env
sed -i "s|BOT_TOKEN=.*|BOT_TOKEN=$BOT_TOKEN|" /opt/openclaw-broker/broker.env
sed -i "s|BROKER_HOST=.*|BROKER_HOST=$BROKER_HOST|" /opt/openclaw-broker/broker.env

echo "[configure_broker] Generated tokens; broker.env updated."
echo "  Save these for the Discord bot and runner: WORKER_TOKEN=$WORKER_TOKEN BOT_TOKEN=$BOT_TOKEN"

mkdir -p /var/lib/openclaw-broker
chown openclaw:openclaw /var/lib/openclaw-broker

systemctl start openclaw-broker
echo "[configure_broker] openclaw-broker started."
sleep 1
systemctl status openclaw-broker --no-pager || true
curl -s http://127.0.0.1:8000/health && echo "" || echo "Health check failed or port not 8000."
