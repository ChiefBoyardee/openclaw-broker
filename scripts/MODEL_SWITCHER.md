# HuggingFace Model Switcher

A tool to automatically download and switch GGUF models from HuggingFace for the OpenClaw llama.cpp server.

## Overview

The model switcher simplifies the process of:
1. Finding available GGUF quantizations in a HuggingFace repository
2. Downloading the selected model
3. Updating environment configuration files
4. Optionally restarting the llama.cpp server

## Usage

### Interactive Mode

Lists available GGUF files and prompts for selection:

```bash
./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF
```

### Auto-Select Quantization

Specify the quantization directly:

```bash
./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF --quant Q4_K_M
```

### Full URL Support

You can also use full HuggingFace URLs:

```bash
./scripts/switch-model.sh https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF
```

### Dry Run

Preview changes without downloading or modifying files:

```bash
./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF --dry-run
```

### Skip Server Restart

Download and update config without restarting the server:

```bash
./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF --no-restart
```

### Non-Interactive Mode

Skip all confirmation prompts:

```bash
./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF --quant Q4_K_M --yes
```

## Features

### Quantization Detection

The tool automatically parses GGUF filenames to extract quantization levels:
- Q4_K_M, Q4_K_S (4-bit, various K-quants)
- Q5_K_M, Q5_K_S (5-bit)
- Q6_K, Q8_0 (higher quality)
- FP16 (unquantized)

### VRAM Estimates

Shows estimated VRAM requirements based on file size plus context overhead (~0.5GB for 8K context).

### Recommendations

Highlights recommended quantizations:
- **Q4_K_M**: Balanced quality and size (recommended for most users)
- **Q5_K_M**: Good quality, moderate size
- **Q6_K**: High quality, larger

### Safety Features

- **Backups**: Automatically backs up `server.env` and `runner.env` before modification
- **Disk Space Check**: Warns if low disk space detected before download
- **Verification**: Verifies downloaded files are non-empty

## Files Modified

The script updates:
- `server.env`: Sets `LLAMA_MODEL` to the downloaded filename
- `runner.env`: Sets `LLM_MODEL` to match (if file exists)

Backup files are created with timestamps (e.g., `server.env.backup.20240310_143022`).

## Environment Detection

The script automatically detects:
- User install: `~/.local/llama-cpp-server/server.env`
- System install: `/opt/llama-cpp-server/server.env`
- Models directory from `server.env` or uses defaults

## Requirements

- Python 3.8+
- `huggingface_hub` library (auto-installed if missing)
- WSL environment (for the bash wrapper)

## Troubleshooting

### Repository Not Found

```
Error: Repository 'owner/model' not found.
```

Make sure:
1. The model ID is correct (format: `owner/model-name`)
2. The repository exists on HuggingFace
3. The repository is public or you have access

### No GGUF Files Found

```
Error: No GGUF files found in owner/model
```

The repository might contain the model in a different format (PyTorch, Safetensors). Look for repositories with `-GGUF` suffix or GGUF files explicitly.

### Low Disk Space

The script will warn if disk space is below the estimated model size. You can:
1. Free up space
2. Choose a smaller quantization
3. Use `--yes` to proceed anyway

### Server Not Restarting

If the server doesn't restart automatically:
```bash
# Systemd install
sudo systemctl restart llama-cpp-server

# User install
~/.local/llama-cpp-server/start-server.sh
```

## Examples

### Switch to Qwen3 8B (Q4_K_M)

```bash
./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF --quant Q4_K_M --yes
```

### Preview Before Installing

```bash
./scripts/switch-model.sh microsoft/Phi-4-mini-instruct-GGUF --dry-run
```

### Use Custom Environment Paths

```bash
./scripts/switch-model.sh Qwen/Qwen3-8B-GGUF \
    --server-env /custom/path/server.env \
    --runner-env /custom/path/runner.env
```

## See Also

- `deploy/scripts/setup_llama_cpp.sh` - Initial llama.cpp setup
- `deploy/install_wsl_llamacpp.sh` - Full WSL worker installation
- `docs/LLM_SETUP_GUIDE.md` - LLM setup documentation
