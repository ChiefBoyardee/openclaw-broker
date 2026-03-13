# VPS CLI Access Setup Guide

This guide explains how to enable CLI access on your VPS (instead of WSL) for secure web setup and nginx management. With this setup, your runner can remain on WSL while executing commands remotely on the VPS via SSH.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      WSL (Runner)                              │
│  ┌─────────────────┐    ┌──────────────────────────────────┐ │
│  │  LLM Agent      │    │  VPS Remote Executor              │ │
│  │  ┌──────────┐   │    │  ┌─────────┐    ┌──────────────┐  │ │
│  │  │ LLM Loop │◄──┼────┼──┤ Bridge  │◄───┤ SSH Client   │  │ │
│  │  └──────────┘   │    │  └─────────┘    └──────┬───────┘  │ │
│  └─────────────────┘    └──────────────────────────┼──────────┘ │
└────────────────────────────────────────────────────┼────────────┘
                                                     │ SSH
                             ┌───────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      VPS (Production)                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Nginx + Website                                          │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │  │
│  │  │ sites-enabled│  │ /var/www/    │  │ SSL Certs    │   │  │
│  │  │ nginx.conf   │  │ website      │  │ (certbot)    │   │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘   │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- **WSL**: Windows Subsystem for Linux with runner already configured
- **VPS**: A Linux VPS (Rocky Linux 9, Ubuntu, or Debian) with:
  - Nginx installed
  - SSH access enabled
  - Sudo access for the deployment user
- **SSH Key**: Ed25519 key pair for secure authentication

## Setup Instructions

### Step 1: Configure SSH Access to VPS

Run the setup script from your WSL environment:

```bash
cd /opt/openclaw/openclaw-broker
bash deploy/scripts/setup_vps_runner.sh --host YOUR_VPS_IP --user openclaw
```

This will:
1. Generate an SSH key pair (if needed)
2. Display the public key to copy to the VPS
3. Create a `runner_vps.env` configuration file

### Step 2: Configure VPS for SSH Access

On your VPS as root, run:

```bash
# Create the openclaw user
useradd -m -s /bin/bash openclaw

# Create .ssh directory
mkdir -p /home/openclaw/.ssh
chmod 700 /home/openclaw/.ssh

# Add the public key (copy from setup script output)
echo 'ssh-ed25519 AAAAC3NzaC...' >> /home/openclaw/.ssh/authorized_keys
chmod 600 /home/openclaw/.ssh/authorized_keys
chown -R openclaw:openclaw /home/openclaw/.ssh

# Configure sudo for nginx and certbot
cat > /etc/sudoers.d/openclaw << 'EOF'
openclaw ALL=(ALL) NOPASSWD: /usr/sbin/nginx, /usr/bin/systemctl reload nginx, /usr/bin/systemctl status nginx, /usr/bin/systemctl restart nginx, /usr/bin/certbot, /bin/mkdir, /bin/chown, /bin/chmod
EOF
chmod 440 /etc/sudoers.d/openclaw

# Create website directory
mkdir -p /var/www/urgo
chown -R openclaw:openclaw /var/www/urgo
```

### Step 3: Configure Runner Environment

Add the VPS configuration to your runner environment:

```bash
cd /opt/openclaw/openclaw-broker
cat runner_vps.env >> runner/runner.env
```

Or manually add to `runner/runner.env`:

```bash
# VPS Remote Execution Configuration
VPS_HOST=your.vps.ip.address
VPS_USER=openclaw
VPS_SSH_KEY_PATH=/home/youruser/.ssh/openclaw_vps_runner
VPS_SSH_PORT=22
VPS_CMD_TIMEOUT=60
VPS_MAX_OUTPUT_BYTES=50000
VPS_WEBSITE_BASE=/var/www/urgo
```

### Step 4: Test Connection

Restart your runner and test the VPS connection:

```bash
# Test via Python
python3 << 'EOF'
from runner.vps_remote_executor import test_vps_connection
print(test_vps_connection())
EOF
```

Or test via Discord command:
```
!tool vps_test_connection
```

## Usage Examples

### Via CLI Commands (Agentic Mode)

```
!agentic Check nginx status on VPS and reload if needed
```

The agent can now use:
- `vps test` - Test SSH connection
- `vps exec "nginx -t"` - Execute commands on VPS
- `vps nginx-status` - Check nginx status
- `vps nginx-reload` - Reload nginx configuration
- `vps website-list` - List website files
- `vps certbot-renew` - Renew SSL certificates

### Via Tool Calls

```json
{
  "tool": "vps_remote_exec",
  "params": {
    "command": "systemctl status nginx"
  }
}
```

### Via Direct Python

```python
from runner.vps_remote_executor import execute_on_vps, get_vps_config

# Execute command on VPS
result = execute_on_vps("nginx -t")
print(result)

# Get nginx status
result = execute_on_vps("systemctl status nginx")
print(result)

# List website files
result = execute_on_vps("ls -la /var/www/urgo")
print(result)
```

## Security Features

### Command Allowlisting

Only these commands are allowed on the VPS:
- `nginx`, `systemctl` (nginx-related)
- `ls`, `cat`, `mkdir`, `cp`, `mv`, `rm`, `chmod`, `chown` (file operations)
- `tee`, `echo`, `head`, `tail`, `grep`, `find` (content manipulation)
- `certbot` (SSL management)
- `df`, `du`, `ps`, `free`, `uptime` (system info)

### Path Restrictions

- Website files: `/var/www/`, `/srv/www/`, `/opt/www/`, `/usr/share/nginx/html/`
- Nginx configs: `/etc/nginx/sites-available/`, `/etc/nginx/sites-enabled/`, `/etc/nginx/conf.d/`
- Denied: `/etc/passwd`, `/root`, `/home/*/.ssh`, `/proc`, `/sys`

### Input Validation

The system blocks:
- Path traversal (`../`, `..\`)
- Command substitution (`$(...)`, `` `...` ``)
- Dangerous patterns (`curl | sh`, `wget | sh`)
- Shell metacharacters (`;`, `|`, `&`, `$`, `` ` ``)

### SSH Security

- Key-based authentication only (no passwords)
- Auto-accept new host keys (disable in production if needed)
- Connection timeouts (10s connect, 60s command)
- Output size limits (50KB max)

## Secure Website Setup Workflow

### 1. Generate Secure Nginx Config

```python
from runner.nginx_configurator import generate_secure_nginx_config

# Generate with strict security preset
result = generate_secure_nginx_config(
    domain="urgo.sgc.earth",
    web_root="/var/www/urgo",
    ssl_cert="/etc/letsencrypt/live/urgo.sgc.earth/fullchain.pem",
    ssl_key="/etc/letsencrypt/live/urgo.sgc.earth/privkey.pem",
    security_preset="strict",  # or "paranoid" for maximum security
    enable_hsts=True,
    enable_csp=True,
)
print(result)
```

### 2. Install Config on VPS

```python
import json
from runner.vps_remote_executor import execute_on_vps

# Write config to temporary file locally
config_content = "..."  # From generate_secure_nginx_config

# Use tee to write config on VPS (requires sudo)
cmd = f"echo '{config_content}' | sudo tee /etc/nginx/sites-available/urgo.sgc.earth"
result = execute_on_vps(cmd)

# Enable site
cmd = "sudo ln -sf /etc/nginx/sites-available/urgo.sgc.earth /etc/nginx/sites-enabled/"
result = execute_on_vps(cmd)

# Test and reload
cmd = "sudo nginx -t && sudo systemctl reload nginx"
result = execute_on_vps(cmd)
```

### 3. Verify SSL Setup

```python
from runner.nginx_configurator import verify_ssl_setup

result = verify_ssl_setup("urgo.sgc.earth")
print(result)
```

## Troubleshooting

### Connection Issues

```bash
# Test SSH manually
ssh -i ~/.ssh/openclaw_vps_runner openclaw@YOUR_VPS_IP uptime

# Check VPS SSH service
ssh root@YOUR_VPS_IP "systemctl status sshd"

# Verify key permissions
ls -la ~/.ssh/openclaw_vps_runner*
# Should be: -rw------- (private), -rw-r--r-- (public)
```

### Permission Denied

```bash
# On VPS, check authorized_keys
ssh root@YOUR_VPS_IP "cat /home/openclaw/.ssh/authorized_keys"

# Check sudoers configuration
ssh root@YOUR_VPS_IP "cat /etc/sudoers.d/openclaw"
ssh root@YOUR_VPS_IP "visudo -c"  # Validate sudoers
```

### Command Failures

```bash
# Check command validation
python3 << 'EOF'
from runner.vps_remote_executor import _validate_command
is_valid, error = _validate_command("nginx -t")
print(f"Valid: {is_valid}, Error: {error}")
EOF

# Test with verbose output
python3 << 'EOF'
import logging
logging.basicConfig(level=logging.DEBUG)
from runner.vps_remote_executor import execute_on_vps
print(execute_on_vps("nginx -t"))
EOF
```

### Nginx Configuration Issues

```bash
# Via VPS CLI
vps exec "sudo nginx -t"

# Check error logs
vps exec "sudo tail -n 50 /var/log/nginx/error.log"

# Verify site is enabled
vps exec "ls -la /etc/nginx/sites-enabled/"
```

## Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `VPS_HOST` | VPS hostname or IP | (required) |
| `VPS_USER` | SSH username | `openclaw` |
| `VPS_SSH_KEY_PATH` | Path to SSH private key | `~/.ssh/openclaw_vps_runner` |
| `VPS_SSH_PORT` | SSH port | `22` |
| `VPS_CMD_TIMEOUT` | Command timeout (seconds) | `60` |
| `VPS_MAX_OUTPUT_BYTES` | Max output size | `50000` |
| `VPS_WEBSITE_BASE` | Website root on VPS | `/var/www/urgo` |

## Security Best Practices

1. **Use Dedicated User**: Create a dedicated `openclaw` user with minimal permissions
2. **Limit Sudo Access**: Only grant sudo for nginx and certbot commands
3. **Rotate Keys Regularly**: Regenerate SSH keys every 90 days
4. **Monitor Logs**: Watch `/var/log/auth.log` for suspicious activity
5. **Enable 2FA**: Consider adding 2FA for VPS root access
6. **Firewall Rules**: Restrict SSH access to your WSL IP if possible
7. **Regular Updates**: Keep nginx and certbot updated on the VPS
8. **SSL Certificates**: Use Let's Encrypt with auto-renewal

## Migration from Local to Remote

If you were previously running nginx/website tools locally on WSL:

1. Backup existing configs:
   ```bash
   cp -r /etc/nginx/sites-available ~/nginx-backup
   ```

2. Update runner.env with VPS configuration

3. Test each command on VPS before switching:
   ```bash
   python3 -c "from runner.vps_remote_executor import test_vps_connection; print(test_vps_connection())"
   ```

4. Update Discord bot commands to use `vps_*` tools

5. Monitor logs during transition

## Next Steps

- Set up [automatic SSL certificate renewal](VPS_FIREWALL.md)
- Configure [firewall rules](VPS_FIREWALL.md)
- Enable [nginx monitoring](SECURITY_OBSERVABILITY.md)
- Review [security cadence](SECURITY_CADENCE.md)
