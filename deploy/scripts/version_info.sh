#!/usr/bin/env bash
# Display OpenClaw version information and update status.
#
# Usage:
#   ./deploy/scripts/version_info.sh
#   ./deploy/scripts/version_info.sh --check   # Also check for updates
#
# This script shows:
#   - Current git commit and date
#   - Last update time (if auto-update was used)
#   - Component type and service status
#   - Update availability (with --check flag)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# Parse arguments
CHECK_UPDATES=false
while [[ $# -gt 0 ]]; do
  case $1 in
    --check|-c)
      CHECK_UPDATES=true
      shift
      ;;
    --help|-h)
      cat << 'EOF'
Usage: version_info.sh [OPTIONS]

Display OpenClaw version information and update status.

OPTIONS:
  --check, -c     Also check for available updates
  --help, -h      Show this help

EXAMPLES:
  ./deploy/scripts/version_info.sh
  ./deploy/scripts/version_info.sh --check

EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# Get git info
get_git_info() {
  cd "$REPO_ROOT"
  
  local commit branch remote repo
  commit=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
  branch=$(git branch --show-current 2>/dev/null || echo "unknown")
  remote=$(git remote get-url origin 2>/dev/null || echo "none")
  
  # Parse repo from remote URL
  if [[ "$remote" =~ github\.com[:/]([^/]+)/([^/.]+) ]]; then
    repo="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
  else
    repo="unknown"
  fi
  
  # Get commit date
  local commit_date
  commit_date=$(git log -1 --format=%cd --date=short 2>/dev/null || echo "unknown")
  
  # Get commit message (first line)
  local commit_msg
  commit_msg=$(git log -1 --format=%s 2>/dev/null || echo "unknown")
  
  echo ""
  echo -e "${BOLD}Repository Information${NC}"
  echo "  Repository: $repo"
  echo "  Branch:     $branch"
  echo "  Commit:     ${CYAN}$commit${NC}"
  echo "  Date:       $commit_date"
  echo "  Message:    $commit_msg"
}

# Get last update info
get_last_update() {
  local last_update_file="/var/lib/openclaw/last-update"
  
  echo ""
  echo -e "${BOLD}Update History${NC}"
  
  if [[ -f "$last_update_file" ]]; then
    local last_update last_commit
    last_update=$(head -1 "$last_update_file")
    last_commit=$(tail -1 "$last_update_file" | cut -c1-7)
    echo "  Last update: $last_update"
    echo "  Commit:      $last_commit"
  else
    echo "  No recorded updates (auto-update may not be configured)"
  fi
}

# Get component status
get_component_status() {
  echo ""
  echo -e "${BOLD}Component Status${NC}"
  
  # Check for broker
  if systemctl is-active --quiet openclaw-broker 2>/dev/null; then
    echo -e "  Broker:     ${GREEN}● running${NC}"
  elif systemctl status openclaw-broker &>/dev/null; then
    echo -e "  Broker:     ${RED}○ stopped${NC}"
  else
    echo "  Broker:     not installed"
  fi
  
  # Check for runner
  if systemctl is-active --quiet openclaw-runner 2>/dev/null; then
    if [[ -f /etc/nv_tegra_release ]] || [[ -d /opt/nvidia/jetson ]]; then
      echo -e "  Runner:     ${GREEN}● running${NC} (Jetson)"
    else
      echo -e "  Runner:     ${GREEN}● running${NC} (WSL/Generic)"
    fi
  elif systemctl status openclaw-runner &>/dev/null; then
    echo -e "  Runner:     ${RED}○ stopped${NC}"
  else
    echo "  Runner:     not installed (or manual start)"
  fi
  
  # Check for Discord bots
  local bot_instances
  bot_instances=$(systemctl list-units --type=service --state=running "openclaw-discord-bot@*" 2>/dev/null | grep -c "openclaw-discord-bot@" || echo "0")
  if [[ "$bot_instances" -gt 0 ]]; then
    echo -e "  Bot(s):     ${GREEN}● running${NC} ($bot_instances instance(s))"
  elif systemctl list-units --type=service "openclaw-discord-bot@*" &>/dev/null; then
    echo -e "  Bot(s):     ${RED}○ stopped${NC}"
  else
    echo "  Bot(s):     not installed"
  fi
  
  # Check for llama.cpp server
  if systemctl is-active --quiet llama-cpp-server 2>/dev/null; then
    echo -e "  LLM Server: ${GREEN}● running${NC} (llama.cpp)"
  elif systemctl status llama-cpp-server &>/dev/null; then
    echo -e "  LLM Server: ${RED}○ stopped${NC} (llama.cpp)"
  elif [[ -f /opt/llama-cpp-server/start-server.sh ]]; then
    echo "  LLM Server: installed but not as service"
  else
    echo "  LLM Server: not installed"
  fi
  
  # Check auto-update timer
  if systemctl is-enabled --quiet openclaw-auto-update.timer 2>/dev/null; then
    local next_run
    next_run=$(systemctl show openclaw-auto-update.timer --property=NextElapseUSecRealtime 2>/dev/null | cut -d= -f2 || echo "unknown")
    echo -e "  Auto-update:${GREEN}● enabled${NC} (next: $next_run)"
  elif systemctl status openclaw-auto-update.timer &>/dev/null; then
    echo -e "  Auto-update:${YELLOW}○ disabled${NC}"
  else
    echo "  Auto-update: not configured"
  fi
}

# Check for updates
get_update_status() {
  echo ""
  echo -e "${BOLD}Update Check${NC}"
  
  cd "$REPO_ROOT"
  
  # Fetch latest from remote (quietly)
  if ! git fetch origin --quiet 2>/dev/null; then
    echo -e "  ${YELLOW}⚠ Could not check for updates (no network?)${NC}"
    return
  fi
  
  local local_commit remote_commit
  local_commit=$(git rev-parse HEAD)
  remote_commit=$(git rev-parse origin/HEAD 2>/dev/null || echo "")
  
  if [[ -z "$remote_commit" ]]; then
    echo "  Could not determine remote commit"
    return
  fi
  
  if [[ "$local_commit" == "$remote_commit" ]]; then
    echo -e "  ${GREEN}✓ Up to date${NC}"
  else
    local ahead behind
    ahead=$(git rev-list --count HEAD..origin/HEAD 2>/dev/null || echo "0")
    behind=$(git rev-list --count origin/HEAD..HEAD 2>/dev/null || echo "0")
    
    echo -e "  ${YELLOW}⬆ Updates available${NC}"
    echo "    Local:  ${local_commit:0:7}"
    echo "    Remote: ${remote_commit:0:7}"
    if [[ "$ahead" -gt 0 ]]; then
      echo "    $ahead new commit(s) on remote"
    fi
    echo ""
    echo "  Run to update:"
    echo "    ./deploy/scripts/auto_update.sh"
  fi
}

# Get llama.cpp model info (if applicable)
get_llamacpp_info() {
  if [[ ! -f /opt/llama-cpp-server/server.env ]]; then
    return
  fi
  
  echo ""
  echo -e "${BOLD}LLM Configuration${NC}"
  
  # Source the server env
  set -a
  source /opt/llama-cpp-server/server.env 2>/dev/null || true
  set +a
  
  if [[ -n "$LLAMA_MODEL" ]]; then
    echo "  Model:      $LLAMA_MODEL"
  fi
  if [[ -n "$LLAMA_N_GPU_LAYERS" ]]; then
    echo "  GPU Layers: $LLAMA_N_GPU_LAYERS"
  fi
  if [[ -n "$LLAMA_PORT" ]]; then
    echo "  Port:       $LLAMA_PORT"
  fi
  
  # Check if server is responding
  if curl -s "http://127.0.0.1:${LLAMA_PORT:-8000}/v1/models" > /dev/null 2>&1; then
    echo -e "  Status:     ${GREEN}● responding${NC}"
  else
    echo -e "  Status:     ${RED}○ not responding${NC}"
  fi
}

# Main function
main() {
  echo ""
  echo -e "${BOLD}OpenClaw Version Information${NC}"
  echo "================================"
  
  get_git_info
  get_last_update
  get_component_status
  get_llamacpp_info
  
  if [[ "$CHECK_UPDATES" == true ]]; then
    get_update_status
  else
    echo ""
    echo "Run with --check to check for updates:"
    echo "  ./deploy/scripts/version_info.sh --check"
  fi
  
  echo ""
  echo "================================"
}

main
