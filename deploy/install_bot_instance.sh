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

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  SUDO=()
elif command -v sudo >/dev/null 2>&1; then
  SUDO=(sudo)
else
  echo "Error: this script needs root privileges for /opt, /var/lib, and systemd. Re-run as root or install sudo." >&2
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

run_as_user() {
  local user="$1"
  shift
  if [[ ${#SUDO[@]} -eq 0 ]]; then
    runuser -u "$user" -- "$@"
  else
    "${SUDO[@]}" -u "$user" "$@"
  fi
}

echo "[install_bot_instance] instance=$INSTANCE_NAME REPO_ROOT=$REPO_ROOT"

require_cmd python3
require_cmd runuser
require_cmd systemctl

if [[ ! "$INSTANCE_NAME" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "Error: instance name '$INSTANCE_NAME' may only contain letters, numbers, '_' or '-'." >&2
  exit 1
fi

# 1. Ensure openclaw user/group exist (idempotent)
if ! getent group openclaw &>/dev/null; then
  run_root groupadd openclaw
  echo "[install_bot_instance] group openclaw created"
fi
if ! id -u openclaw &>/dev/null; then
  run_root useradd -r -g openclaw -s /usr/sbin/nologin openclaw
  echo "[install_bot_instance] user openclaw created"
fi

# 2. Create directories
run_root mkdir -p "$OPT_DIR" "$STATE_DIR"
run_root chown openclaw:openclaw "$OPT_DIR" "$STATE_DIR"
echo "[install_bot_instance] dirs $OPT_DIR $STATE_DIR created"

# 3. Copy bot code (run as current user for copy, then fix ownership)
run_root rm -rf "$OPT_DIR/discord_bot"
run_root cp -r "$REPO_ROOT/discord_bot" "$OPT_DIR/"
run_root cp "$REPO_ROOT/requirements.txt" "$OPT_DIR/"
run_root chown -R openclaw:openclaw "$OPT_DIR"

# 4. Venv (create as openclaw so venv has correct ownership)
run_as_user openclaw python3 -m venv "$OPT_DIR/venv"
run_as_user openclaw "$OPT_DIR/venv/bin/pip" install -r "$OPT_DIR/requirements.txt"
echo "[install_bot_instance] venv created and deps installed"

# 5. Example env only; do not create bot.env
run_as_user openclaw cp "$OPT_DIR/discord_bot/bot.env.example" "$OPT_DIR/bot.env.example"

# 6. Install systemd template once
run_root cp "$REPO_ROOT/deploy/systemd/openclaw-discord-bot@.service" "/etc/systemd/system/${UNIT_TEMPLATE}"
run_root systemctl daemon-reload
echo "[install_bot_instance] systemd template installed"

echo ""
echo "Next steps (no secrets are created by this script):"
echo "  1. Create bot env: ${SUDO[*]:+${SUDO[*]} }cp $OPT_DIR/bot.env.example $OPT_DIR/bot.env && ${SUDO[*]:+${SUDO[*]} }${EDITOR:-nano} $OPT_DIR/bot.env"
echo "  2. Set DISCORD_TOKEN, BOT_TOKEN, ALLOWED_USER_ID, BROKER_URL (each instance needs its own Discord Application and token)"
echo "  3. Optional: INSTANCE_NAME is set by systemd to '$INSTANCE_NAME' when using the template"
echo "  4. chown: ${SUDO[*]:+${SUDO[*]} }chown openclaw:openclaw $OPT_DIR/bot.env"
echo "  5. Start: ${SUDO[*]:+${SUDO[*]} }systemctl enable --now openclaw-discord-bot@$INSTANCE_NAME"
echo "  Logs: ${SUDO[*]:+${SUDO[*]} }journalctl -u openclaw-discord-bot@$INSTANCE_NAME -f"
echo ""

if [[ "$ENABLE_NOW" == "--enable" ]]; then
  run_root systemctl enable --now "openclaw-discord-bot@${INSTANCE_NAME}"
  echo "[install_bot_instance] enabled and started openclaw-discord-bot@${INSTANCE_NAME}"
fi
