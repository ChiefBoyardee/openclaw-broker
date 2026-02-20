#!/usr/bin/env bash
# Update OpenClaw on VPS: pull repo, refresh deps, restart broker and all Discord bot instances.
# Run from repo root on the VPS (or set REPO_ROOT). Use --no-pull to skip git pull (restart only).
# Usage: ./deploy/scripts/update_vps.sh [--no-pull]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
NO_PULL=""
for arg in "$@"; do
  [[ "$arg" == "--no-pull" ]] && NO_PULL=1
done

echo "[update_vps] REPO_ROOT=$REPO_ROOT NO_PULL=$NO_PULL"
cd "$REPO_ROOT"

if [[ -z "$NO_PULL" ]]; then
  git pull
  echo "[update_vps] git pull done"
fi

# Broker: refresh venv and restart
if [[ -d "$REPO_ROOT/.venv-broker" ]]; then
  "$REPO_ROOT/.venv-broker/bin/pip" install -r "$REPO_ROOT/requirements.txt" -q
  echo "[update_vps] broker venv updated"
fi
sudo systemctl restart openclaw-broker
echo "[update_vps] openclaw-broker restarted"

# Bot instances: copy code, refresh venv, restart each
for opt_dir in /opt/openclaw-bot-*/; do
  [[ -d "$opt_dir" ]] || continue
  instance="$(basename "$opt_dir" | sed 's/^openclaw-bot-//')"
  if [[ -z "$instance" ]]; then
    continue
  fi
  echo "[update_vps] updating bot instance: $instance"
  sudo rm -rf "${opt_dir}discord_bot"
  sudo cp -r "$REPO_ROOT/discord_bot" "$opt_dir"
  sudo cp "$REPO_ROOT/requirements.txt" "$opt_dir"
  sudo chown -R openclaw:openclaw "$opt_dir/discord_bot" "$opt_dir/requirements.txt"
  sudo -u openclaw "$opt_dir/venv/bin/pip" install -r "$opt_dir/requirements.txt" -q
  sudo systemctl restart "openclaw-discord-bot@${instance}"
  echo "[update_vps] openclaw-discord-bot@${instance} restarted"
done

echo "[update_vps] done"
