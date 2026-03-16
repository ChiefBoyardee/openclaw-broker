#!/usr/bin/env bash
# OpenClaw universal update script.
# Pulls latest code, installs dependencies for detected local components, and restarts services.

set -e

# ---------------------------------------------------------------------------
# Env-file migration helpers
# ---------------------------------------------------------------------------

# Replace an exact "KEY=OLD_VAL" line with "KEY=NEW_VAL".
# Only acts when the line is present with exactly that value; leaves user
# customisations with any other value untouched.
_replace_env_val() {
    local file="$1" key="$2" old_val="$3" new_val="$4"
    if grep -qE "^${key}=${old_val}$" "$file" 2>/dev/null; then
        run_sudo sed -i "s|^${key}=${old_val}$|${key}=${new_val}|" "$file"
        echo "    Migrated: ${key}=${old_val} → ${key}=${new_val}"
    fi
}

# Comment out a KEY=* line (any value) — used for vars that are fully removed.
# Skips lines that are already commented out.
_comment_out_env_key() {
    local file="$1" key="$2" reason="$3"
    if grep -qE "^${key}=" "$file" 2>/dev/null; then
        run_sudo sed -i "s|^${key}=|# [removed] ${key}=|" "$file"
        echo "    Commented out: ${key}  (${reason})"
    fi
}

# Migrate a single env file.  Backs up the file first if any changes are needed.
_migrate_env_file() {
    local file="$1" label="$2"
    [[ -f "$file" ]] || return 0

    # Check whether this file needs any migration at all before touching it.
    local needs_migration=0
    grep -qE "^LEASE_SECONDS=60$"            "$file" 2>/dev/null && needs_migration=1
    grep -qE "^VPS_CMD_TIMEOUT=60$"          "$file" 2>/dev/null && needs_migration=1
    grep -qE "^AGENTIC_ABSOLUTE_MAX_TIMEOUT=" "$file" 2>/dev/null && needs_migration=1
    grep -qE "^AGENTIC_MAX_STREAM_WAIT="      "$file" 2>/dev/null && needs_migration=1
    grep -qE "^AGENTIC_IDLE_TIMEOUT="         "$file" 2>/dev/null && needs_migration=1

    [[ $needs_migration -eq 0 ]] && return 0

    echo "  -> Migrating $label ($file)..."
    run_sudo cp "$file" "${file}.backup.$(date +%Y%m%d%H%M%S)"

    # Broker: old hard lease default → new default matching heartbeat-renewal logic
    _replace_env_val "$file" "LEASE_SECONDS"   "60"  "300"

    # Runner: old SSH command timeout → longer default for certbot/nginx operations
    _replace_env_val "$file" "VPS_CMD_TIMEOUT" "60"  "120"

    # Bot: AGENTIC_ABSOLUTE_MAX_TIMEOUT is fully removed — it bypassed idle-based
    # termination and was the primary cause of hard cutoffs on long tasks.
    _comment_out_env_key "$file" "AGENTIC_ABSOLUTE_MAX_TIMEOUT" \
        "replaced by idle-based termination; heartbeats keep job alive indefinitely"

    # Bot: AGENTIC_MAX_STREAM_WAIT — if set to ≤900 (old default), bump to 3600.
    # Values the user explicitly raised above 900 are left untouched.
    local msw
    msw=$(grep -E "^AGENTIC_MAX_STREAM_WAIT=" "$file" 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')
    if [[ -n "$msw" ]] && [[ "$msw" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        if (( $(echo "$msw <= 900" | bc -l) )); then
            _replace_env_val "$file" "AGENTIC_MAX_STREAM_WAIT" "$msw" "3600"
        fi
    fi

    # Bot: AGENTIC_IDLE_TIMEOUT — the variable is still valid (controls how long
    # to wait without any heartbeat before declaring runner dead), but values that
    # were lowered to work around the old absolute-timeout bug can be relaxed.
    # We only migrate the old conservative default of 300; anything else is left.
    _replace_env_val "$file" "AGENTIC_IDLE_TIMEOUT" "300" "600"

    echo "    Done.  Original saved as ${file}.backup.*"
}

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

    # Migrate broker.env: LEASE_SECONDS 60→300 (heartbeat lease renewal now keeps
    # long jobs alive, so the base lease just needs to outlive one heartbeat interval)
    for BROKER_ENV in /opt/openclaw-broker/broker.env "${REPO_ROOT}/broker.env" "${REPO_ROOT}/broker/broker.env"; do
        _migrate_env_file "$BROKER_ENV" "broker.env"
    done

    if systemctl list-units --full -all | grep -Fq "openclaw-broker.service"; then
        echo "Restarting openclaw-broker service..."
        run_sudo systemctl restart openclaw-broker
        sleep 2
        # Verify restart succeeded
        if systemctl is-active --quiet openclaw-broker; then
            echo "Broker restarted successfully."
        else
            echo "ERROR: Broker restart failed! Check logs: sudo journalctl -u openclaw-broker -n 20"
            exit 1
        fi
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
    
    # Migrate runner.env: VPS_CMD_TIMEOUT 60→120 s for long SSH operations
    for RUNNER_ENV in "${REPO_ROOT}/runner/runner.env" "${REPO_ROOT}/runner.env" /opt/openclaw-runner-jetson/runner.env; do
        _migrate_env_file "$RUNNER_ENV" "runner.env"
    done

    # Restart runner service if using systemd
    if systemctl list-units --full -all | grep -Fq "openclaw-runner.service"; then
        echo "Restarting openclaw-runner service to re-initialize LLM state..."
        run_sudo systemctl restart openclaw-runner
        # Wait a moment for runner to reconnect and load embedding model
        sleep 3
        # Verify restart succeeded
        if systemctl is-active --quiet openclaw-runner; then
            echo "Runner restarted successfully."
        else
            echo "WARNING: Runner restart may have failed. Check logs: sudo journalctl -u openclaw-runner -n 20"
        fi
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
        
        # Migrate bot.env: remove/update legacy hard-timeout variables
        _migrate_env_file "$BOT_DIR/bot.env" "bot.env ($INSTANCE_NAME)"
        
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
            sleep 2
            # Verify restart succeeded
            if systemctl is-active --quiet "$SERVICE"; then
                echo "  -> Bot $INSTANCE_NAME restarted successfully."
            else
                echo "  -> WARNING: Bot $INSTANCE_NAME restart may have failed. Check logs: sudo journalctl -u $SERVICE -n 20"
            fi
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
