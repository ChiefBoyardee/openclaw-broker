# OpenClaw env examples

One-place reference for all component env files. **Do not commit real `.env` or `*.env` files** — only the `.example` files live in git.

For a complete, beginner-friendly setup walkthrough (local + production, Discord, runner, optional LLM), see [docs/INSTALLATION_GUIDE.md](../../docs/INSTALLATION_GUIDE.md).

## Quick start (recommended topology)

From the repo root on the VPS. If a script is not executable (e.g. after a Windows clone), run it with `bash deploy/onboard_*.sh` instead of `./deploy/onboard_*.sh`.

1. **Broker (one-time)** — install, generate tokens, create `broker.env`, optional start:
   ```bash
   ./deploy/onboard_broker.sh
   ```
   Or with Tailscale and custom port: `BROKER_HOST=100.x.x.x BROKER_PORT=8443 ./deploy/onboard_broker.sh --enable`  
   Save the printed `WORKER_TOKEN`, `BOT_TOKEN`, and `BROKER_URL` for the runner and bots.

2. **Discord bot (per instance)** — paste tokens and allowlist ID:
   ```bash
   ./deploy/onboard_bot.sh <instance_name>
   ```
   Use the `BOT_TOKEN` and `BROKER_URL` from step 1.

3. **Runner (WSL/worker)** — from repo root on WSL, run `./deploy/onboard_runner.sh` and paste `BROKER_URL` and `WORKER_TOKEN` from step 1 (or set them in env). This creates the default repo-local env file at `runner/runner.env`. Then run `./runner/start.sh` or `python runner/runner.py`.

If you intentionally want the alternate deployment `WSL = broker + LLM + runner` and `VPS = bot only`, use [docs/COMMANDS_WSL_AND_VPS.md](../../docs/COMMANDS_WSL_AND_VPS.md).

For **multi-worker LLM smoke** (WSL vLLM + Jetson Orin), caps, routing, and full steps: see [docs/MULTI_WORKER_LLM_SMOKE.md](../../docs/MULTI_WORKER_LLM_SMOKE.md). Use [runner-wsl.env.example](runner-wsl.env.example) and [runner-jetson.env.example](runner-jetson.env.example) for each worker.

## LLM Backend Options

The runner supports multiple LLM backends via the OpenAI-compatible API:

| Backend | Example File | Use Case |
|---------|--------------|----------|
| **vLLM** | [runner-wsl.env.example](runner-wsl.env.example) | High throughput, multi-user, HuggingFace models |
| **llama.cpp** | [runner-llamacpp.env.example](runner-llamacpp.env.example) | GGUF models, lower VRAM, CPU support, simpler setup |

### llama.cpp (GGUF) Setup

For running GGUF models with llama.cpp on WSL:

1. **Quick Install**: Run the automated setup script:
   ```bash
   ./deploy/install_wsl_llamacpp.sh
   ```

2. **Or Manual Setup**:
   ```bash
   # Install llama.cpp server and download a model
   ./deploy/scripts/setup_llama_cpp.sh

   # Copy the llama.cpp runner config
   cp deploy/env.examples/runner-llamacpp.env.example runner/runner.env

   # Edit runner.env with your BROKER_URL and WORKER_TOKEN
   $EDITOR runner/runner.env

   # Start the server
   ~/.local/llama-cpp-server/start-server.sh
   # Or: /opt/llama-cpp-server/start-server.sh for system installs

   # Start the runner
   RUNNER_ENV=runner/runner.env runner/start.sh
   ```

3. **Discord routing**: Use `ask llamacpp:` or `ask llamacpp ` to target this worker.

### Qwen3.5 and New Model Support

The pip-released version of llama-cpp-python (0.3.16) does not yet include support for the Qwen3.5 model architecture (`qwen35`). This architecture was added to llama.cpp in February 2026, after the last pip release.

**To use Qwen3.5 models, you must build from source:**

```bash
# Build llama-cpp-python from source with latest llama.cpp
./deploy/install_wsl_llamacpp.sh --build-from-source

# Or for manual setup with CUDA support:
CMAKE_ARGS="-DGGML_CUDA=ON" ./deploy/scripts/setup_llama_cpp.sh --build-from-source
```

**What this does:**
- Clones the JamePeng llama-cpp-python fork (maintains synchronized API with latest llama.cpp)
- Updates the llama.cpp submodule to the latest commit (includes qwen35)
- Builds and installs from source with proper API compatibility

**Why the JamePeng fork?**
The main abetlen repository has outdated Python bindings that cause `undefined symbol: llama_get_kv_self` errors when built against the latest llama.cpp. The JamePeng fork maintains synchronized API names with upstream llama.cpp (see [abetlen/llama-cpp-python#2074](https://github.com/abetlen/llama-cpp-python/issues/2074) and [abetlen/llama-cpp-python#1901](https://github.com/abetlen/llama-cpp-python/pull/1901)).

**Build requirements:**
- `git`, `cmake`, and a C++ compiler
- For CUDA: NVIDIA drivers and CUDA toolkit
- Build time: 5-10 minutes depending on system

**Required CMAKE_ARGS:**
The build automatically includes `-DLLAVA_BUILD=OFF` to avoid a known CMake bug in llama.cpp's mtmd/llava tools. For CUDA support, also add `-DGGML_CUDA=ON`:

```bash
export CMAKE_ARGS="-DGGML_CUDA=ON -DLLAVA_BUILD=OFF"
./deploy/scripts/setup_llama_cpp.sh --build-from-source
```

**Auto-updates for source builds:**
The `auto_update.sh` script can update source-built installations:
```bash
./deploy/scripts/auto_update.sh llama-cpp
```

This will fetch the latest llama.cpp changes and rebuild automatically.

**Troubleshooting:**

| Error | Solution |
|-------|----------|
| `unknown model architecture: qwen35` | Use `--build-from-source` flag |
| `undefined symbol: llama_get_kv_self` | The main repo has API mismatch. The setup script now uses JamePeng fork which fixes this. Re-run with `--build-from-source`. |
| `set_target_properties` CMake error | Already patched in setup script via `-DLLAVA_BUILD=OFF` |
| `Permission denied` on scripts | Run `chmod +x deploy/scripts/*.sh` |
| `syntax error near unexpected token` | CRLF line endings from Windows. Run `sed -i 's/\r$//' deploy/scripts/script.sh` |

See the llama.cpp setup script for model download options, GPU layer configuration, and systemd service installation.

## Layout

| Component | Env file | Where it lives |
|-----------|----------|----------------|
| **Broker** | [broker.env.example](broker.env.example) | VPS: `/opt/openclaw-broker/broker.env` (or path used by systemd) |
| **Runner** | [runner.env.example](runner.env.example) | WSL/worker: default `runner/runner.env` in the repo |
| **Runner (WSL + vLLM)** | [runner-wsl.env.example](runner-wsl.env.example) | WSL with vLLM backend |
| **Runner (WSL + llama.cpp)** | [runner-llamacpp.env.example](runner-llamacpp.env.example) | WSL with llama.cpp GGUF backend |
| **Runner (Jetson)** | [runner-jetson.env.example](runner-jetson.env.example) | Jetson Orin with local LLM |
| **Discord bot** | [bot.env.example](bot.env.example) | VPS per instance: `/opt/openclaw-bot-<instance>/bot.env` |

### Scripts Reference

| Script | Purpose |
|--------|---------|
| `deploy/onboard_broker.sh` | One-time broker setup |
| `deploy/onboard_runner.sh` | One-time runner setup |
| `deploy/onboard_bot.sh` | One-time Discord bot setup |
| `deploy/install_wsl_llamacpp.sh` | Complete WSL + llama.cpp setup |
| `deploy/scripts/setup_llama_cpp.sh` | Setup llama.cpp server only |
| `deploy/scripts/check_updates.sh` | Check GitHub for updates |
| `deploy/scripts/auto_update.sh` | Apply updates automatically |
| `deploy/scripts/install_auto_update.sh` | Install systemd auto-update timer |
| `deploy/scripts/version_info.sh` | Show version and status |
| `deploy/scripts/update_vps.sh` | Manual VPS update |
| `deploy/scripts/update_runner_wsl.sh` | Manual WSL runner update |
| `deploy/scripts/update_runner_jetson.sh` | Manual Jetson runner update |

## Our environment (VPS + WSL)

- **VPS:** Broker + one or more Discord bot instances. Broker bound to Tailscale IP (e.g. `http://100.x.x.x:8443`).
- **WSL:** Runner; connects to broker over Tailscale or opened firewall (TCP 8000 or your port).

### Broker (VPS)

- Generate tokens once: `openssl rand -hex 32` for each of `WORKER_TOKEN` and `BOT_TOKEN`.
- Set `BROKER_HOST` to your Tailscale IP (e.g. `100.64.0.1`) and `BROKER_PORT=8443` if not 8000.
- Use the same `BOT_TOKEN` in every bot instance that should talk to this broker.
- Each bot instance still needs its own Discord Application and `DISCORD_TOKEN`.

### Runner (WSL)

- `BROKER_URL=http://<VPS_TAILSCALE_IP>:8443` (or `:8000` if you use 8000).
- `WORKER_TOKEN` = broker’s `WORKER_TOKEN`.

### Discord bot (VPS, per instance)

- Each instance = one Discord Application → one `DISCORD_TOKEN`.
- `BOT_TOKEN` = broker’s `BOT_TOKEN`.
- `BROKER_URL=http://127.0.0.1:8000` (if broker is on same host) or `http://<VPS_TAILSCALE_IP>:8443` if you use Tailscale and a different port.
- `ALLOWED_USER_ID` or `ALLOWLIST_USER_ID` = your Discord user ID (right‑click your user → Copy ID; Developer Mode must be on).

Use the **onboarding scripts** so you rarely edit env files by hand:

- **Broker:** `./deploy/onboard_broker.sh` — installs broker, prompts for bind address/port, generates or accepts tokens, writes `broker.env`, optionally starts. Use `--enable` to start without prompting.
- **Runner:** `./deploy/onboard_runner.sh` — prompts for `BROKER_URL` and `WORKER_TOKEN` (from broker), writes the default repo-local env file `runner/runner.env`. No sudo; run on WSL or worker machine.
- **Runner (llama.cpp):** `./deploy/install_wsl_llamacpp.sh` — complete WSL setup with llama.cpp GGUF support. See below.
- **Bot:** `./deploy/onboard_bot.sh <instance_name>` — installs one bot instance, prompts for `DISCORD_TOKEN`, `BOT_TOKEN`, `BROKER_URL`, and allowlist ID(s), writes `bot.env`, optionally starts.

## Automatic Updates

OpenClaw supports automatic updates via systemd timers (Linux/VPS) or manual cron jobs.

### Quick Setup (systemd)

```bash
# Install auto-update timer (detects component automatically)
sudo ./deploy/scripts/install_auto_update.sh --enable

# Or specify component explicitly:
sudo ./deploy/scripts/install_auto_update.sh --component vps --enable
sudo ./deploy/scripts/install_auto_update.sh --component runner --enable
sudo ./deploy/scripts/install_auto_update.sh --component jetson --enable

# Customize schedule (default: daily at 3 AM)
sudo ./deploy/scripts/install_auto_update.sh --component vps \
  --interval "*:00/6" --enable  # Every 6 hours
```

### Manual Update Commands

```bash
# Check for updates without applying
./deploy/scripts/check_updates.sh

# Apply updates (auto-detects component)
./deploy/scripts/auto_update.sh

# Force update even if no new commits
./deploy/scripts/auto_update.sh --force

# Update specific component with restart
./deploy/scripts/auto_update.sh --restart vps
./deploy/scripts/auto_update.sh --restart runner
./deploy/scripts/auto_update.sh --restart jetson
```

### Update Status

```bash
# Show version and component status
./deploy/scripts/version_info.sh

# Include update check
./deploy/scripts/version_info.sh --check
```

### Cron Setup (Alternative to systemd)

If systemd timers aren't available, use cron:

```bash
# Edit crontab
crontab -e

# Check hourly, update daily at 3 AM
0 * * * * cd /path/to/openclaw-broker && ./deploy/scripts/check_updates.sh --quiet
0 3 * * * cd /path/to/openclaw-broker && ./deploy/scripts/auto_update.sh --quiet --restart
```
