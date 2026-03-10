#!/usr/bin/env bash
# OpenClaw universal update script.
# Pulls latest code, installs dependencies for detected local components, and restarts services.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Pulling latest changes from git ==="
git fetch origin main
git reset --hard origin/main

HAS_SUDO=0
if command -v sudo >/dev/null 2>&1; then
    HAS_SUDO=1
fi

function run_sudo() {
    if [[ $EUID -eq 0 ]]; then
        "$@"
    elif [[ $HAS_SUDO -eq 1 ]]; then
        sudo "$@"
    else
        echo "Error: Need root privileges to run: $*"
        exit 1
    fi
}

echo ""
echo "=== Updating OpenClaw Broker ==="
if [[ -d "${REPO_ROOT}/.venv-broker" ]]; then
    echo "Detected broker installation. Updating dependencies..."
    "${REPO_ROOT}/.venv-broker/bin/pip" install -r requirements.txt
    
    if systemctl list-units --full -all | grep -Fq "openclaw-broker.service"; then
        echo "Restarting openclaw-broker service..."
        run_sudo systemctl restart openclaw-broker
    fi
else
    echo "No local broker detected (.venv-broker missing)."
fi

echo ""
echo "=== Updating OpenClaw Runner ==="
if [[ -d "${REPO_ROOT}/.venv-runner" ]]; then
    echo "Detected runner installation. Updating dependencies..."
    "${REPO_ROOT}/.venv-runner/bin/pip" install -r requirements.txt
    
    if [[ -f "${REPO_ROOT}/requirements-runner-enhanced.txt" ]]; then
        echo "Installing enhanced runner dependencies (Playwright + Embedding support)..."
        "${REPO_ROOT}/.venv-runner/bin/pip" install -r requirements-runner-enhanced.txt
        "${REPO_ROOT}/.venv-runner/bin/playwright" install chromium
    fi
    
    # Check if runner has embedding capability configured
    if [[ -f "${REPO_ROOT}/runner.env" ]] && grep -q "EMBEDDING_MODEL=" "${REPO_ROOT}/runner.env"; then
        echo "Note: Runner embedding model configured. Ensure sentence-transformers is installed (included in enhanced deps)."
    fi
    
    # Restart runner service if using systemd
    if systemctl list-units --full -all | grep -Fq "openclaw-runner.service"; then
        echo "Restarting openclaw-runner service to re-initialize LLM state..."
        run_sudo systemctl restart openclaw-runner
        # Wait a moment for runner to reconnect and load embedding model
        sleep 2
        echo "Runner restarted. Embedding model will be lazy-loaded on first use."
    else
        echo "Note: openclaw-runner systemd service not found. If you run the runner manually via terminal, please restart it to apply updates."
    fi
else
    echo "No local runner detected (.venv-runner missing)."
fi

echo ""
echo "=== Updating OpenClaw Discord Bots ==="
# Check for bot instances in /opt/openclaw-bot-*
BOT_FOUND=0
for BOT_DIR in /opt/openclaw-bot-*; do
    if [[ -d "$BOT_DIR" ]]; then
        BOT_FOUND=1
        INSTANCE_NAME=$(basename "$BOT_DIR" | sed 's/openclaw-bot-//')
        echo "Detected bot instance: $INSTANCE_NAME"
        
        echo "  -> Syncing latest bot code to $BOT_DIR..."
        run_sudo rm -rf "$BOT_DIR/discord_bot"
        run_sudo cp -r "${REPO_ROOT}/discord_bot" "$BOT_DIR/"
        run_sudo cp "${REPO_ROOT}/requirements.txt" "$BOT_DIR/"
        
        # Copy custom_personas.json if it doesn't exist (preserve user customizations)
        if [[ -f "${REPO_ROOT}/custom_personas.json" ]]; then
            if [[ ! -f "$BOT_DIR/custom_personas.json" ]]; then
                echo "  -> Installing custom_personas.json (user customizations)..."
                run_sudo cp "${REPO_ROOT}/custom_personas.json" "$BOT_DIR/"
                run_sudo chown openclaw:openclaw "$BOT_DIR/custom_personas.json"
            else
                echo "  -> Preserving existing custom_personas.json (user customizations kept)"
            fi
        fi
        
        run_sudo chown -R openclaw:openclaw "$BOT_DIR/discord_bot" "$BOT_DIR/requirements.txt"
        
        echo "  -> Updating bot dependencies..."
        if [[ $EUID -eq 0 ]]; then
            runuser -u openclaw -- "$BOT_DIR/venv/bin/pip" install -r "$BOT_DIR/requirements.txt"
        elif [[ $HAS_SUDO -eq 1 ]]; then
            sudo -u openclaw "$BOT_DIR/venv/bin/pip" install -r "$BOT_DIR/requirements.txt"
        fi
        
        # Install memory dependencies if configured
        if [[ -f "$BOT_DIR/bot.env" ]] && grep -q "EMBEDDING_PROVIDER=" "$BOT_DIR/bot.env" && grep -vq "EMBEDDING_PROVIDER=none" "$BOT_DIR/bot.env"; then
            echo "  -> Memory features detected in bot.env. Installing memory dependencies..."
            if [[ $EUID -eq 0 ]]; then
                runuser -u openclaw -- "$BOT_DIR/venv/bin/pip" install -r "${REPO_ROOT}/requirements-memory.txt"
            elif [[ $HAS_SUDO -eq 1 ]]; then
                sudo -u openclaw "$BOT_DIR/venv/bin/pip" install -r "${REPO_ROOT}/requirements-memory.txt"
            fi
        fi
        
        SERVICE="openclaw-discord-bot@${INSTANCE_NAME}"
        if systemctl list-units --full -all | grep -Fq "${SERVICE}.service"; then
            echo "  -> Restarting service $SERVICE..."
            run_sudo systemctl restart "$SERVICE"
        fi
    fi
done

if [[ $BOT_FOUND -eq 0 ]]; then
    echo "No local bot instances detected."
fi

echo ""
echo "=== Update Complete! ==="
echo ""
echo "Services restarted:"
echo "  - Broker: Maintains job queue (persists across restarts)"
echo "  - Runner: LLM and embedding model re-initialized"
echo "  - Bot: Fresh instance with updated code"
echo ""
echo "If persona responses are still incorrect, try clearing state:"
echo "  sudo rm /opt/openclaw-bot-<instance>/*.db  # Clear conversation history"
echo "  sudo systemctl restart openclaw-discord-bot@<instance>"
echo ""
