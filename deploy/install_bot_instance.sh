#!/usr/bin/env bash
# Install one OpenClaw Discord Bot instance for multi-instance deploy.
# Usage: ./deploy/install_bot_instance.sh <instance_name> [--enable]
# Creates /opt/openclaw-bot-<instance>/ and /var/lib/openclaw-bot-<instance>/.
# No secrets in this script; create bot.env from bot.env.example manually.

set -e
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
INSTANCE_NAME="${1:?Usage: $0 <instance_name> [--enable]}"
ENABLE_NOW="${2:-}"

OPT_DIR="/opt/openclaw-bot-${INSTANCE_NAME}"
STATE_DIR="/var/lib/openclaw-bot-${INSTANCE_NAME}"
UNIT_TEMPLATE="openclaw-discord-bot@.service"

echo "[install_bot_instance] instance=$INSTANCE_NAME REPO_ROOT=$REPO_ROOT"

# 1. Ensure openclaw user/group exist (idempotent)
if ! getent group openclaw &>/dev/null; then
  sudo groupadd openclaw
  echo "[install_bot_instance] group openclaw created"
fi
if ! id -u openclaw &>/dev/null; then
  sudo useradd -r -g openclaw -s /usr/sbin/nologin openclaw
  echo "[install_bot_instance] user openclaw created"
fi

# 2. Create directories
sudo mkdir -p "$OPT_DIR" "$STATE_DIR"
sudo chown openclaw:openclaw "$OPT_DIR" "$STATE_DIR"
echo "[install_bot_instance] dirs $OPT_DIR $STATE_DIR created"

# 3. Copy bot code (run as current user for copy, then fix ownership)
sudo cp -r "$REPO_ROOT/discord_bot" "$OPT_DIR/"
sudo cp "$REPO_ROOT/requirements.txt" "$OPT_DIR/"
sudo chown -R openclaw:openclaw "$OPT_DIR"

# 4. Venv (create as openclaw so venv has correct ownership)
sudo -u openclaw python3 -m venv "$OPT_DIR/venv"
sudo -u openclaw "$OPT_DIR/venv/bin/pip" install -r "$OPT_DIR/requirements.txt"
echo "[install_bot_instance] venv created and deps installed"

# 5. Example env only; do not create bot.env
sudo -u openclaw cp "$OPT_DIR/discord_bot/bot.env.example" "$OPT_DIR/bot.env.example"

# 6. Install systemd template once
sudo cp "$REPO_ROOT/deploy/systemd/openclaw-discord-bot@.service" "/etc/systemd/system/${UNIT_TEMPLATE}"
sudo systemctl daemon-reload
echo "[install_bot_instance] systemd template installed"

echo ""
echo "Next steps (no secrets are created by this script):"
echo "  1. Create bot env: sudo cp $OPT_DIR/bot.env.example $OPT_DIR/bot.env && sudo ${EDITOR:-nano} $OPT_DIR/bot.env"
echo "  2. Set DISCORD_TOKEN, BOT_TOKEN, ALLOWED_USER_ID, BROKER_URL (each instance needs its own Discord Application and token)"
echo "  3. Optional: INSTANCE_NAME is set by systemd to '$INSTANCE_NAME' when using the template"
echo "  4. chown: sudo chown openclaw:openclaw $OPT_DIR/bot.env"
echo "  5. Start: sudo systemctl enable --now openclaw-discord-bot@$INSTANCE_NAME"
echo "  Logs: journalctl -u openclaw-discord-bot@$INSTANCE_NAME -f"
echo ""

if [[ "$ENABLE_NOW" == "--enable" ]]; then
  sudo systemctl enable --now "openclaw-discord-bot@${INSTANCE_NAME}"
  echo "[install_bot_instance] enabled and started openclaw-discord-bot@${INSTANCE_NAME}"
fi
