#!/usr/bin/env bash
# Install OpenClaw Discord Bot on VPS: venv, requirements, systemd template copy.
# Does NOT enable/start the service unless --enable is passed.
# No secrets in this script; use bot.env (from bot.env.example).

set -e
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SERVICE_NAME="openclaw-discord-bot"
VENV_NAME=".venv-bot"

echo "[install_discord_bot] REPO_ROOT=$REPO_ROOT"

if [[ ! -d "$REPO_ROOT/$VENV_NAME" ]]; then
  python3 -m venv "$REPO_ROOT/$VENV_NAME"
  echo "[install_discord_bot] venv created at $REPO_ROOT/$VENV_NAME"
fi
"$REPO_ROOT/$VENV_NAME/bin/pip" install -r "$REPO_ROOT/requirements.txt"
echo "[install_discord_bot] dependencies installed"

sudo cp "$REPO_ROOT/deploy/systemd/openclaw-discord-bot.service.template" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo sed -i "s|/opt/openclaw/openclaw-broker|$REPO_ROOT|g" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
echo "[install_discord_bot] systemd unit copied to /etc/systemd/system/${SERVICE_NAME}.service"

echo ""
echo "Next steps:"
echo "  1. Create bot env: sudo mkdir -p /opt/openclaw-discord-bot && sudo cp $REPO_ROOT/discord_bot/bot.env.example /opt/openclaw-discord-bot/bot.env && sudo $EDITOR /opt/openclaw-discord-bot/bot.env"
echo "  2. Set DISCORD_TOKEN, BOT_TOKEN (same as broker), ALLOWED_USER_ID, BROKER_URL"
echo "  3. Optional: sudo systemctl enable $SERVICE_NAME && sudo systemctl start $SERVICE_NAME"
if [[ "${1:-}" == "--enable" ]]; then
  sudo systemctl enable "$SERVICE_NAME"
  echo "[install_discord_bot] service enabled (not started; start with: sudo systemctl start $SERVICE_NAME)"
fi
