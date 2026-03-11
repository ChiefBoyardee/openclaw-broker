#!/usr/bin/env python3
"""
HuggingFace GGUF Model Switcher for OpenClaw

Downloads GGUF models from HuggingFace and updates the llama.cpp server
and OpenClaw runner configuration to use the new model.

Usage:
    python switch_model.py <model_id_or_url> [options]
    python switch_model.py Qwen/Qwen3-8B-GGUF
    python switch_model.py Qwen/Qwen3-8B-GGUF --quant Q4_K_M
    python switch_model.py https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF
    python switch_model.py Qwen/Qwen3-8B-GGUF --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Try to import huggingface_hub
try:
    from huggingface_hub import HfApi, hf_hub_download, list_repo_files
    from huggingface_hub.utils import RepositoryNotFoundError, RevisionNotFoundError
except ImportError:
    print("Error: huggingface_hub not installed.")
    print("Install with: pip install huggingface-hub")
    sys.exit(1)


# Color codes for terminal output
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


def color(text: str, color_code: str) -> str:
    """Wrap text with color codes."""
    return f"{color_code}{text}{Colors.END}"


def parse_model_id(model_input: str) -> str:
    """Parse a HuggingFace model ID from various input formats."""
    # Remove URL prefixes
    if "huggingface.co" in model_input:
        # Extract from URL like https://huggingface.co/owner/model-gguf
        match = re.search(r"huggingface\.co/([^/]+/[^/]+)", model_input)
        if match:
            return match.group(1)
    # Direct model ID
    if "/" in model_input and " " not in model_input:
        return model_input.strip()
    raise ValueError(f"Invalid model ID or URL: {model_input}")


def extract_quantization(filename: str) -> Optional[str]:
    """Extract quantization level from GGUF filename."""
    # Common patterns: model-q4_k_m.gguf, model-Q4_K_M.gguf, model.q4_k_m.gguf
    patterns = [
        r"[._-](q[0-9]+_[kksm]+)[.]gguf",
        r"[._-](q[0-9]+_[kksm]+)\.gguf",
        r"[._-](Q[0-9]+_[KKSM]+)\.gguf",
        r"[._-](fp16|FP16|q4_0|q5_0|q8_0|Q8_0)\.gguf",
    ]
    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def estimate_vram_gb(file_size_bytes: int, quant: Optional[str] = None) -> float:
    """Estimate VRAM requirements in GB based on file size and quantization."""
    # GGUF files are roughly the size of the loaded model
    # Add overhead for context buffer (~0.5-1GB depending on context size)
    base_gb = file_size_bytes / (1024**3)
    context_overhead = 0.5  # Conservative estimate for 8K context
    return round(base_gb + context_overhead, 2)


def get_quant_recommendation(quant: str) -> tuple[bool, str]:
    """Return (is_recommended, reason) for a given quantization."""
    quant_upper = quant.upper()
    recommendations = {
        "Q4_K_M": (True, "balanced quality/size"),
        "Q4_K_S": (False, "smaller but lower quality"),
        "Q5_K_M": (True, "good quality, moderate size"),
        "Q5_K_S": (False, "compromise option"),
        "Q6_K": (True, "high quality"),
        "Q8_0": (False, "highest quality but large"),
        "FP16": (False, "unquantized, very large"),
    }
    return recommendations.get(quant_upper, (False, ""))


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def find_gguf_files(repo_id: str, api: HfApi) -> list[dict]:
    """Find all GGUF files in a HuggingFace repository."""
    try:
        files = list_repo_files(repo_id, repo_type="model")
    except RepositoryNotFoundError:
        print(color(f"Error: Repository '{repo_id}' not found.", Colors.RED))
        print("Make sure the model ID is correct and the repo exists.")
        sys.exit(1)
    except Exception as e:
        print(color(f"Error listing repository files: {e}", Colors.RED))
        sys.exit(1)

    gguf_files = []
    for filename in files:
        if filename.lower().endswith(".gguf"):
            quant = extract_quantization(filename)
            # Try to get file info (may fail for some files)
            try:
                file_info = api.model_info(repo_id, files_metadata=True)
                # Find the specific file in the siblings
                size = None
                for sibling in file_info.siblings:
                    if sibling.rfilename == filename and sibling.size:
                        size = sibling.size
                        break
            except Exception:
                size = None

            gguf_files.append({
                "filename": filename,
                "quantization": quant or "UNKNOWN",
                "size": size,
            })

    # Sort by quantization quality (roughly)
    quality_order = {
        "Q4_K_S": 1, "Q4_K_M": 2, "Q5_K_S": 3, "Q5_K_M": 4,
        "Q6_K": 5, "Q8_0": 6, "FP16": 7, "Q4_0": 0, "Q5_0": 0,
    }
    gguf_files.sort(key=lambda x: quality_order.get(x["quantization"].upper(), -1))

    return gguf_files


def display_quantizations(files: list[dict]) -> None:
    """Display available quantizations in a formatted table."""
    print()
    print(color("Available GGUF Models:", Colors.BOLD + Colors.CYAN))
    print(color("=" * 80, Colors.DIM))
    print(f"{color(' # ', Colors.BOLD)} {color('Quantization', Colors.BOLD):12} {color('Size', Colors.BOLD):10} {color('VRAM Est.', Colors.BOLD):12} {color('Recommendation', Colors.BOLD):20} {color('Filename', Colors.BOLD)}")
    print(color("-" * 80, Colors.DIM))

    for i, file_info in enumerate(files, 1):
        quant = file_info["quantization"]
        size_str = format_size(file_info["size"]) if file_info["size"] else "Unknown"
        vram = estimate_vram_gb(file_info["size"] or 0, quant) if file_info["size"] else "?"
        vram_str = f"~{vram} GB" if isinstance(vram, (int, float)) else "Unknown"

        is_rec, reason = get_quant_recommendation(quant)
        if is_rec:
            rec_str = color(f"Recommended ({reason})", Colors.GREEN)
        else:
            rec_str = color(reason, Colors.DIM) if reason else ""

        filename_display = file_info["filename"]
        if len(filename_display) > 35:
            filename_display = "..." + filename_display[-32:]

        print(f" {color(str(i), Colors.YELLOW):3} {quant:12} {size_str:10} {vram_str:12} {rec_str:35} {filename_display}")

    print(color("=" * 80, Colors.DIM))
    print()


def prompt_for_selection(files: list[dict]) -> dict:
    """Prompt user to select a quantization."""
    while True:
        try:
            choice = input(color("Enter number of model to download (or 'q' to quit): ", Colors.BOLD + Colors.CYAN)).strip()
            if choice.lower() == 'q':
                print("Aborted.")
                sys.exit(0)
            idx = int(choice) - 1
            if 0 <= idx < len(files):
                return files[idx]
            print(color(f"Invalid selection. Please enter 1-{len(files)}", Colors.RED))
        except ValueError:
            print(color("Invalid input. Please enter a number.", Colors.RED))


def find_server_env() -> Optional[Path]:
    """Find the server.env file in common locations.
    
    Prefer system install if systemd service exists, otherwise use user install.
    """
    # Check if systemd service exists (indicates system install)
    systemd_service = Path("/etc/systemd/system/llama-cpp-server.service")
    
    paths = []
    if systemd_service.exists():
        # Systemd exists - prefer system install paths first
        paths = [
            Path("/opt/llama-cpp-server/server.env"),
            Path.home() / ".local" / "llama-cpp-server" / "server.env",
        ]
    else:
        # No systemd - prefer user install
        paths = [
            Path.home() / ".local" / "llama-cpp-server" / "server.env",
            Path("/opt/llama-cpp-server/server.env"),
        ]
    
    for path in paths:
        if path.exists():
            return path
    return None


def find_runner_env() -> Optional[Path]:
    """Find the runner.env file in common locations."""
    paths = [
        Path.cwd() / "runner" / "runner.env",
        Path("/opt/openclaw/runner/runner.env"),
    ]
    for path in paths:
        if path.exists():
            return path
    return None


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse an env file into a dictionary."""
    env_vars = {}
    if not path.exists():
        return env_vars

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip()
    return env_vars


def write_env_file(path: Path, env_vars: dict[str, str]) -> None:
    """Write env variables back to file, preserving comments where possible."""
    lines = []
    existing_keys = set()

    # Read existing file to preserve comments and structure
    if path.exists():
        with open(path, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    lines.append(line.rstrip())
                elif "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in env_vars:
                        lines.append(f"{key}={env_vars[key]}")
                        existing_keys.add(key)
                    else:
                        lines.append(line.rstrip())
                else:
                    lines.append(line.rstrip())

    # Add any new keys
    for key, value in env_vars.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def backup_env_file(path: Path) -> Path:
    """Create a backup of an env file with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.parent / f"{path.name}.backup.{timestamp}"
    shutil.copy2(path, backup_path)
    return backup_path


def get_models_dir(server_env_path: Path) -> Path:
    """Get the models directory from server.env or use default."""
    env_vars = parse_env_file(server_env_path)
    models_dir = env_vars.get("MODELS_DIR", "")
    if models_dir:
        return Path(models_dir)
    # Default based on server.env location
    if ".local" in str(server_env_path):
        return Path.home() / ".local" / "share" / "openclaw-models"
    return Path("/opt/models")


def download_model(repo_id: str, filename: str, models_dir: Path, dry_run: bool = False) -> bool:
    """Download a model from HuggingFace to the models directory."""
    target_path = models_dir / filename

    if dry_run:
        print(color(f"[DRY RUN] Would download {filename} to {target_path}", Colors.YELLOW))
        return True

    print(color(f"Downloading {filename}...", Colors.CYAN))
    print(color(f"Target: {target_path}", Colors.DIM))

    try:
        # Check disk space
        stats = shutil.disk_usage(models_dir)
        # Estimate size (we'll check actual file size after listing)
        # Most GGUFs are 2-10GB
        estimated_size = 5 * 1024 * 1024 * 1024  # 5GB estimate
        if stats.free < estimated_size:
            print(color(f"Warning: Low disk space ({format_size(stats.free)} available)", Colors.YELLOW))
            confirm = input(color("Continue anyway? (y/N): ", Colors.YELLOW)).strip().lower()
            if confirm != 'y':
                print("Aborted.")
                sys.exit(0)

        # Download the file
        downloaded_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(models_dir),
            local_dir_use_symlinks=False,
        )

        print(color(f"Downloaded to: {downloaded_path}", Colors.GREEN))

        # Verify the file exists and has content
        if not target_path.exists():
            # hf_hub_download may return a different path
            target_path = Path(downloaded_path)

        if target_path.exists() and target_path.stat().st_size > 0:
            actual_size = format_size(target_path.stat().st_size)
            print(color(f"Verified: {actual_size}", Colors.GREEN))
            return True
        else:
            print(color("Error: Downloaded file is empty or missing", Colors.RED))
            return False

    except Exception as e:
        print(color(f"Error downloading model: {e}", Colors.RED))
        return False


def update_environment(
    server_env_path: Path,
    runner_env_path: Optional[Path],
    model_filename: str,
    dry_run: bool = False,
) -> bool:
    """Update environment files with the new model."""
    # Backup files
    if not dry_run:
        server_backup = backup_env_file(server_env_path)
        print(color(f"Backed up server.env to: {server_backup}", Colors.DIM))
        if runner_env_path and runner_env_path.exists():
            runner_backup = backup_env_file(runner_env_path)
            print(color(f"Backed up runner.env to: {runner_backup}", Colors.DIM))

    # Update server.env
    server_vars = parse_env_file(server_env_path)
    old_model = server_vars.get("LLAMA_MODEL", "(not set)")
    server_vars["LLAMA_MODEL"] = model_filename

    if dry_run:
        print(color(f"[DRY RUN] Would update server.env:", Colors.YELLOW))
        print(color(f"  LLAMA_MODEL: {old_model} -> {model_filename}", Colors.YELLOW))
    else:
        write_env_file(server_env_path, server_vars)
        print(color(f"Updated server.env: LLAMA_MODEL={model_filename}", Colors.GREEN))

    # Update runner.env if it exists
    if runner_env_path and runner_env_path.exists():
        runner_vars = parse_env_file(runner_env_path)
        old_runner_model = runner_vars.get("LLM_MODEL", "(not set)")
        runner_vars["LLM_MODEL"] = model_filename

        if dry_run:
            print(color(f"[DRY RUN] Would update runner.env:", Colors.YELLOW))
            print(color(f"  LLM_MODEL: {old_runner_model} -> {model_filename}", Colors.YELLOW))
        else:
            write_env_file(runner_env_path, runner_vars)
            print(color(f"Updated runner.env: LLM_MODEL={model_filename}", Colors.GREEN))

    return True


def restart_llama_server(server_env_path: Path, dry_run: bool = False) -> bool:
    """Attempt to restart the llama.cpp server."""
    # Check if systemd service exists
    systemd_service = Path("/etc/systemd/system/llama-cpp-server.service")

    if systemd_service.exists():
        if dry_run:
            print(color("[DRY RUN] Would restart llama-cpp-server.service", Colors.YELLOW))
            return True

        print(color("Restarting llama-cpp-server service...", Colors.CYAN))
        import subprocess
        try:
            # Check if running as root - skip sudo if so
            is_root = os.geteuid() == 0
            cmd = ["systemctl", "restart", "llama-cpp-server"] if is_root else ["sudo", "systemctl", "restart", "llama-cpp-server"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                print(color("Service restarted successfully", Colors.GREEN))
                return True
            else:
                print(color(f"Failed to restart service: {result.stderr}", Colors.YELLOW))
                return False
        except Exception as e:
            print(color(f"Could not restart service: {e}", Colors.YELLOW))
            return False
    else:
        # Try to find and use the start script
        start_script = server_env_path.parent / "start-server.sh"
        if start_script.exists():
            if dry_run:
                print(color(f"[DRY RUN] Would run: {start_script}", Colors.YELLOW))
                return True
            print(color(f"Found start script: {start_script}", Colors.DIM))
            print(color("Please restart the server manually with:", Colors.YELLOW))
            print(f"  {start_script}")
            return False
        else:
            print(color("Could not find llama.cpp server start script", Colors.YELLOW))
            return False


def main():
    parser = argparse.ArgumentParser(
        description="Switch the OpenClaw llama.cpp server to a new HuggingFace GGUF model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s Qwen/Qwen3-8B-GGUF
  %(prog)s Qwen/Qwen3-8B-GGUF --quant Q4_K_M
  %(prog)s https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF
  %(prog)s Qwen/Qwen3-8B-GGUF --dry-run
  %(prog)s Qwen/Qwen3-8B-GGUF --no-restart
        """
    )
    parser.add_argument("model", help="HuggingFace model ID or URL (e.g., Qwen/Qwen3-8B-GGUF)")
    parser.add_argument("--quant", "-q", help="Specific quantization to download (e.g., Q4_K_M)")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview changes without downloading or modifying files")
    parser.add_argument("--no-restart", action="store_true", help="Skip restarting the llama.cpp server")
    parser.add_argument("--server-env", help="Path to server.env (auto-detected if not provided)")
    parser.add_argument("--runner-env", help="Path to runner.env (auto-detected if not provided)")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")

    args = parser.parse_args()

    # Parse model ID
    try:
        repo_id = parse_model_id(args.model)
        print(color(f"Model repository: {repo_id}", Colors.BLUE))
    except ValueError as e:
        print(color(f"Error: {e}", Colors.RED))
        sys.exit(1)

    # Find environment files
    server_env_path = Path(args.server_env) if args.server_env else find_server_env()
    runner_env_path = Path(args.runner_env) if args.runner_env else find_runner_env()

    if not server_env_path:
        print(color("Error: Could not find server.env. Please specify --server-env", Colors.RED))
        print("Searched in:")
        print(f"  {Path.home() / '.local' / 'llama-cpp-server' / 'server.env'}")
        print(f"  /opt/llama-cpp-server/server.env")
        sys.exit(1)

    print(color(f"Using server.env: {server_env_path}", Colors.DIM))
    if runner_env_path:
        print(color(f"Using runner.env: {runner_env_path}", Colors.DIM))

    # Get models directory
    models_dir = get_models_dir(server_env_path)
    print(color(f"Models directory: {models_dir}", Colors.DIM))

    # Ensure models directory exists
    models_dir.mkdir(parents=True, exist_ok=True)

    # Connect to HuggingFace
    api = HfApi()

    # List available GGUF files
    print(color("Fetching available models from HuggingFace...", Colors.CYAN))
    gguf_files = find_gguf_files(repo_id, api)

    if not gguf_files:
        print(color(f"Error: No GGUF files found in {repo_id}", Colors.RED))
        print("Make sure this is a GGUF model repository.")
        sys.exit(1)

    # Select model
    if args.quant:
        # Find matching quantization
        quant_upper = args.quant.upper()
        matching = [f for f in gguf_files if f["quantization"].upper() == quant_upper]
        if not matching:
            print(color(f"Quantization '{args.quant}' not found.", Colors.RED))
            display_quantizations(gguf_files)
            sys.exit(1)
        selected = matching[0]
        print(color(f"Selected: {selected['filename']}", Colors.GREEN))
    else:
        # Interactive selection
        display_quantizations(gguf_files)
        selected = prompt_for_selection(gguf_files)

    filename = selected["filename"]
    quant = selected["quantization"]
    size_str = format_size(selected["size"]) if selected["size"] else "Unknown"

    print()
    print(color("=" * 60, Colors.BOLD))
    print(color("Model Selection Summary:", Colors.BOLD + Colors.CYAN))
    print(f"  Repository: {repo_id}")
    print(f"  Filename:   {filename}")
    print(f"  Quantization: {quant}")
    print(f"  Size: {size_str}")
    print(color("=" * 60, Colors.BOLD))
    print()

    # Confirm
    if not args.yes and not args.dry_run:
        confirm = input(color("Proceed with download and installation? (Y/n): ", Colors.BOLD + Colors.YELLOW)).strip().lower()
        if confirm and confirm not in ('y', 'yes'):
            print("Aborted.")
            sys.exit(0)

    # Download model
    if not download_model(repo_id, filename, models_dir, args.dry_run):
        sys.exit(1)

    # Update environment files
    if not update_environment(server_env_path, runner_env_path, filename, args.dry_run):
        sys.exit(1)

    # Restart server
    if not args.no_restart:
        restart_llama_server(server_env_path, args.dry_run)
    else:
        print(color("Skipped server restart (--no-restart)", Colors.DIM))

    print()
    print(color("=" * 60, Colors.BOLD + Colors.GREEN))
    if args.dry_run:
        print(color("Dry run complete. No changes were made.", Colors.YELLOW))
        print("Run without --dry-run to apply changes.")
    else:
        print(color("Model switch complete!", Colors.GREEN))
        print()
        print("Next steps:")
        print(f"  1. Test the server: {server_env_path.parent / 'test-server.sh'}")
        if runner_env_path:
            print(f"  2. Restart the runner if needed")
    print(color("=" * 60, Colors.BOLD + Colors.GREEN))


if __name__ == "__main__":
    main()
