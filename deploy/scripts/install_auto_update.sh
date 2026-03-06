#!/usr/bin/env bash
# Install OpenClaw automatic update systemd service and timer.
# This script sets up automatic updates to run at scheduled intervals.
#
# Usage:
#   ./deploy/scripts/install_auto_update.sh [OPTIONS]
#
# Options:
#   --component TYPE   Component type (vps, runner, jetson, llama-cpp)
#   --user USER        Run as this user (default: current user)
#   --interval SPEC    Systemd calendar spec (default: daily at 3 AM)
#   --enable           Enable the timer immediately
#
# Examples:
#   # Install for VPS with daily updates
#   sudo ./deploy/scripts/install_auto_update.sh --component vps --enable
#
#   # Install for WSL runner, hourly checks
#   sudo ./deploy/scripts/install_auto_update.sh --component runner \
#     --interval "*:00/6" --enable
#
#   # Install for Jetson with custom user
#   sudo ./deploy/scripts/install_auto_update.sh --component jetson \
#     --user openclaw --enable

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

# Default configuration
COMPONENT=""
RUN_USER="${SUDO_USER:-$USER}"
INTERVAL="*-*-* 03:00:00"
ENABLE=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[install_auto_update]${NC} $1"; }
success() { echo -e "${GREEN}[install_auto_update]${NC} $1"; }
warn() { echo -e "${YELLOW}[install_auto_update]${NC} $1"; }
error() { echo -e "${RED}[install_auto_update]${NC} $1" >&2; }

# Show help
show_help() {
  cat << EOF
Install OpenClaw automatic update systemd service and timer.

USAGE:
    sudo $0 [OPTIONS]

OPTIONS:
    --component TYPE    Component type (vps, runner, jetson, llama-cpp)
    --user USER         Run updates as this user (default: current)
    --interval SPEC     Systemd OnCalendar spec (default: daily 3 AM)
                        Examples: "daily", "weekly", "*:00/6"
    --enable            Enable and start the timer immediately
    --help              Show this help

COMPONENTS:
    vps        - VPS with broker and Discord bots
    runner     - WSL runner
    jetson     - Jetson Orin runner
    llama-cpp  - llama.cpp server only

EXAMPLES:
    # VPS with daily updates at 3 AM
    sudo $0 --component vps --enable

    # Runner with 6-hour update checks
    sudo $0 --component runner --interval "*:00/6" --enable

    # Jetson with weekly updates
    sudo $0 --component jetson --interval "weekly" --enable

SCHEDULE FORMAT (systemd OnCalendar):
    *-*-* 03:00:00     - Daily at 3:00 AM
    Mon,Fri 02:00      - Monday and Friday at 2 AM
    *:00/6             - Every 6 hours
    weekly             - Weekly

EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --component)
      COMPONENT="$2"
      shift 2
      ;;
    --user)
      RUN_USER="$2"
      shift 2
      ;;
    --interval)
      INTERVAL="$2"
      shift 2
      ;;
    --enable)
      ENABLE=true
      shift
      ;;
    --help|-h)
      show_help
      exit 0
      ;;
    *)
      error "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Detect component if not specified
detect_component() {
  if [[ -n "$COMPONENT" ]]; then
    return 0
  fi
  
  log "Auto-detecting component type..."
  
  if systemctl is-active --quiet openclaw-broker 2>/dev/null; then
    COMPONENT="vps"
  elif [[ -f /etc/nv_tegra_release ]] || [[ -d /opt/nvidia/jetson ]]; then
    COMPONENT="jetson"
  elif systemctl is-active --quiet openclaw-runner 2>/dev/null; then
    COMPONENT="runner"
  elif systemctl is-active --quiet llama-cpp-server 2>/dev/null; then
    COMPONENT="llama-cpp"
  else
    error "Could not auto-detect component type. Please specify with --component"
    exit 1
  fi
  
  log "Detected component: $COMPONENT"
}

# Verify systemd is available
check_systemd() {
  if [[ ! -d /etc/systemd/system ]]; then
    error "Systemd is not available on this system"
    exit 1
  fi
  
  if [[ $EUID -ne 0 ]]; then
    error "This script must be run with sudo"
    exit 1
  fi
}

# Install the service and timer
install_service() {
  log "Installing auto-update service..."
  
  # Copy timer file
  cp "$REPO_ROOT/deploy/systemd/openclaw-auto-update.timer" \
    /etc/systemd/system/openclaw-auto-update.timer
  
  # Customize the timer interval
  if [[ "$INTERVAL" != "*-*-* 03:00:00" ]]; then
    log "Setting update interval to: $INTERVAL"
    sed -i "s|OnCalendar=\*-\*-\* 03:00:00|OnCalendar=$INTERVAL|" \
      /etc/systemd/system/openclaw-auto-update.timer
  fi
  
  # Copy and customize service file
  sed -e "s|REPO_ROOT_PLACEHOLDER|$REPO_ROOT|g" \
      -e "s|REPO_USER_PLACEHOLDER|$RUN_USER|g" \
      -e "s|COMPONENT_PLACEHOLDER|$COMPONENT|g" \
      "$REPO_ROOT/deploy/systemd/openclaw-auto-update.service.template" \
      > /etc/systemd/system/openclaw-auto-update.service
  
  # Create log directory
  mkdir -p /var/log/openclaw
  chown "$RUN_USER:$RUN_USER" /var/log/openclaw
  
  # Create state directory for last update tracking
  mkdir -p /var/lib/openclaw
  chown "$RUN_USER:$RUN_USER" /var/lib/openclaw
  
  # Reload systemd
  systemctl daemon-reload
  
  success "Service files installed"
}

# Enable and start the timer
enable_timer() {
  if [[ "$ENABLE" == false ]]; then
    log ""
    log "To enable automatic updates, run:"
    log "  sudo systemctl enable --now openclaw-auto-update.timer"
    return 0
  fi
  
  log "Enabling and starting timer..."
  systemctl enable --now openclaw-auto-update.timer
  
  success "Timer enabled and started!"
}

# Print final status
print_status() {
  echo ""
  echo "========================================"
  echo "Auto-Update Installation Complete"
  echo "========================================"
  echo ""
  echo "Configuration:"
  echo "  Component: $COMPONENT"
  echo "  Run as user: $RUN_USER"
  echo "  Repository: $REPO_ROOT"
  echo "  Update interval: $INTERVAL"
  echo ""
  echo "Service files:"
  echo "  /etc/systemd/system/openclaw-auto-update.service"
  echo "  /etc/systemd/system/openclaw-auto-update.timer"
  echo ""
  echo "Logs:"
  echo "  /var/log/openclaw/auto-update.log"
  echo "  sudo journalctl -u openclaw-auto-update.service -f"
  echo ""
  
  if [[ "$ENABLE" == true ]]; then
    echo "Timer status:"
    systemctl status openclaw-auto-update.timer --no-pager || true
    echo ""
    echo "Next scheduled runs:"
    systemctl list-timers openclaw-auto-update.timer --no-pager || true
  else
    echo "Status: Timer installed but not enabled"
    echo "Enable with: sudo systemctl enable --now openclaw-auto-update.timer"
  fi
  
  echo ""
  echo "Manual trigger:"
  echo "  sudo systemctl start openclaw-auto-update.service"
  echo ""
  echo "Check for updates without applying:"
  echo "  ./deploy/scripts/check_updates.sh"
  echo ""
}

# Main function
main() {
  log "OpenClaw Auto-Update Installation"
  log "================================="
  echo ""
  
  check_systemd
  detect_component
  install_service
  enable_timer
  print_status
  
  success "Installation complete!"
}

main
