#!/usr/bin/env bash
# Setup llama-cpp-python server for OpenClaw runner (WSL or Linux worker).
# This script installs llama-cpp-python[server], creates model directory, and
# optionally downloads a recommended GGUF model.
#
# Usage:
#   ./deploy/scripts/setup_llama_cpp.sh              # Interactive setup
#   ./deploy/scripts/setup_llama_cpp.sh --build-from-source  # Build latest llama.cpp from source (for new model support)
#   MODEL_PATH=/path/to/mymodel.gguf ./deploy/scripts/setup_llama_cpp.sh  # Use existing model
#
# The script creates:
#   - /opt/llama-cpp-server/venv  (virtual environment)
#   - /opt/models/                (model storage directory; or ~/.local/share/openclaw-models in --user mode)
#   - systemd service (if --systemd flag provided)
#
# IMPORTANT: --build-from-source uses the JamePeng fork which maintains
# synchronized API bindings with latest llama.cpp. The main abetlen repo
# has outdated bindings causing "undefined symbol: llama_get_kv_self" errors
# when used with newer llama.cpp versions (required for Qwen3.5 models).
# See: https://github.com/abetlen/llama-cpp-python/issues/2074

set -e

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

# Build configuration
BUILD_FROM_SOURCE=false
WITH_SYSTEMD=false

# Configuration
LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-/opt/llama-cpp-server}"
MODELS_DIR="${MODELS_DIR:-/opt/models}"
LLAMA_LOG_DIR="${LLAMA_LOG_DIR:-/var/log/llama-cpp-server}"
VENV_NAME="venv"

# Default model (Qwen2.5-Coder-Instruct 7B Q4_K_M - good balance of quality/speed)
DEFAULT_MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf"
DEFAULT_MODEL_NAME="qwen2.5-coder-7b-instruct-q4_k_m.gguf"

# GPU configuration
N_GPU_LAYERS="${N_GPU_LAYERS:-35}"
N_CTX="${N_CTX:-8192}"
SERVER_PORT="${SERVER_PORT:-8000}"

echo "[setup_llama_cpp] ============================================"
echo "[setup_llama_cpp] OpenClaw llama.cpp Server Setup"
echo "[setup_llama_cpp] ============================================"
echo ""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --user)
      INSTALL_MODE="user"
      shift
      ;;
    --systemd)
      WITH_SYSTEMD=true
      shift
      ;;
    --build-from-source)
      BUILD_FROM_SOURCE=true
      shift
      ;;
    --help|-h)
      cat << 'EOF'
Usage: setup_llama_cpp.sh [OPTIONS]

Setup llama-cpp-python server for OpenClaw runner.

OPTIONS:
    --user                User-mode install (no sudo, installs to ~/.local)
    --systemd             Install systemd service (system mode only)
    --build-from-source   Build llama-cpp-python from source with latest llama.cpp
                          Required for Qwen3.5 models and other new architectures
    --help                Show this help message

ENVIRONMENT VARIABLES:
    MODEL_PATH            Path to existing GGUF model to use
    N_GPU_LAYERS          GPU layers to offload (default: 35, 0 for CPU)
    N_CTX                 Context size in tokens (default: 8192)
    SERVER_PORT           Server port (default: 8000)

EXAMPLES:
    # Standard pip install (may not support latest models)
    ./deploy/scripts/setup_llama_cpp.sh

    # Build from source for Qwen3.5 support
    ./deploy/scripts/setup_llama_cpp.sh --build-from-source

    # User-mode with source build
    ./deploy/scripts/setup_llama_cpp.sh --user --build-from-source

    # Use existing model
    MODEL_PATH=/path/to/model.gguf ./deploy/scripts/setup_llama_cpp.sh

Note: --build-from-source requires git and build tools (cmake, C++ compiler).
For CUDA support, set: export CMAKE_ARGS="-DGGML_CUDA=ON"
EOF
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      echo "Use --help for usage information" >&2
      exit 1
      ;;
    *)
      shift
      ;;
  esac
done

# Check if running as root for system-wide install
if [[ "$INSTALL_MODE" == "user" ]]; then
  LLAMA_CPP_DIR="${HOME}/.local/llama-cpp-server"
  MODELS_DIR="${HOME}/.local/share/openclaw-models"
  LLAMA_LOG_DIR="${HOME}/.local/state/llama-cpp-server"
  echo "[setup_llama_cpp] User-mode install (no sudo required)"
else
  INSTALL_MODE="system"
  echo "[setup_llama_cpp] System-wide install (may require sudo)"
fi

# Create directories
echo "[setup_llama_cpp] Creating directories..."
mkdir -p "$LLAMA_CPP_DIR"
mkdir -p "$MODELS_DIR"
mkdir -p "$LLAMA_LOG_DIR"

# Create virtual environment
echo "[setup_llama_cpp] Setting up Python virtual environment..."
if [[ ! -d "$LLAMA_CPP_DIR/$VENV_NAME" ]]; then
  python3 -m venv "$LLAMA_CPP_DIR/$VENV_NAME"
  echo "[setup_llama_cpp] Created venv at $LLAMA_CPP_DIR/$VENV_NAME"
fi

# Install llama-cpp-python with server support
echo "[setup_llama_cpp] Installing llama-cpp-python[server]..."
"$LLAMA_CPP_DIR/$VENV_NAME/bin/pip" install --upgrade pip

if [[ "$BUILD_FROM_SOURCE" == true ]]; then
  echo "[setup_llama_cpp] Building llama-cpp-python from source with latest llama.cpp..."
  echo "[setup_llama_cpp] This is required for Qwen3.5 and other new model architectures."
  echo "[setup_llama_cpp] Note: This requires git, cmake, and a C++ compiler."
  
  # Check for required tools
  if ! command -v git &> /dev/null; then
    echo "[setup_llama_cpp] ERROR: git is required for --build-from-source but not found." >&2
    exit 1
  fi
  
  # Create source directory
  SOURCE_DIR="$LLAMA_CPP_DIR/src"
  mkdir -p "$SOURCE_DIR"
  
  # Clone or update the repository
  if [[ -d "$SOURCE_DIR/llama-cpp-python/.git" ]]; then
    echo "[setup_llama_cpp] Updating existing llama-cpp-python source..."
    cd "$SOURCE_DIR/llama-cpp-python"
    
    # Check if we need to switch remotes (from abetlen to JamePeng fork)
    CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
    if [[ "$CURRENT_REMOTE" == *"abetlen"* ]]; then
      echo "[setup_llama_cpp] Switching to JamePeng fork for API compatibility..."
      git remote set-url origin https://github.com/JamePeng/llama-cpp-python.git
      git fetch origin
      git checkout main || git checkout master
      git reset --hard origin/main 2>/dev/null || git reset --hard origin/master
    else
      git fetch origin
      git checkout main || git checkout master
      git pull
    fi
    
    git submodule update --remote vendor/llama.cpp
  else
    echo "[setup_llama_cpp] Cloning llama-cpp-python repository..."
    rm -rf "$SOURCE_DIR/llama-cpp-python"
    # Use JamePeng fork for API compatibility with latest llama.cpp
    # The abetlen repo has outdated bindings causing "undefined symbol: llama_get_kv_self" errors
    git clone --recursive https://github.com/JamePeng/llama-cpp-python.git "$SOURCE_DIR/llama-cpp-python"
    cd "$SOURCE_DIR/llama-cpp-python"
    # Update to latest llama.cpp (this gets qwen35 support)
    git submodule update --remote vendor/llama.cpp
  fi
  
  # Patch mtmd CMakeLists.txt to fix build error
  MTMD_CMAKELISTS="$SOURCE_DIR/llama-cpp-python/vendor/llama.cpp/tools/mtmd/CMakeLists.txt"
  if [[ -f "$MTMD_CMAKELISTS" ]]; then
    echo "[setup_llama_cpp] Patching mtmd CMakeLists.txt to fix build error..."
    # The error is due to PUBLIC_HEADER being set to an empty or invalid value
    # Remove or fix the PUBLIC_HEADER property that's causing issues
    sed -i '/PUBLIC_HEADER.*mtmd.h/d' "$MTMD_CMAKELISTS" 2>/dev/null || true
  fi
  
  # Build and install
  echo "[setup_llama_cpp] Building llama-cpp-python from source..."
  cd "$SOURCE_DIR/llama-cpp-python"
  
  # Set build environment
  export FORCE_CMAKE=1
  # Allow user to set CMAKE_ARGS for CUDA, etc.
  # Add -DLLAVA_BUILD=OFF to disable problematic llava/mtmd builds
  if [[ -n "$CMAKE_ARGS" ]]; then
    echo "[setup_llama_cpp] Using CMAKE_ARGS: $CMAKE_ARGS -DLLAVA_BUILD=OFF"
    export CMAKE_ARGS="$CMAKE_ARGS -DLLAVA_BUILD=OFF"
  else
    export CMAKE_ARGS="-DLLAVA_BUILD=OFF"
  fi
  
  # Install the package
  "$LLAMA_CPP_DIR/$VENV_NAME/bin/pip" install . --upgrade --force-reinstall --no-cache-dir || {
    echo "[setup_llama_cpp] ERROR: Failed to build from source. Falling back to pip install..." >&2
    "$LLAMA_CPP_DIR/$VENV_NAME/bin/pip" install llama-cpp-python[server]
  }
  
  # Record that we built from source
  echo "source" > "$LLAMA_CPP_DIR/install_type.txt"
  echo "[setup_llama_cpp] Source build complete!"
else
  echo "[setup_llama_cpp] Installing llama-cpp-python[server] from pip..."
  echo "[setup_llama_cpp] Note: Use --build-from-source for Qwen3.5 model support."
  "$LLAMA_CPP_DIR/$VENV_NAME/bin/pip" install llama-cpp-python[server]
  echo "pip" > "$LLAMA_CPP_DIR/install_type.txt"
fi

# Install huggingface-hub for model downloads
"$LLAMA_CPP_DIR/$VENV_NAME/bin/pip" install huggingface-hub

echo ""
echo "[setup_llama_cpp] ============================================"
echo "[setup_llama_cpp] Model Setup"
echo "[setup_llama_cpp] ============================================"
echo ""

# Determine model path
if [[ -n "$MODEL_PATH" ]]; then
  # User provided a model path
  if [[ ! -f "$MODEL_PATH" ]]; then
    echo "[setup_llama_cpp] ERROR: Model not found at $MODEL_PATH" >&2
    exit 1
  fi
  MODEL_FILENAME=$(basename "$MODEL_PATH")
  # Copy to models dir if not already there
  if [[ "$MODEL_PATH" != "$MODELS_DIR/$MODEL_FILENAME" ]]; then
    echo "[setup_llama_cpp] Copying model to $MODELS_DIR/$MODEL_FILENAME..."
    cp "$MODEL_PATH" "$MODELS_DIR/$MODEL_FILENAME"
  fi
  MODEL_NAME="$MODEL_FILENAME"
  echo "[setup_llama_cpp] Using provided model: $MODEL_NAME"
else
  # Check if user already has models in the target model directory
  EXISTING_MODELS=$(find "$MODELS_DIR" -name "*.gguf" -type f 2>/dev/null || true)
  if [[ -n "$EXISTING_MODELS" ]]; then
    echo "[setup_llama_cpp] Found existing GGUF models in $MODELS_DIR:"
    echo "$EXISTING_MODELS" | while read -r model; do
      echo "  - $(basename "$model")"
    done
    echo ""
    echo "[setup_llama_cpp] Use MODEL_PATH=$MODELS_DIR/<model.gguf> to use an existing model."
    echo "[setup_llama_cpp] Or continue to download a recommended model."
    echo ""
  fi
  
  echo "Download recommended model?"
  echo "  Model: $DEFAULT_MODEL_NAME"
  echo "  Size: ~4.5GB"
  echo "  Source: HuggingFace (Qwen/Qwen2.5-Coder-7B-Instruct-GGUF)"
  echo ""
  echo "Options:"
  echo "  [d] Download recommended model (default)"
  echo "  [s] Skip (you have your own model)"
  echo "  [u] Enter custom HuggingFace URL"
  read -r -p "Choice [d/s/u]: " CHOICE
  CHOICE=${CHOICE:-d}
  
  case "$CHOICE" in
    d|D|"" )
      echo "[setup_llama_cpp] Downloading $DEFAULT_MODEL_NAME..."
      echo "[setup_llama_cpp] This may take 5-15 minutes depending on connection..."
      "$LLAMA_CPP_DIR/$VENV_NAME/bin/python" -c "
from huggingface_hub import hf_hub_download
hf_hub_download(repo_id='Qwen/Qwen2.5-Coder-7B-Instruct-GGUF', filename='$DEFAULT_MODEL_NAME', local_dir='$MODELS_DIR', local_dir_use_symlinks=False)
"
      MODEL_NAME="$DEFAULT_MODEL_NAME"
      ;;
    s|S )
      echo "[setup_llama_cpp] Skipping download. Please place your .gguf model in $MODELS_DIR"
      echo "[setup_llama_cpp] and re-run with MODEL_PATH=$MODELS_DIR/your-model.gguf"
      MODEL_NAME=""
      ;;
    u|U )
      read -r -p "Enter HuggingFace repo_id (e.g., owner/model-gguf, not a filename): " REPO_ID
      read -r -p "Enter exact filename from the repo (e.g., model-q4_k_m.gguf): " FILENAME
      echo "[setup_llama_cpp] Downloading $FILENAME from $REPO_ID..."
      "$LLAMA_CPP_DIR/$VENV_NAME/bin/python" -c "
from huggingface_hub import hf_hub_download
hf_hub_download(repo_id='$REPO_ID', filename='$FILENAME', local_dir='$MODELS_DIR', local_dir_use_symlinks=False)
"
      MODEL_NAME="$FILENAME"
      ;;
    * )
      echo "[setup_llama_cpp] Invalid choice. Exiting." >&2
      exit 1
      ;;
  esac
fi

# Create server wrapper script
echo ""
echo "[setup_llama_cpp] ============================================"
echo "[setup_llama_cpp] Creating Server Scripts"
echo "[setup_llama_cpp] ============================================"
echo ""

cat > "$LLAMA_CPP_DIR/start-server.sh" << 'SCRIPT'
#!/usr/bin/env bash
# Start llama-cpp-python server with configured model
# Usage: start-server.sh [model.gguf] [port]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load from environment file if it exists
if [[ -f "$SCRIPT_DIR/server.env" ]]; then
  set -a
  source "$SCRIPT_DIR/server.env"
  set +a
fi

MODELS_DIR="${MODELS_DIR:-/opt/models}"

MODEL_NAME="${1:-$LLAMA_MODEL}"
PORT="${2:-${LLAMA_PORT:-8000}}"
N_GPU_LAYERS="${LLAMA_N_GPU_LAYERS:-35}"
N_CTX="${LLAMA_N_CTX:-8192}"

if [[ -z "$MODEL_NAME" ]]; then
  echo "ERROR: No model specified. Set LLAMA_MODEL in server.env or pass as argument." >&2
  echo "Usage: $0 <model.gguf> [port]" >&2
  exit 1
fi

MODEL_PATH="$MODELS_DIR/$MODEL_NAME"
if [[ ! -f "$MODEL_PATH" ]]; then
  echo "ERROR: Model not found at $MODEL_PATH" >&2
  exit 1
fi

echo "Starting llama.cpp server..."
echo "  Model: $MODEL_NAME"
echo "  Path: $MODEL_PATH"
echo "  Port: $PORT"
echo "  GPU layers: $N_GPU_LAYERS"
echo "  Context: $N_CTX"
echo ""

exec "$SCRIPT_DIR/venv/bin/python" -m llama_cpp.server \
  --model "$MODEL_PATH" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --n_ctx "$N_CTX" \
  --n_gpu_layers "$N_GPU_LAYERS" \
  --chat_format chatml
SCRIPT

chmod +x "$LLAMA_CPP_DIR/start-server.sh"

# Create server environment file
if [[ -n "$MODEL_NAME" ]]; then
  cat > "$LLAMA_CPP_DIR/server.env" << EOF
# llama.cpp server configuration
# Generated by setup_llama_cpp.sh

LLAMA_MODEL=$MODEL_NAME
LLAMA_PORT=$SERVER_PORT
LLAMA_N_GPU_LAYERS=$N_GPU_LAYERS
LLAMA_N_CTX=$N_CTX
MODELS_DIR=$MODELS_DIR
LLAMA_LOG_DIR=$LLAMA_LOG_DIR
EOF
  echo "[setup_llama_cpp] Created $LLAMA_CPP_DIR/server.env"
fi

# Create test script
cat > "$LLAMA_CPP_DIR/test-server.sh" << 'SCRIPT'
#!/usr/bin/env bash
# Test if llama.cpp server is running and responding

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment
if [[ -f "$SCRIPT_DIR/server.env" ]]; then
  set -a
  source "$SCRIPT_DIR/server.env"
  set +a
fi

PORT="${LLAMA_PORT:-8000}"
MODEL="${LLAMA_MODEL:-unknown}"

echo "Testing llama.cpp server on port $PORT..."
echo ""

# Test /models endpoint
echo "1. Checking /v1/models endpoint..."
MODELS_RESPONSE=$(curl -s "http://127.0.0.1:$PORT/v1/models" 2>/dev/null || echo "")
if [[ -n "$MODELS_RESPONSE" ]]; then
  echo "   Server is running! Available models:"
  echo "$MODELS_RESPONSE" | grep -o '"id":"[^"]*"' | sed 's/"id":"/   - /;s/"$//' || true
else
  echo "   Server not responding. Is it running?"
  exit 1
fi

echo ""
echo "2. Testing chat completion..."
TEST_RESPONSE=$(curl -s "http://127.0.0.1:$PORT/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"'"$MODEL"'","messages":[{"role":"user","content":"Say hello in one word"}]}' 2>/dev/null || echo "")

if [[ -n "$TEST_RESPONSE" ]]; then
  CONTENT=$(echo "$TEST_RESPONSE" | grep -o '"content":"[^"]*"' | head -1 | sed 's/"content":"//;s/"$//' || echo "(no content)")
  echo "   Response: $CONTENT"
  echo ""
  echo "Server is working correctly!"
else
  echo "   No response from chat completions endpoint"
  exit 1
fi
SCRIPT

chmod +x "$LLAMA_CPP_DIR/test-server.sh"

# Install systemd service if requested and in system mode
if [[ "$WITH_SYSTEMD" == true && "$INSTALL_MODE" == "system" ]]; then
  echo "[setup_llama_cpp] Installing systemd service..."
  
  if [[ -d /etc/systemd/system ]]; then
    sed -e "s|LLAMA_CPP_DIR_PLACEHOLDER|$LLAMA_CPP_DIR|g" \
        -e "s|MODELS_DIR_PLACEHOLDER|$MODELS_DIR|g" \
        "$REPO_ROOT/deploy/systemd/llama-cpp-server.service.template" \
        > /etc/systemd/system/llama-cpp-server.service
    
    systemctl daemon-reload
    echo "[setup_llama_cpp] Created /etc/systemd/system/llama-cpp-server.service"
    echo "[setup_llama_cpp] Start with: sudo systemctl start llama-cpp-server"
    echo "[setup_llama_cpp] Enable on boot: sudo systemctl enable llama-cpp-server"
  else
    echo "[setup_llama_cpp] Warning: /etc/systemd/system not found, skipping systemd setup"
  fi
fi

echo ""
echo "[setup_llama_cpp] ============================================"
echo "[setup_llama_cpp] Setup Complete!"
echo "[setup_llama_cpp] ============================================"
echo ""
echo "Installation directory: $LLAMA_CPP_DIR"
echo "Models directory: $MODELS_DIR"
echo "Log directory: $LLAMA_LOG_DIR"
echo ""

if [[ -n "$MODEL_NAME" ]]; then
  echo "Model configured: $MODEL_NAME"
  echo ""
  echo "To start the server:"
  echo "  $LLAMA_CPP_DIR/start-server.sh"
  echo ""
  echo "To test the server:"
  echo "  $LLAMA_CPP_DIR/test-server.sh"
  echo ""
  echo "Server will run on: http://127.0.0.1:$SERVER_PORT/v1"
  echo ""
  echo "Configure OpenClaw runner with:"
  echo "  LLM_BASE_URL=http://127.0.0.1:$SERVER_PORT/v1"
  echo "  LLM_MODEL=$MODEL_NAME"
else
  echo "No model downloaded. To use your own model:"
  echo "  1. Copy .gguf file to $MODELS_DIR"
  echo "  2. Run: MODEL_PATH=$MODELS_DIR/your-model.gguf $0"
  echo ""
fi

if [[ "$INSTALL_MODE" == "system" ]]; then
  echo "File permissions:"
  echo "  sudo chown -R \$USER:\$USER $LLAMA_CPP_DIR"
  echo "  sudo chown -R \$USER:\$USER $MODELS_DIR"
fi

echo ""
echo "For help and examples, see:"
echo "  - deploy/env.examples/runner-llamacpp.env.example"
echo "  - docs/LLM_SETUP_GUIDE.md (if available)"
echo ""
