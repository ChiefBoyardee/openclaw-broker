#!/usr/bin/env bash
# HuggingFace GGUF Model Switcher for OpenClaw
# 
# This script provides a convenient CLI wrapper around switch_model.py
# for WSL users. It automatically finds and activates the appropriate
# Python virtual environment.
#
# Usage:
#   ./scripts/switch-model.sh <model_id_or_url> [options]
#
# Examples:
#   ./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF
#   ./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF --quant Q4_K_M
#   ./scripts/switch-model.sh https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF
#   ./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF --dry-run
#   ./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF --no-restart
#
# Options:
#   --quant Q4_K_M    Specify quantization (e.g., Q4_K_M, Q5_K_M, Q8_0)
#   --dry-run, -n     Preview changes without downloading
#   --no-restart      Skip restarting the llama.cpp server
#   --yes, -y         Skip confirmation prompts
#   --server-env      Path to server.env (auto-detected by default)
#   --runner-env      Path to runner.env (auto-detected by default)
#   --help, -h        Show this help message

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Self-healing: ensure scripts are executable (git may reset permissions)
if [[ ! -x "$SCRIPT_DIR/switch_model.py" ]]; then
    chmod +x "$SCRIPT_DIR/switch_model.py" 2>/dev/null || true
fi
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m' # No Color

# Print functions
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }
dim() { echo -e "${DIM}$1${NC}"; }

# Show help
show_help() {
    cat << 'EOF'
HuggingFace GGUF Model Switcher for OpenClaw

USAGE:
    ./scripts/switch-model.sh <model_id_or_url> [OPTIONS]

ARGUMENTS:
    model_id_or_url     HuggingFace model ID (e.g., Qwen/Qwen3-8B-GGUF)
                        or full URL (e.g., https://huggingface.co/owner/model)

OPTIONS:
    --quant Q4_K_M      Specific quantization to download (e.g., Q4_K_M, Q5_K_M, Q8_0)
    --dry-run, -n       Preview changes without downloading or modifying files
    --no-restart        Skip restarting the llama.cpp server
    --yes, -y           Skip confirmation prompts
    --server-env PATH   Path to server.env (auto-detected if not provided)
    --runner-env PATH   Path to runner.env (auto-detected if not provided)
    --help, -h          Show this help message

ENVIRONMENT:
    The script automatically detects and uses:
      - User install: ~/.local/llama-cpp-server/venv/
      - System install: /opt/llama-cpp-server/venv/

EXAMPLES:
    # Interactive mode - lists available GGUFs and prompts for selection
    ./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF

    # Auto-download specific quantization
    ./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF --quant Q4_K_M

    # Full URL support
    ./scripts/switch-model.sh https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF

    # Dry run (preview changes without applying)
    ./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF --dry-run

    # Skip server restart
    ./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF --no-restart

    # Non-interactive mode
    ./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF --quant Q4_K_M --yes

AFTER INSTALLATION:
    The script updates:
      - server.env (LLAMA_MODEL)
      - runner.env (LLM_MODEL, if exists)

    To test the new model:
      ~/.local/llama-cpp-server/test-server.sh
      # or
      /opt/llama-cpp-server/test-server.sh

For more help, see:
    docs/LLM_SETUP_GUIDE.md (if available)
EOF
}

# Check if help requested
if [[ $# -eq 0 ]] || [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
    show_help
    exit 0
fi

# Find Python virtual environment
find_python() {
    # Check for user-mode install first
    USER_VENV="$HOME/.local/llama-cpp-server/venv"
    if [[ -d "$USER_VENV" ]]; then
        echo "$USER_VENV/bin/python"
        return 0
    fi

    # Check for system install
    SYSTEM_VENV="/opt/llama-cpp-server/venv"
    if [[ -d "$SYSTEM_VENV" ]]; then
        echo "$SYSTEM_VENV/bin/python"
        return 0
    fi

    # Fall back to system python
    if command -v python3 &> /dev/null; then
        echo "python3"
        return 0
    fi

    error "Could not find Python. Please install Python 3.8+ or run setup_llama_cpp.sh first."
    exit 1
}

# Find the Python script
PYTHON_SCRIPT="$SCRIPT_DIR/switch_model.py"
if [[ ! -f "$PYTHON_SCRIPT" ]]; then
    error "switch_model.py not found at $PYTHON_SCRIPT"
    exit 1
fi

# Get Python interpreter
PYTHON=$(find_python)
info "Using Python: $PYTHON"

# Check huggingface_hub is available
if ! "$PYTHON" -c "import huggingface_hub" 2>/dev/null; then
    warn "huggingface_hub not found in Python environment"
    info "Attempting to install..."
    "$PYTHON" -m pip install huggingface-hub --quiet || {
        error "Failed to install huggingface_hub. Please run:"
        error "  $PYTHON -m pip install huggingface-hub"
        exit 1
    }
    success "Installed huggingface-hub"
fi

# Run the Python script with all arguments
exec "$PYTHON" "$PYTHON_SCRIPT" "$@"
