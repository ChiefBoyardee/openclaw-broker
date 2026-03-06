#!/usr/bin/env bash
# Automatic update script for OpenClaw components.
# Checks for updates from GitHub and applies them if available.
#
# This script can run as a cron job or systemd timer for automatic updates.
#
# Usage:
#   ./deploy/scripts/auto_update.sh [COMPONENT]
#
# Components:
#   vps|broker      - Update VPS (broker + all Discord bot instances)
#   runner|wsl      - Update WSL runner
#   jetson          - Update Jetson runner
#   llama-cpp       - Update llama.cpp server (if installed)
#   all             - Update all detected components
#
#   If not specified, auto-detects the component based on environment.
#
# Options:
#   --check-only    Only check for updates, don't apply
#   --force         Update even if no new commits (useful for dependency refresh)
#   --restart       Restart services after update (default for systemd installs)
#   --no-restart    Don't restart services after update
#   --notify        Send notification on update (requires notify-send or similar)
#   --quiet         Minimal output (good for cron)
#   --dry-run       Show what would be done without doing it
#
# Environment:
#   AUTO_UPDATE_LOG - Log file path (default: /var/log/openclaw/auto-update.log)
#   COMPONENT       - Default component if not specified as argument
#
# Cron example (check every hour, update at 3 AM):
#   0 * * * * cd /opt/openclaw-broker && ./deploy/scripts/check_updates.sh --quiet || true
#   0 3 * * * cd /opt/openclaw-broker && ./deploy/scripts/auto_update.sh --quiet

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

# Default configuration
COMPONENT="${COMPONENT:-}"
CHECK_ONLY=false
FORCE=false
RESTART="auto"
NOTIFY=false
QUIET=false
DRY_RUN=false
BACKUP=false

# Auto-detected settings
LOG_FILE="${AUTO_UPDATE_LOG:-/var/log/openclaw/auto-update.log}"
LAST_UPDATE_FILE="/var/lib/openclaw/last-update"

# Colors (disabled in quiet mode)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging
log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
  if [[ "$QUIET" == false ]]; then
    echo -e "$msg"
  fi
  # Also log to file if we can write to it
  if [[ -w "$(dirname "$LOG_FILE")" || -w "$LOG_FILE" ]]; then
    mkdir -p "$(dirname "$LOG_FILE")"
    echo "$msg" >> "$LOG_FILE"
  fi
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --check-only)
      CHECK_ONLY=true
      shift
      ;;
    --force)
      FORCE=true
      shift
      ;;
    --restart)
      RESTART=true
      shift
      ;;
    --no-restart)
      RESTART=false
      shift
      ;;
    --notify)
      NOTIFY=true
      shift
      ;;
    --quiet|-q)
      QUIET=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --backup)
      BACKUP=true
      shift
      ;;
    --help|-h)
      cat << 'EOF'
Usage: auto_update.sh [OPTIONS] [COMPONENT]

Automatically check for and apply OpenClaw updates from GitHub.

COMPONENT (optional, auto-detected if not specified):
  vps, broker      Update VPS (broker + all Discord bot instances)
  runner, wsl      Update WSL runner
  jetson           Update Jetson runner
  llama-cpp        Update llama.cpp server (if installed)
  all              Update all detected components

OPTIONS:
  --check-only     Only check for updates, don't apply
  --force          Update even if no new commits detected
  --restart        Restart services after update (default for systemd)
  --no-restart     Don't restart services after update
  --notify         Send desktop notification on update
  --quiet, -q      Minimal output (for cron/systemd timers)
  --dry-run        Show what would be done without executing
  --backup         Create backup before updating
  --help, -h       Show this help

ENVIRONMENT:
  AUTO_UPDATE_LOG  Log file path (default: /var/log/openclaw/auto-update.log)
  COMPONENT        Default component if not specified

EXAMPLES:
  # Check only
  ./deploy/scripts/auto_update.sh --check-only

  # Update with restart (for systemd installations)
  ./deploy/scripts/auto_update.sh --restart

  # Quiet update (good for cron)
  ./deploy/scripts/auto_update.sh --quiet

  # Force update of specific component
  ./deploy/scripts/auto_update.sh --force vps

  # Add to cron (check hourly, update daily at 3 AM)
  0 * * * * cd /path/to/repo && ./deploy/scripts/check_updates.sh --quiet
  0 3 * * * cd /path/to/repo && ./deploy/scripts/auto_update.sh --quiet --restart

EOF
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      COMPONENT="$1"
      shift
      ;;
  esac
done

# Detect component type from environment
detect_component() {
  if [[ -n "$COMPONENT" ]]; then
    return 0
  fi
  
  # Check for systemd services
  if systemctl is-active --quiet openclaw-broker 2>/dev/null; then
    COMPONENT="vps"
    log "Detected component: VPS (broker)"
    return 0
  fi
  
  if systemctl is-active --quiet openclaw-runner 2>/dev/null; then
    # Could be WSL or Jetson, check for Jetson-specific files
    if [[ -f /etc/nv_tegra_release ]] || [[ -d /opt/nvidia/jetson ]]; then
      COMPONENT="jetson"
      log "Detected component: Jetson runner"
    else
      COMPONENT="runner"
      log "Detected component: WSL runner"
    fi
    return 0
  fi
  
  if [[ -f /opt/llama-cpp-server/start-server.sh ]]; then
    log "Detected component: llama-cpp server"
    COMPONENT="llama-cpp"
    return 0
  fi
  
  # Default to runner if we can't detect
  log "Could not auto-detect component, defaulting to runner"
  COMPONENT="runner"
}

# Check for updates using check_updates.sh
check_for_updates() {
  if [[ "$QUIET" == true ]]; then
    if "$SCRIPT_DIR/check_updates.sh" --quiet 2>/dev/null; then
      return 0  # No updates
    else
      return 1  # Updates available
    fi
  else
    "$SCRIPT_DIR/check_updates.sh"
    return $?  # Return the exit code directly
  fi
}

# Create backup before update
create_backup() {
  if [[ "$BACKUP" == false ]]; then
    return 0
  fi
  
  local backup_dir="/var/backups/openclaw/$(date +%Y%m%d-%H%M%S)"
  log "Creating backup at $backup_dir..."
  
  if [[ "$DRY_RUN" == true ]]; then
    log "[DRY RUN] Would create backup: $backup_dir"
    return 0
  fi
  
  mkdir -p "$backup_dir"
  
  # Backup git repo state
  cd "$REPO_ROOT"
  git bundle create "$backup_dir/repo.bundle" --all 2>/dev/null || true
  
  # Backup environment files
  find /opt -name "*.env" -type f 2>/dev/null | while read -r env_file; do
    cp "$env_file" "$backup_dir/" 2>/dev/null || true
  done
  
  # Backup runner env
  if [[ -f "$REPO_ROOT/runner/runner.env" ]]; then
    cp "$REPO_ROOT/runner/runner.env" "$backup_dir/" 2>/dev/null || true
  fi
  
  log "Backup created at $backup_dir"
}

# Update VPS component (broker + bots)
update_vps() {
  log "Updating VPS (broker + Discord bots)..."
  
  if [[ "$DRY_RUN" == true ]]; then
    log "[DRY RUN] Would run: update_vps.sh"
    return 0
  fi
  
  if [[ "$RESTART" == true ]]; then
    "$SCRIPT_DIR/update_vps.sh"
  else
    "$SCRIPT_DIR/update_vps.sh" --no-pull
    log "Skipping service restart (use --restart to restart services)"
  fi
}

# Update WSL runner
update_runner() {
  log "Updating WSL runner..."
  
  if [[ "$DRY_RUN" == true ]]; then
    log "[DRY RUN] Would run: update_runner_wsl.sh"
    return 0
  fi
  
  "$SCRIPT_DIR/update_runner_wsl.sh"
  
  if [[ "$RESTART" == true ]]; then
    log "NOTE: Runner must be restarted manually (stop current process, then start.sh)"
  fi
}

# Update Jetson runner
update_jetson() {
  log "Updating Jetson runner..."
  
  if [[ "$DRY_RUN" == true ]]; then
    log "[DRY RUN] Would run: update_runner_jetson.sh"
    return 0
  fi
  
  if [[ "$RESTART" == true ]]; then
    "$SCRIPT_DIR/update_runner_jetson.sh"
  else
    "$SCRIPT_DIR/update_runner_jetson.sh" --no-pull
    log "Skipping service restart (use --restart to restart services)"
  fi
}

# Update llama.cpp server
update_llama_cpp() {
  log "Updating llama.cpp server..."
  
  if [[ "$DRY_RUN" == true ]]; then
    log "[DRY RUN] Would update llama-cpp-python"
    return 0
  fi
  
  local llama_dir="/opt/llama-cpp-server"
  local user_llama_dir="$HOME/.local/llama-cpp-server"
  
  # Check both system and user install locations
  if [[ -d "$llama_dir" ]]; then
    log "Found system install at $llama_dir"
  elif [[ -d "$user_llama_dir" ]]; then
    llama_dir="$user_llama_dir"
    log "Found user install at $llama_dir"
  else
    log "llama.cpp server not installed"
    return 1
  fi
  
  # Check if this was a source build
  local install_type="pip"
  if [[ -f "$llama_dir/install_type.txt" ]]; then
    install_type=$(cat "$llama_dir/install_type.txt")
  fi
  
  # Update llama-cpp-python
  if [[ -d "$llama_dir/venv" ]]; then
    if [[ "$install_type" == "source" && -d "$llama_dir/src/llama-cpp-python" ]]; then
      log "Updating source-built llama-cpp-python..."
      cd "$llama_dir/src/llama-cpp-python"
      
      # Fetch latest and update submodule
      log "Fetching latest llama-cpp-python..."
      git fetch origin
      git checkout main 2>/dev/null || git checkout master 2>/dev/null || true
      git pull
      
      log "Updating llama.cpp submodule to latest..."
      git submodule update --remote vendor/llama.cpp
      
      # Rebuild
      log "Rebuilding from source..."
      export FORCE_CMAKE=1
      "$llama_dir/venv/bin/pip" install . --upgrade --force-reinstall --no-cache-dir -q
      log "llama-cpp-python updated from source"
    else
      log "Updating llama-cpp-python from pip..."
      "$llama_dir/venv/bin/pip" install --upgrade llama-cpp-python[server] -q
      log "llama-cpp-python updated from pip"
    fi
  fi
  
  # Restart service if running
  if [[ "$RESTART" == true ]]; then
    if systemctl is-active --quiet llama-cpp-server 2>/dev/null; then
      log "Restarting llama-cpp-server service..."
      systemctl restart llama-cpp-server
      log "llama-cpp-server restarted"
    else
      log "llama-cpp-server service not running (manual restart required)"
    fi
  fi
}

# Update all detected components
update_all() {
  log "Updating all detected components..."
  
  # Update main repo first
  if [[ "$DRY_RUN" == false ]]; then
    cd "$REPO_ROOT"
    git pull
  else
    log "[DRY RUN] Would run: git pull"
  fi
  
  # Update each component
  if systemctl is-active --quiet openclaw-broker 2>/dev/null; then
    update_vps
  fi
  
  if systemctl is-active --quiet openclaw-runner 2>/dev/null; then
    if [[ -f /etc/nv_tegra_release ]]; then
      update_jetson
    else
      update_runner
    fi
  fi
  
  if systemctl is-active --quiet llama-cpp-server 2>/dev/null; then
    update_llama_cpp
  fi
}

# Send notification
send_notification() {
  local message="$1"
  
  if [[ "$NOTIFY" == false ]]; then
    return 0
  fi
  
  # Try different notification methods
  if command -v notify-send &> /dev/null; then
    notify-send "OpenClaw Update" "$message"
  elif command -v zenity &> /dev/null; then
    zenity --info --text="$message" --title="OpenClaw Update" 2>/dev/null || true
  elif [[ -n "$DISCORD_WEBHOOK_URL" ]]; then
    # Send to Discord if webhook configured
    curl -s -H "Content-Type: application/json" \
      -d "{\"content\":\"$message\"}" \
      "$DISCORD_WEBHOOK_URL" > /dev/null || true
  fi
}

# Record last update time
record_update() {
  if [[ "$DRY_RUN" == true ]]; then
    return 0
  fi
  
  mkdir -p "$(dirname "$LAST_UPDATE_FILE")"
  date '+%Y-%m-%d %H:%M:%S' > "$LAST_UPDATE_FILE"
  
  # Also record the commit
  cd "$REPO_ROOT"
  git rev-parse HEAD >> "$LAST_UPDATE_FILE"
}

# Main function
main() {
  detect_component
  
  log "=========================================="
  log "OpenClaw Auto-Update"
  log "Component: $COMPONENT"
  log "Repository: $REPO_ROOT"
  log "=========================================="
  
  # Check-only mode
  if [[ "$CHECK_ONLY" == true ]]; then
    log "Running in check-only mode..."
    if check_for_updates; then
      log "No updates available."
      exit 0
    else
      log "Updates are available!"
      exit 1
    fi
  fi
  
  # Check for updates (unless forced)
  if [[ "$FORCE" == false ]]; then
    log "Checking for updates..."
    if check_for_updates; then
      log "No updates available. Exiting."
      exit 0
    fi
    log "Updates found! Proceeding with update..."
  else
    log "Force mode enabled - proceeding regardless of updates..."
  fi
  
  # Determine restart behavior
  if [[ "$RESTART" == "auto" ]]; then
    # Auto-restart if running under systemd
    if [[ -d /run/systemd/system ]]; then
      RESTART=true
      log "Systemd detected - will restart services"
    else
      RESTART=false
      log "Not running under systemd - manual restart required"
    fi
  fi
  
  # Create backup if requested
  create_backup
  
  # Perform update based on component
  case "$COMPONENT" in
    vps|broker)
      update_vps
      ;;
    runner|wsl)
      update_runner
      ;;
    jetson)
      update_jetson
      ;;
    llama-cpp)
      update_llama_cpp
      ;;
    all)
      update_all
      ;;
    *)
      log "Unknown component: $COMPONENT"
      exit 1
      ;;
  esac
  
  # Record successful update
  record_update
  
  # Send notification
  send_notification "OpenClaw updated successfully! ($COMPONENT)"
  
  log "=========================================="
  log "Update complete!"
  log "=========================================="
  
  if [[ "$RESTART" == false ]] && [[ "$COMPONENT" != "runner" ]]; then
    log ""
    log "NOTE: Services were not restarted."
    log "To restart, run:"
    log "  sudo systemctl restart openclaw-broker"
    log "  sudo systemctl restart openclaw-runner"
    log "  sudo systemctl restart llama-cpp-server"
  fi
}

# Run main
main
