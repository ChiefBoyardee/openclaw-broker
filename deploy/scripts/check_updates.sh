#!/usr/bin/env bash
# Check for OpenClaw updates from GitHub repository.
# This script compares the local commit with the latest remote commit
# and reports if an update is available.
#
# Usage:
#   ./deploy/scripts/check_updates.sh              # Check and report only
#   ./deploy/scripts/check_updates.sh --notify   # Print update notification if available
#   ./deploy/scripts/check_updates.sh --quiet    # Exit 0 if up-to-date, 1 if update available
#
# Environment:
#   GITHUB_REPO    - GitHub repo in format "owner/repo" (auto-detected from git remote)
#   CHECK_BRANCH   - Branch to check (default: main)
#
# Exit codes:
#   0 - Up to date
#   1 - Update available (or error in --quiet mode)
#   2 - Not a git repository or no remote configured

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

# Configuration
CHECK_BRANCH="${CHECK_BRANCH:-main}"
GITHUB_REPO="${GITHUB_REPO:-}"
QUIET=false
NOTIFY=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --quiet|-q)
      QUIET=true
      shift
      ;;
    --notify|-n)
      NOTIFY=true
      shift
      ;;
    --help|-h)
      cat << 'EOF'
Usage: check_updates.sh [OPTIONS]

Check if OpenClaw updates are available from GitHub.

OPTIONS:
  --quiet, -q     Silent mode: exit 0 if up-to-date, 1 if update available
  --notify, -n    Print notification message if update available
  --help, -h      Show this help

ENVIRONMENT:
  GITHUB_REPO     GitHub repo "owner/repo" (auto-detected)
  CHECK_BRANCH    Branch to check (default: main)

EXAMPLES:
  ./deploy/scripts/check_updates.sh
  ./deploy/scripts/check_updates.sh --quiet && echo "Up to date" || echo "Update available"

EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# Detect GitHub repo from git remote
detect_github_repo() {
  if [[ -z "$GITHUB_REPO" ]]; then
    local remote_url
    remote_url=$(cd "$REPO_ROOT" && git remote get-url origin 2>/dev/null || echo "")
    
    if [[ -z "$remote_url" ]]; then
      [[ "$QUIET" == false ]] && echo "Error: No git remote configured" >&2
      exit 2
    fi
    
    # Parse GitHub URL (handles HTTPS and SSH formats)
    if [[ "$remote_url" =~ github\.com[:/]([^/]+)/([^/.]+) ]]; then
      GITHUB_REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
    else
      [[ "$QUIET" == false ]] && echo "Error: Could not parse GitHub repo from $remote_url" >&2
      exit 2
    fi
  fi
}

# Get latest commit from GitHub API
get_remote_commit() {
  local api_url="https://api.github.com/repos/$GITHUB_REPO/commits/$CHECK_BRANCH"
  local commit_sha
  
  # Try to fetch with curl
  if ! commit_sha=$(curl -s -H "Accept: application/vnd.github.v3+json" \
    "$api_url" 2>/dev/null | grep -o '"sha": "[^"]*"' | head -1 | cut -d'"' -f4); then
    [[ "$QUIET" == false ]] && echo "Error: Failed to fetch from GitHub API" >&2
    exit 1
  fi
  
  if [[ -z "$commit_sha" ]]; then
    [[ "$QUIET" == false ]] && echo "Error: Could not get commit SHA from GitHub" >&2
    exit 1
  fi
  
  echo "$commit_sha"
}

# Get local commit SHA
get_local_commit() {
  cd "$REPO_ROOT"
  git rev-parse HEAD
}

# Get commit details from GitHub
get_commit_details() {
  local commit_sha="$1"
  local api_url="https://api.github.com/repos/$GITHUB_REPO/commits/$commit_sha"
  
  curl -s -H "Accept: application/vnd.github.v3+json" "$api_url" 2>/dev/null
}

# Main check logic
main() {
  # Verify we're in a git repo
  if [[ ! -d "$REPO_ROOT/.git" ]]; then
    [[ "$QUIET" == false ]] && echo "Error: Not a git repository" >&2
    exit 2
  fi
  
  detect_github_repo
  
  [[ "$QUIET" == false ]] && echo "Checking for updates..."
  [[ "$QUIET" == false ]] && echo "  Repository: $GITHUB_REPO"
  [[ "$QUIET" == false ]] && echo "  Branch: $CHECK_BRANCH"
  
  local local_commit remote_commit
  local_commit=$(get_local_commit)
  remote_commit=$(get_remote_commit)
  
  if [[ "$QUIET" == false ]]; then
    echo ""
    echo "Local commit:  ${local_commit:0:7}"
    echo "Remote commit: ${remote_commit:0:7}"
  fi
  
  if [[ "$local_commit" == "$remote_commit" ]]; then
    if [[ "$QUIET" == false ]]; then
      echo ""
      echo -e "${GREEN}✓ Up to date!${NC} No updates available."
    fi
    exit 0
  else
    # Get more details about the update
    local commit_info commit_message commit_date commit_author
    commit_info=$(get_commit_details "$remote_commit")
    commit_message=$(echo "$commit_info" | grep -o '"message": "[^"]*"' | head -1 | cut -d'"' -f4 | head -1)
    commit_date=$(echo "$commit_info" | grep -o '"date": "[^"]*"' | head -1 | cut -d'"' -f4)
    commit_author=$(echo "$commit_info" | grep -o '"login": "[^"]*"' | head -1 | cut -d'"' -f4)
    
    if [[ "$QUIET" == true ]]; then
      exit 1
    elif [[ "$NOTIFY" == true ]]; then
      echo "Update available: $commit_message (${remote_commit:0:7})"
      exit 1
    else
      echo ""
      echo -e "${YELLOW}⬆ Update available!${NC}"
      echo ""
      echo "Latest commit:"
      echo "  SHA:    ${remote_commit:0:7}"
      echo "  Author: $commit_author"
      echo "  Date:   $commit_date"
      echo "  Message: $commit_message"
      echo ""
      echo "To update, run:"
      echo "  ./deploy/scripts/update_vps.sh        # For VPS (broker + bots)"
      echo "  ./deploy/scripts/update_runner_wsl.sh # For WSL runner"
      echo "  ./deploy/scripts/update_runner_jetson.sh # For Jetson runner"
      echo ""
      echo "Or for automatic updates, run:"
      echo "  ./deploy/scripts/auto_update.sh"
      exit 1
    fi
  fi
}

main
