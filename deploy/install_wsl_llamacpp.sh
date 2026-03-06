#!/usr/bin/env bash
# OpenClaw WSL worker installation with llama.cpp (GGUF) support
#
# This script automates the complete setup of an OpenClaw worker on WSL:
#   1. Installs the OpenClaw runner
#   2. Sets up llama-cpp-python server with GGUF model support
#   3. Configures the runner to use the llama.cpp server
#   4. Creates systemd services (optional)
#
# Prerequisites:
#   - Broker must be set up first (run ./deploy/onboard_broker.sh on your VPS)
#   - WSL with Python 3.8+ and internet access
#   - Git repo cloned locally
#   - For --build-from-source: git, cmake, and C++ compiler installed
#
# Usage:
#   # Interactive mode (prompts for broker URL, tokens, etc.)
#   ./deploy/install_wsl_llamacpp.sh
#
#   # With pre-set environment variables (fully automated)
#   BROKER_URL=http://100.x.x.x:8443 \
#   WORKER_TOKEN=your_token_here \
#   MODEL_PATH=/path/to/your-model.gguf \
#   ./deploy/install_wsl_llamacpp.sh --auto
#
#   # User-mode install (no sudo, installs to ~/.local)
#   ./deploy/install_wsl_llamacpp.sh --user
#
#   # Build from source for Qwen3.5 model support
#   ./deploy/install_wsl_llamacpp.sh --build-from-source
#
# Environment Variables:
#   BROKER_URL        - Broker URL (e.g., http://100.x.x.x:8443)
#   WORKER_TOKEN      - Worker token from broker setup
#   MODEL_PATH        - Path to existing GGUF model (optional)
#   INSTALL_MODE      - "system" (default) or "user"
#   LLAMA_N_GPU_LAYERS - GPU layers to offload (default: 35, set 0 for CPU)
#
# After installation:
#   - Start server: ~/.local/llama-cpp-server/start-server.sh (or /opt/llama-cpp-server/start-server.sh)
#   - Test server: ~/.local/llama-cpp-server/test-server.sh
#   - Start runner: cd <repo> && RUNNER_ENV=<repo>/runner/runner.env runner/start.sh
#
# For help: ./deploy/install_wsl_llamacpp.sh --help

set -e

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SCRIPT_NAME="$(basename "$0")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
INSTALL_MODE="${INSTALL_MODE:-system}"
AUTO_MODE=false
WITH_SYSTEMD=false
WITH_BUILDFROM_SOURCE=false

# Print colored output
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# Show help
show_help() {
  cat << EOF
OpenClaw WSL Worker Installation with llama.cpp (GGUF) support

USAGE:
    $SCRIPT_NAME [OPTIONS]

OPTIONS:
    --auto               Fully automated mode (requires env vars set)
    --user               User-mode install (no sudo, ~/.local)
    --systemd            Install and enable systemd services
    --build-from-source  Build llama-cpp-python from source (required for Qwen3.5)
    --help               Show this help message

ENVIRONMENT VARIABLES (for --auto mode):
    BROKER_URL          Broker URL (required)
    WORKER_TOKEN        Worker token from broker (required)
    MODEL_PATH          Path to existing GGUF model (optional)
    LLAMA_N_GPU_LAYERS  GPU layers (default: 35, 0 for CPU)
    WORKER_ID           Worker identifier (default: hostname-llamacpp)
    CMAKE_ARGS          Build flags for source build (e.g., "-DGGML_CUDA=ON" for CUDA)

EXAMPLES:
    # Interactive installation
    ./deploy/install_wsl_llamacpp.sh

    # Fully automated with environment variables
    BROKER_URL=http://100.64.0.1:8443 WORKER_TOKEN=abc123 ./deploy/install_wsl_llamacpp.sh --auto

    # User-mode with existing model
    MODEL_PATH=~/models/mymodel.gguf ./deploy/install_wsl_llamacpp.sh --user

    # System install with systemd services
    ./deploy/install_wsl_llamacpp.sh --systemd

    # Build from source for Qwen3.5 model support
    CMAKE_ARGS="-DGGML_CUDA=ON" ./deploy/install_wsl_llamacpp.sh --build-from-source

PREREQUISITES:
    - WSL with Python 3.8+ installed
    - Broker must be running (run onboard_broker.sh first)
    - 4GB+ free disk space for model download
    - For GPU: CUDA drivers installed in WSL

AFTER INSTALLATION:
    1. Start the llama.cpp server:
       sudo systemctl start llama-cpp-server   (if using systemd)
       OR
       ~/.local/llama-cpp-server/start-server.sh  (manual start for --user)
       OR
       /opt/llama-cpp-server/start-server.sh      (manual start for system mode)

    2. Start the OpenClaw runner:
       cd $REPO_ROOT && RUNNER_ENV=$REPO_ROOT/runner/runner.env runner/start.sh

    3. Test from Discord:
       ask llamacpp: Hello!

For more help, see:
    - deploy/env.examples/runner-llamacpp.env.example
    - docs/INSTALLATION_GUIDE.md
EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --auto)
      AUTO_MODE=true
      shift
      ;;
    --user)
      INSTALL_MODE=user
      shift
      ;;
    --systemd)
      WITH_SYSTEMD=true
      shift
      ;;
    --build-from-source)
      WITH_BUILDFROM_SOURCE=true
      shift
      ;;
    --help|-h)
      show_help
      exit 0
      ;;
    *)
      error "Unknown option: $1"
      show_help
      exit 1
      ;;
  esac
done

if [[ "$INSTALL_MODE" == "user" ]]; then
  LLAMA_CPP_DIR="${HOME}/.local/llama-cpp-server"
  MODELS_DIR="${HOME}/.local/share/openclaw-models"
  SERVER_LOG_DIR="${HOME}/.local/state/llama-cpp-server"
  RUNNER_LOG_DIR_PATH="${HOME}/.local/state/openclaw-runner"
else
  LLAMA_CPP_DIR="/opt/llama-cpp-server"
  MODELS_DIR="/opt/models"
  SERVER_LOG_DIR="/var/log/llama-cpp-server"
  RUNNER_LOG_DIR_PATH="/var/log/openclaw-runner"
fi
RUNNER_ENV_PATH="${REPO_ROOT}/runner/runner.env"
SERVER_ENV_PATH="${LLAMA_CPP_DIR}/server.env"

# Check prerequisites
check_prerequisites() {
  info "Checking prerequisites..."
  
  # Check Python
  if ! command -v python3 &> /dev/null; then
    error "python3 is not installed. Please install Python 3.8+ first."
    exit 1
  fi
  
  PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
  info "Python version: $PYTHON_VERSION"
  if ! python3 -m venv --help >/dev/null 2>&1; then
    error "python3 venv support is missing. Install the Python venv package for your distro first."
    exit 1
  fi
  if ! command -v curl &> /dev/null; then
    error "curl is not installed. Please install curl first."
    exit 1
  fi
  if [[ "$WITH_SYSTEMD" == true ]] && ! command -v systemctl >/dev/null 2>&1; then
    error "--systemd was requested, but systemctl is not available on this machine."
    exit 1
  fi
  if [[ "$WITH_SYSTEMD" == true && "$INSTALL_MODE" == "user" ]]; then
    error "--systemd cannot be combined with --user. Use system mode for systemd installs."
    exit 1
  fi
  
  # Check if we're in WSL (optional but helpful)
  if [[ -f /proc/version ]] && grep -q Microsoft /proc/version; then
    info "Detected WSL environment"
  fi
  
  # Check repo structure
  if [[ ! -f "$REPO_ROOT/runner/runner.py" ]]; then
    error "OpenClaw runner not found at $REPO_ROOT/runner/runner.py"
    error "Please run this script from the repo root."
    exit 1
  fi
  
  success "Prerequisites OK"
}

# Get configuration (interactive or from env)
get_configuration() {
  info "Configuration..."
  
  if [[ "$AUTO_MODE" == true ]]; then
    # Use environment variables
    if [[ -z "$BROKER_URL" || -z "$WORKER_TOKEN" ]]; then
      error "BROKER_URL and WORKER_TOKEN must be set in --auto mode"
      exit 1
    fi
    info "Using environment variables for configuration"
  else
    # Interactive mode
    echo ""
    echo "========================================"
    echo "OpenClaw WSL Worker Setup"
    echo "========================================"
    echo ""
    echo "Enter values from your broker setup (run ./deploy/onboard_broker.sh on VPS)"
    echo ""
    
    if [[ -z "$BROKER_URL" ]]; then
      read -r -p "BROKER_URL (e.g., http://100.x.x.x:8443): " BROKER_URL
    fi
    
    if [[ -z "$WORKER_TOKEN" ]]; then
      read -rs -p "WORKER_TOKEN: " WORKER_TOKEN
      echo ""
    fi
    
    if [[ -z "$WORKER_ID" ]]; then
      DEFAULT_ID="$(hostname)-llamacpp"
      read -r -p "WORKER_ID [$DEFAULT_ID]: " WORKER_ID
      WORKER_ID="${WORKER_ID:-$DEFAULT_ID}"
    fi
    
    echo ""
    echo "GPU Configuration (for llama.cpp):"
    if [[ -z "$LLAMA_N_GPU_LAYERS" ]]; then
      read -r -p "GPU layers to offload (0 for CPU-only, 35 for typical GPU) [35]: " LLAMA_N_GPU_LAYERS
      LLAMA_N_GPU_LAYERS="${LLAMA_N_GPU_LAYERS:-35}"
    fi
    
    # Validate
    if [[ -z "$BROKER_URL" || -z "$WORKER_TOKEN" ]]; then
      error "BROKER_URL and WORKER_TOKEN are required"
      exit 1
    fi
  fi
  
  # Set defaults
  WORKER_ID="${WORKER_ID:-$(hostname)-llamacpp}"
  LLAMA_N_GPU_LAYERS="${LLAMA_N_GPU_LAYERS:-35}"
  
  # Clean up BROKER_URL (remove trailing slash)
  BROKER_URL=$(echo "$BROKER_URL" | sed 's|/$||')
  
  success "Configuration complete"
  info "  BROKER_URL: $BROKER_URL"
  info "  WORKER_ID: $WORKER_ID"
  info "  GPU Layers: $LLAMA_N_GPU_LAYERS"
  info "  Runner env path: $RUNNER_ENV_PATH"
  info "  llama.cpp dir: $LLAMA_CPP_DIR"
}

# Install llama.cpp server
install_llama_cpp() {
  info "Setting up llama.cpp server..."
  
  local setup_args=""
  if [[ "$INSTALL_MODE" == "user" ]]; then
    setup_args="--user"
  fi
  if [[ "$WITH_SYSTEMD" == true && "$INSTALL_MODE" == "system" ]]; then
    setup_args="$setup_args --systemd"
  fi
  if [[ "$WITH_BUILDFROM_SOURCE" == true ]]; then
    setup_args="$setup_args --build-from-source"
    info "Building llama-cpp-python from source for latest model support (Qwen3.5+)"
  fi
  
  if [[ -n "$MODEL_PATH" ]]; then
    LLAMA_CPP_DIR="$LLAMA_CPP_DIR" MODELS_DIR="$MODELS_DIR" LLAMA_LOG_DIR="$SERVER_LOG_DIR" \
      MODEL_PATH="$MODEL_PATH" "$REPO_ROOT/deploy/scripts/setup_llama_cpp.sh" $setup_args
  else
    LLAMA_CPP_DIR="$LLAMA_CPP_DIR" MODELS_DIR="$MODELS_DIR" LLAMA_LOG_DIR="$SERVER_LOG_DIR" \
      "$REPO_ROOT/deploy/scripts/setup_llama_cpp.sh" $setup_args
  fi
  
  success "llama.cpp server setup complete"
}

# Read a value from the generated llama.cpp server env
get_server_env_value() {
  local key="$1"
  if [[ -f "$SERVER_ENV_PATH" ]]; then
    (
      set -a
      source "$SERVER_ENV_PATH"
      set +a
      eval "printf '%s' \"\${$key:-}\""
    )
  fi
}

# Install OpenClaw runner
install_runner() {
  info "Installing OpenClaw runner..."
  
  export RUNNER_ENV_DIR="$REPO_ROOT/runner"
  export RUNNER_LOG_DIR="$RUNNER_LOG_DIR_PATH"
  bash "$REPO_ROOT/deploy/scripts/install_runner.sh"
  
  success "Runner installation complete"
}

# Configure runner environment
configure_runner() {
  info "Configuring runner environment..."
  
  local model_name
  local server_port
  model_name=$(get_server_env_value "LLAMA_MODEL")
  server_port=$(get_server_env_value "LLAMA_PORT")
  server_port="${server_port:-8000}"
  LLAMA_SERVER_PORT="$server_port"
  
  if [[ -z "$model_name" ]]; then
    warn "No model detected. Using placeholder in runner.env"
    model_name="your-model.gguf"
  fi
  
  # Create runner.env from template
  cat > "$RUNNER_ENV_PATH" << EOF
# Generated by install_wsl_llamacpp.sh â€” do not commit.
# OpenClaw Runner with llama.cpp (GGUF) backend

BROKER_URL="$BROKER_URL"
WORKER_TOKEN="$WORKER_TOKEN"
WORKER_ID="$WORKER_ID"
WORKER_CAPS=llm:llamacpp,repo_tools
RUNNER_LOG_DIR="$RUNNER_LOG_DIR_PATH"

# LLM (OpenAI-compatible llama.cpp server)
LLM_PROVIDER=openai_compat
LLM_BASE_URL=http://127.0.0.1:$server_port/v1
LLM_API_KEY=
LLM_MODEL=$model_name
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=4096
LLM_TOOL_LOOP_MAX_STEPS=6

# Optional: Repo tools configuration
# RUNNER_REPOS_BASE=/home/\$USER/src
# RUNNER_REPO_ALLOWLIST=/etc/openclaw/repos.json

# Poll and timeouts
POLL_INTERVAL_SEC=10
RESULT_TIMEOUT_SEC=300
EOF
  
  success "Created runner configuration: $RUNNER_ENV_PATH"
}

# Create convenience start script
create_start_script() {
  info "Creating convenience scripts..."
  
  local start_all="$REPO_ROOT/start-wsl-worker.sh"
  
  cat > "$start_all" << EOF
#!/usr/bin/env bash
# OpenClaw WSL Worker - Quick Start Script
# Starts both llama.cpp server and OpenClaw runner

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_SCRIPT="$LLAMA_CPP_DIR/start-server.sh"
RUNNER_SCRIPT="$REPO_ROOT/runner/start.sh"
RUNNER_ENV_PATH="$RUNNER_ENV_PATH"
SERVER_LOG_DIR="$SERVER_LOG_DIR"
SERVER_ENV_PATH="$SERVER_ENV_PATH"
PORT="8000"

if [[ -f "$SERVER_ENV_PATH" ]]; then
  set -a
  source "$SERVER_ENV_PATH"
  set +a
  PORT="${LLAMA_PORT:-8000}"
fi

echo "========================================"
echo "Starting OpenClaw WSL Worker"
echo "========================================"
echo ""

# Check if server is already running
if curl -s "http://127.0.0.1:$PORT/v1/models" > /dev/null 2>&1; then
  echo "âœ“ llama.cpp server is already running"
else
  echo "â†’ Starting llama.cpp server..."
  if [[ -f "$SERVER_SCRIPT" ]]; then
    mkdir -p "$SERVER_LOG_DIR"
    # Start in background
    nohup "$SERVER_SCRIPT" > "$SERVER_LOG_DIR/server.log" 2>&1 &
    echo "  Server starting in background (PID: $!)"
    echo "  Logs: $SERVER_LOG_DIR/server.log"
    
    # Wait for server to be ready
    echo "  Waiting for server to start..."
    for i in {1..30}; do
      if curl -s "http://127.0.0.1:$PORT/v1/models" > /dev/null 2>&1; then
        echo "  âœ“ Server is ready!"
        break
      fi
      sleep 1
    done
  else
    echo "  âœ— Server script not found at $SERVER_SCRIPT"
    echo "    Please run ./deploy/scripts/setup_llama_cpp.sh first"
    exit 1
  fi
fi

echo ""
echo "â†’ Starting OpenClaw runner..."
echo "  Press Ctrl+C to stop the runner"
echo ""

# Run via the repo start script so RUNNER_ENV and logging stay consistent
cd "$REPO_ROOT"
exec env RUNNER_ENV="$RUNNER_ENV_PATH" "$RUNNER_SCRIPT"
EOF

  chmod +x "$start_all"
  success "Created start script: $start_all"
}

# Print final instructions
print_instructions() {
  echo ""
  echo "========================================"
  echo "Installation Complete!"
  echo "========================================"
  echo ""
  
  if [[ "$WITH_SYSTEMD" == true && "$INSTALL_MODE" == "system" ]]; then
    echo "Systemd services installed:"
    echo "  llama-cpp-server.service - The GGUF model server"
    echo ""
    echo "Start services:"
    echo "  sudo systemctl start llama-cpp-server"
    echo "  sudo systemctl enable llama-cpp-server  # Start on boot"
    echo ""
  fi
  
  echo "Quick Start:"
  echo "  1. Start the server: $LLAMA_CPP_DIR/start-server.sh"
  echo "     (or use the systemd command above)"
  echo ""
  echo "  2. Test the server: $LLAMA_CPP_DIR/test-server.sh"
  echo ""
  echo "  3. Start the runner: $REPO_ROOT/start-wsl-worker.sh"
  echo "     (or: cd $REPO_ROOT && RUNNER_ENV=$RUNNER_ENV_PATH runner/start.sh)"
  echo ""
  echo "  4. Test from Discord: ask llamacpp: Hello!"
  echo ""
  
  echo "Configuration:"
  echo "  Runner env: $RUNNER_ENV_PATH"
  echo "  Server env: $SERVER_ENV_PATH"
  echo ""
  
  echo "Useful Commands:"
  echo "  View server logs: tail -f $SERVER_LOG_DIR/server.log"
  echo "  Test server: curl http://127.0.0.1:${LLAMA_SERVER_PORT:-8000}/v1/models"
  echo "  Check runner: tail -f $RUNNER_LOG_DIR_PATH/runner.log"
  echo ""
  
  echo "Documentation:"
  echo "  - deploy/env.examples/runner-llamacpp.env.example"
  echo "  - docs/INSTALLATION_GUIDE.md"
  echo ""
}

# Main installation flow
main() {
  echo "========================================"
  echo "OpenClaw WSL Worker + llama.cpp Setup"
  echo "========================================"
  echo ""
  
  check_prerequisites
  get_configuration
  install_llama_cpp
  install_runner
  configure_runner
  create_start_script
  print_instructions
  
  success "All done! Your WSL worker is ready."
}

# Run main
main
