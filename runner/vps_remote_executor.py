"""
VPS Remote Execution Module - Execute CLI commands on VPS via SSH.

Provides secure remote execution capabilities for the runner to manage
VPS resources (nginx, website files, system commands) without requiring
the runner to be physically located on the VPS.

Security features:
- Key-based SSH authentication only (no passwords)
- Command allowlisting
- Path traversal prevention
- Output size limits
- Connection timeouts
- Audit logging
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Configuration from environment
VPS_HOST = os.environ.get("VPS_HOST", "")
VPS_USER = os.environ.get("VPS_USER", "openclaw")
VPS_SSH_KEY_PATH = os.environ.get("VPS_SSH_KEY_PATH", "")
VPS_SSH_PORT = int(os.environ.get("VPS_SSH_PORT", "22"))
VPS_CMD_TIMEOUT = int(os.environ.get("VPS_CMD_TIMEOUT", "60"))
VPS_MAX_OUTPUT_BYTES = int(os.environ.get("VPS_MAX_OUTPUT_BYTES", "50000"))

# Allowed commands on VPS (security allowlist)
ALLOWED_VPS_COMMANDS = {
    # Nginx management
    "nginx", "nginx-test", "nginx-reload", "systemctl",
    # File operations (restricted paths)
    "ls", "cat", "mkdir", "cp", "mv", "rm", "chmod", "chown",
    # Website content
    "tee", "echo", "head", "tail", "grep", "find",
    # SSL/Certbot
    "certbot",
    # System info
    "df", "du", "ps", "free", "uptime",
}

# Restricted paths that cannot be accessed
RESTRICTED_PATHS = [
    "/etc/passwd", "/etc/shadow", "/etc/ssh/sshd_config",
    "/root", "/home/*/.ssh", "/proc", "/sys",
    "/etc/nginx/nginx.conf",  # Only allow sites-available/
]

# Allowed web root paths
ALLOWED_WEB_ROOTS = [
    "/var/www/", "/srv/www/", "/opt/www/", "/usr/share/nginx/html/",
]

# Allowed nginx paths
ALLOWED_NGINX_PATHS = [
    "/etc/nginx/sites-available/", "/etc/nginx/sites-enabled/",
    "/etc/nginx/conf.d/", "/var/log/nginx/",
]


@dataclass
class VPSConnectionConfig:
    """Configuration for VPS SSH connection."""
    host: str
    user: str
    key_path: str
    port: int = 22
    timeout: int = 60

    def is_configured(self) -> bool:
        """Check if all required config is present."""
        return bool(self.host and self.user and self.key_path)


def get_vps_config() -> VPSConnectionConfig:
    """Get VPS connection configuration from environment."""
    return VPSConnectionConfig(
        host=VPS_HOST,
        user=VPS_USER,
        key_path=VPS_SSH_KEY_PATH,
        port=VPS_SSH_PORT,
        timeout=VPS_CMD_TIMEOUT,
    )


def _validate_path(path: str, allowed_prefixes: list[str]) -> bool:
    """Validate that path is within allowed prefixes."""
    if not path or not isinstance(path, str):
        return False

    # Normalize path
    path = os.path.normpath(path)

    # Check for path traversal attempts
    if ".." in path or path.startswith(".."):
        return False

    # Check for restricted paths
    for restricted in RESTRICTED_PATHS:
        if restricted.endswith("*"):
            pattern = restricted.rstrip("*") + ".*"
            if re.match(pattern, path):
                return False
        elif path.startswith(restricted) or path == restricted:
            return False

    # Check if within allowed prefixes
    for prefix in allowed_prefixes:
        if path.startswith(prefix):
            return True

    return False


def _validate_command(command: str) -> tuple[bool, str]:
    """
    Validate that a command is safe to execute on VPS.

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not command or not isinstance(command, str):
        return False, "Empty command"

    # Extract the base command
    try:
        tokens = shlex.split(command)
        if not tokens:
            return False, "Empty command after parsing"
        base_cmd = tokens[0]
    except ValueError:
        # Fallback to simple split
        base_cmd = command.split()[0] if command.split() else ""

    # Check if base command is in allowlist
    if base_cmd not in ALLOWED_VPS_COMMANDS:
        return False, f"Command '{base_cmd}' not in allowlist"

    # Check for dangerous patterns in full command
    dangerous_patterns = [
        r";\s*rm\s+-rf\s+/",  # ; rm -rf /
        r"`.*`",               # Backtick command substitution
        r"\$\(.*\)",          # $(...) command substitution
        r">\s*/etc/",         # Redirect to /etc
        r"2>&1.*>/etc/",      # Redirect with fd to /etc
        r"curl.*\|.*sh",      # curl | sh
        r"wget.*\|.*sh",      # wget | sh
        r"eval\s*\(",         # eval(
        r"exec\s*\(",         # exec(
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Command contains dangerous pattern: {pattern}"

    # Validate paths in command arguments
    # Check file paths mentioned in the command
    path_patterns = [
        r"/(?:var|srv|opt|usr|etc|home)/[^\s;|&\"'`]+",
    ]

    for pattern in path_patterns:
        for match in re.finditer(pattern, command):
            path = match.group(0)
            # Check if path is in allowed locations
            all_allowed = ALLOWED_WEB_ROOTS + ALLOWED_NGINX_PATHS
            is_allowed = False
            for allowed in all_allowed:
                if path.startswith(allowed.rstrip("/")):
                    is_allowed = True
                    break
            if not is_allowed:
                # Check restricted paths
                for restricted in RESTRICTED_PATHS:
                    if restricted.endswith("*"):
                        prefix = restricted.rstrip("*")
                        if path.startswith(prefix):
                            return False, f"Path '{path}' is in restricted area"
                    elif path.startswith(restricted) or path == restricted:
                        return False, f"Path '{path}' is in restricted area"

    return True, ""


def _build_ssh_command(config: VPSConnectionConfig, remote_command: str) -> list[str]:
    """Build SSH command with proper options for security."""
    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=accept-new",  # Auto-accept new host keys
        "-o", "UserKnownHostsFile=/dev/null",      # Don't persist host keys
        "-o", "LogLevel=ERROR",                    # Reduce noise
        "-o", "ConnectTimeout=10",                 # Connection timeout
        "-o", "ServerAliveInterval=30",            # Keep connection alive
        "-p", str(config.port),
        "-i", config.key_path,
        f"{config.user}@{config.host}",
        remote_command,
    ]
    return ssh_cmd


def execute_on_vps(
    command: str,
    config: Optional[VPSConnectionConfig] = None,
    timeout: Optional[int] = None,
) -> str:
    """
    Execute a command on the VPS via SSH.

    Args:
        command: The command to execute on VPS
        config: VPS connection config (uses env defaults if not provided)
        timeout: Command timeout in seconds (uses env default if not provided)

    Returns:
        JSON string with result
    """
    if config is None:
        config = get_vps_config()

    # Check configuration
    if not config.is_configured():
        return json.dumps({
            "success": False,
            "error": "VPS not configured. Set VPS_HOST, VPS_USER, and VPS_SSH_KEY_PATH.",
            "configured": False,
        }, indent=2)

    # Validate command
    is_valid, error_msg = _validate_command(command)
    if not is_valid:
        return json.dumps({
            "success": False,
            "error": f"Command validation failed: {error_msg}",
            "command": command,
        }, indent=2)

    # Check SSH key exists
    if not os.path.isfile(config.key_path):
        return json.dumps({
            "success": False,
            "error": f"SSH key not found: {config.key_path}",
        }, indent=2)

    # Build and execute SSH command
    ssh_cmd = _build_ssh_command(config, command)
    cmd_timeout = timeout or config.timeout

    try:
        logger.info(f"Executing on VPS ({config.host}): {command[:100]}...")

        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=cmd_timeout,
        )

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        # Truncate output if too large
        truncated = False
        if len(stdout.encode("utf-8")) > VPS_MAX_OUTPUT_BYTES:
            stdout = stdout[:VPS_MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore")
            truncated = True

        success = result.returncode == 0

        return json.dumps({
            "success": success,
            "returncode": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": truncated,
            "host": config.host,
            "command": command,
        }, indent=2)

    except subprocess.TimeoutExpired:
        logger.error(f"VPS command timed out after {cmd_timeout}s: {command[:100]}")
        return json.dumps({
            "success": False,
            "error": f"Command timed out after {cmd_timeout} seconds",
            "timeout": True,
        }, indent=2)

    except subprocess.CalledProcessError as e:
        logger.error(f"VPS command failed: {e}")
        return json.dumps({
            "success": False,
            "error": f"SSH execution failed: {str(e)}",
            "returncode": e.returncode,
            "stderr": e.stderr,
        }, indent=2)

    except Exception as e:
        logger.exception("Unexpected error executing VPS command")
        return json.dumps({
            "success": False,
            "error": f"Unexpected error: {str(e)}",
        }, indent=2)


def copy_to_vps(
    local_path: str,
    remote_path: str,
    config: Optional[VPSConnectionConfig] = None,
) -> str:
    """
    Copy a file to the VPS via SCP.

    Args:
        local_path: Local file path
        remote_path: Destination path on VPS
        config: VPS connection config

    Returns:
        JSON string with result
    """
    if config is None:
        config = get_vps_config()

    if not config.is_configured():
        return json.dumps({
            "success": False,
            "error": "VPS not configured",
        }, indent=2)

    # Validate remote path
    all_allowed = ALLOWED_WEB_ROOTS + ALLOWED_NGINX_PATHS
    if not _validate_path(remote_path, all_allowed):
        return json.dumps({
            "success": False,
            "error": f"Remote path '{remote_path}' is not in allowed location",
        }, indent=2)

    # Check local file exists
    if not os.path.isfile(local_path):
        return json.dumps({
            "success": False,
            "error": f"Local file not found: {local_path}",
        }, indent=2)

    # Build SCP command
    scp_cmd = [
        "scp",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        "-P", str(config.port),
        "-i", config.key_path,
        local_path,
        f"{config.user}@{config.host}:{remote_path}",
    ]

    try:
        result = subprocess.run(
            scp_cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        success = result.returncode == 0
        return json.dumps({
            "success": success,
            "local_path": local_path,
            "remote_path": remote_path,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }, indent=2)

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"SCP failed: {str(e)}",
        }, indent=2)


def test_vps_connection(config: Optional[VPSConnectionConfig] = None) -> str:
    """Test SSH connection to VPS."""
    if config is None:
        config = get_vps_config()

    if not config.is_configured():
        return json.dumps({
            "success": False,
            "configured": False,
            "error": "VPS not configured. Set VPS_HOST, VPS_USER, VPS_SSH_KEY_PATH.",
        }, indent=2)

    result = execute_on_vps("uptime", config=config)
    result_obj = json.loads(result)

    if result_obj.get("success"):
        return json.dumps({
            "success": True,
            "configured": True,
            "connected": True,
            "host": config.host,
            "user": config.user,
            "message": "SSH connection successful",
        }, indent=2)
    else:
        return json.dumps({
            "success": False,
            "configured": True,
            "connected": False,
            "host": config.host,
            "error": result_obj.get("error", "Connection failed"),
        }, indent=2)


def get_vps_remote_capabilities() -> list[str]:
    """Return list of VPS remote execution capabilities."""
    return [
        "vps_remote_exec",
        "vps_remote_copy",
        "vps_connection_test",
        "vps_nginx_manage",
        "vps_website_manage",
    ]
