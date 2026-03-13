"""
Security-hardened nginx configuration generator and manager.

Provides tools for AI personalities to manage their own nginx server blocks
with comprehensive security hardening, rate limiting, and SSL/TLS support.

All functions are designed to be called via the runner tool bridge.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Optional

# Default nginx paths (can be overridden via environment)
NGINX_SITES_AVAILABLE = os.environ.get("NGINX_SITES_AVAILABLE", "/etc/nginx/sites-available")
NGINX_SITES_ENABLED = os.environ.get("NGINX_SITES_ENABLED", "/etc/nginx/sites-enabled")
NGINX_CONF_D = os.environ.get("NGINX_CONF_D", "/etc/nginx/conf.d")
NGINX_BINARY = os.environ.get("NGINX_BINARY", "nginx")


def _validate_domain_name(domain: str) -> bool:
    """
    Strict domain name validation.
    
    Args:
        domain: Domain name to validate
        
    Returns:
        True if valid and safe
    """
    if not domain or not isinstance(domain, str):
        return False
    
    # Strip whitespace
    domain = domain.strip()
    
    # Check for dangerous characters
    dangerous = [';', '&', '|', '$', '`', '\\', '<', '>', '*', '?', '{', '}']
    for char in dangerous:
        if char in domain:
            return False
    
    # Check for path traversal attempts
    if '..' in domain or '//' in domain:
        return False
    
    # Remove trailing dot if present
    domain = domain.rstrip('.')
    
    # Check length
    if len(domain) > 253:
        return False
    
    # Validate each label
    labels = domain.split('.')
    for label in labels:
        if not label or len(label) > 63:
            return False
        # Labels must start/end with alphanumeric, can contain hyphens
        if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$', label):
            return False
    
    return True


def _validate_web_root(path: str) -> bool:
    """
    Validate web root path for safety.
    
    Args:
        path: Absolute path to validate
        
    Returns:
        True if valid and safe
    """
    if not path or not isinstance(path, str):
        return False
    
    # Must be absolute path
    if not path.startswith('/'):
        return False
    
    # No path traversal
    if '..' in path:
        return False
    
    # No dangerous characters
    dangerous = [';', '&', '|', '$', '`', '\\', '*', '?', '{', '}']
    for char in dangerous:
        if char in path:
            return False
    
    # Must be under common web roots or explicitly allowed
    allowed_prefixes = [
        '/var/www/',
        '/srv/',
        '/usr/share/nginx/html',
        '/opt/www/',
    ]

    # Check if path is in allowed location
    is_allowed = any(path.startswith(prefix) for prefix in allowed_prefixes)

    # Also allow /home/<user>/www/ pattern (user web dirs)
    if not is_allowed and re.match(r'^/home/[^/]+/www/', path):
        is_allowed = True

    return is_allowed


def _escape_nginx_string(value: str) -> str:
    """
    Escape a string for safe use in nginx configuration.
    
    Args:
        value: String to escape
        
    Returns:
        Escaped string safe for nginx config
    """
    if not value:
        return ""
    
    # Remove null bytes
    value = value.replace('\x00', '')
    
    # Escape backslashes
    value = value.replace('\\', '\\\\')
    
    # Escape quotes
    value = value.replace('"', '\\"')
    
    return value


def _generate_security_headers(config: dict) -> str:
    """
    Generate nginx add_header directives for security headers.
    
    Args:
        config: Configuration dict with security_headers
        
    Returns:
        Nginx configuration string with header directives
    """
    headers = config.get('security_headers', {
        "X-Frame-Options": "SAMEORIGIN",
        "X-Content-Type-Options": "nosniff",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    })
    
    directives = []
    for header, value in headers.items():
        # Validate header name (alphanumeric and hyphens)
        if not re.match(r'^[a-zA-Z0-9-]+$', header):
            continue
        # Escape value
        safe_value = _escape_nginx_string(str(value))
        directives.append(f'    add_header {header} "{safe_value}" always;')
    
    return '\n'.join(directives)


def nginx_generate_config(
    domain: str,
    web_root: str,
    ssl_cert: Optional[str] = None,
    ssl_key: Optional[str] = None,
    enable_http2: bool = True,
    rate_limit_zone: str = "ai_site",
    rate_limit_rps: int = 10,
    rate_limit_burst: int = 20,
    security_config: Optional[dict] = None,
) -> str:
    """
    Generate a security-hardened nginx server block configuration.
    
    Args:
        domain: Domain name (e.g., "urgo.sgc.earth")
        web_root: Absolute path to website files
        ssl_cert: Path to SSL certificate (fullchain.pem)
        ssl_key: Path to SSL certificate key (privkey.pem)
        enable_http2: Enable HTTP/2 support (requires SSL)
        rate_limit_zone: Rate limiting zone name
        rate_limit_rps: Requests per second limit
        rate_limit_burst: Burst capacity
        security_config: Additional security configuration
        
    Returns:
        JSON string with result and generated configuration
    """
    try:
        # Validate inputs
        if not _validate_domain_name(domain):
            return json.dumps({
                "success": False,
                "error": "Invalid domain name",
                "domain": domain
            })
        
        if not _validate_web_root(web_root):
            return json.dumps({
                "success": False,
                "error": "Invalid or unsafe web root path",
                "path": web_root
            })
        
        # Escape values for nginx
        safe_domain = _escape_nginx_string(domain)
        safe_web_root = _escape_nginx_string(web_root)
        safe_zone = _escape_nginx_string(rate_limit_zone)
        
        # Build configuration
        config_parts = []
        
        # HTTP server - redirect to HTTPS if SSL is configured
        if ssl_cert and ssl_key:
            http_server = f"""server {{
    listen 80;
    server_name {safe_domain};
    return 301 https://$server_name$request_uri;
}}
"""
            config_parts.append(http_server)
        
        # Main server block
        listen_directive = "listen 443 ssl"
        if enable_http2 and ssl_cert and ssl_key:
            listen_directive += " http2"
        elif not ssl_cert:
            listen_directive = "listen 80"
        
        # Rate limiting (define zone at http level - we'll include this separately)
        rate_limit_directive = f"limit_req zone={safe_zone} burst={rate_limit_burst} nodelay;"
        
        # Security headers
        security_headers = _generate_security_headers(security_config or {})
        
        # SSL configuration
        ssl_config = ""
        if ssl_cert and ssl_key:
            safe_cert = _escape_nginx_string(ssl_cert)
            safe_key = _escape_nginx_string(ssl_key)
            ssl_config = f"""
    # SSL Configuration
    ssl_certificate {safe_cert};
    ssl_certificate_key {safe_key};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
"""
        
        # Main server configuration
        main_server = f"""server {{
    {listen_directive};
    server_name {safe_domain};
    
    root {safe_web_root};
    index index.html index.htm;
    
    # Security Headers
{security_headers}
    
    # Hide nginx version
    server_tokens off;
    
    # Rate limiting
    {rate_limit_directive}
    
    # Deny access to hidden files
    location ~ /\\. {{
        deny all;
        return 404;
    }}
    
    # Deny access to backup/sensitive files
    location ~* \\.(bak|backup|swp|tmp|temp|log|sql|env)$ {{
        deny all;
        return 404;
    }}
    
    # Main location
    location / {{
        try_files $uri $uri/ =404;
        # Additional rate limiting for dynamic content could go here
    }}
    
    # Static files caching
    location ~* \\.(jpg|jpeg|png|gif|ico|css|js|svg|woff|woff2|ttf|eot)$ {{
        expires 30d;
        add_header Cache-Control "public, immutable";
    }}
{ssl_config}}}
"""
        config_parts.append(main_server)
        
        # Rate limiting zone definition (goes in http context)
        rate_limit_zone_def = f"limit_req_zone $binary_remote_addr zone={safe_zone}:10m rate={rate_limit_rps}r/s;"
        
        full_config = '\n'.join(config_parts)
        
        return json.dumps({
            "success": True,
            "domain": domain,
            "web_root": web_root,
            "ssl_enabled": bool(ssl_cert and ssl_key),
            "config": full_config,
            "rate_limit_zone": rate_limit_zone_def,
            "message": f"Nginx configuration generated for {domain}"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": "Failed to generate nginx configuration"
        })


def nginx_test_config() -> str:
    """
    Test nginx configuration syntax.
    
    Returns:
        JSON string with test result
    """
    try:
        result = subprocess.run(
            [NGINX_BINARY, "-t"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        success = result.returncode == 0
        return json.dumps({
            "success": success,
            "valid": success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "message": "Configuration test passed" if success else "Configuration test failed"
        }, indent=2)
        
    except subprocess.TimeoutExpired:
        return json.dumps({
            "success": False,
            "error": "Nginx test timed out",
            "valid": False
        })
    except FileNotFoundError:
        return json.dumps({
            "success": False,
            "error": f"Nginx binary not found: {NGINX_BINARY}",
            "valid": False
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "valid": False
        })


def nginx_reload() -> str:
    """
    Reload nginx configuration safely.
    
    Returns:
        JSON string with result
    """
    try:
        # First test the configuration
        test_result = subprocess.run(
            [NGINX_BINARY, "-t"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if test_result.returncode != 0:
            return json.dumps({
                "success": False,
                "error": "Configuration test failed, not reloading",
                "test_output": test_result.stderr,
                "reloaded": False
            })
        
        # Reload nginx
        reload_result = subprocess.run(
            [NGINX_BINARY, "-s", "reload"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        success = reload_result.returncode == 0
        return json.dumps({
            "success": success,
            "reloaded": success,
            "message": "Nginx reloaded successfully" if success else "Nginx reload failed",
            "stdout": reload_result.stdout,
            "stderr": reload_result.stderr
        }, indent=2)
        
    except subprocess.TimeoutExpired:
        return json.dumps({
            "success": False,
            "error": "Nginx reload timed out",
            "reloaded": False
        })
    except FileNotFoundError:
        return json.dumps({
            "success": False,
            "error": f"Nginx binary not found: {NGINX_BINARY}",
            "reloaded": False
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "reloaded": False
        })


def nginx_install_config(domain: str, config_content: str, enable: bool = True) -> str:
    """
    Install nginx configuration file.
    
    Args:
        domain: Domain name for the configuration file
        config_content: Nginx configuration content
        enable: Whether to enable the site (create symlink)
        
    Returns:
        JSON string with result
    """
    try:
        # Validate domain
        if not _validate_domain_name(domain):
            return json.dumps({
                "success": False,
                "error": "Invalid domain name",
                "domain": domain
            })
        
        # Validate config content (basic check for dangerous directives)
        dangerous_patterns = [
            r'user\s+root',
            r'worker_processes\s+0',
            r'daemon\s+off',
            r'master_process\s+off',
        ]
        for pattern in dangerous_patterns:
            if re.search(pattern, config_content, re.IGNORECASE):
                return json.dumps({
                    "success": False,
                    "error": f"Configuration contains potentially dangerous pattern: {pattern}"
                })
        
        # Create safe filename
        safe_domain = re.sub(r'[^a-zA-Z0-9._-]', '', domain)
        config_filename = f"{safe_domain}.conf"
        config_path = os.path.join(NGINX_SITES_AVAILABLE, config_filename)
        
        # Check if we have permission to write
        if not os.access(NGINX_SITES_AVAILABLE, os.W_OK):
            return json.dumps({
                "success": False,
                "error": f"No write permission to {NGINX_SITES_AVAILABLE}. Run with sudo.",
                "config_path": config_path
            })
        
        # Write configuration file
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(config_content)
        
        result = {
            "success": True,
            "config_path": config_path,
            "domain": domain,
            "installed": True,
            "message": f"Configuration installed to {config_path}"
        }
        
        # Enable site if requested
        if enable:
            enable_result = nginx_enable_site(domain)
            enable_data = json.loads(enable_result)
            result["enabled"] = enable_data.get("enabled", False)
            if not enable_data.get("success"):
                result["enable_error"] = enable_data.get("error")
        
        return json.dumps(result, indent=2)
        
    except PermissionError as e:
        return json.dumps({
            "success": False,
            "error": f"Permission denied: {str(e)}. Run with sudo.",
            "installed": False
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "installed": False
        })


def nginx_enable_site(domain: str) -> str:
    """
    Enable an nginx site by creating symlink.
    
    Args:
        domain: Domain name of the site to enable
        
    Returns:
        JSON string with result
    """
    try:
        # Validate domain
        if not _validate_domain_name(domain):
            return json.dumps({
                "success": False,
                "error": "Invalid domain name",
                "domain": domain
            })
        
        safe_domain = re.sub(r'[^a-zA-Z0-9._-]', '', domain)
        available_path = os.path.join(NGINX_SITES_AVAILABLE, f"{safe_domain}.conf")
        enabled_path = os.path.join(NGINX_SITES_ENABLED, f"{safe_domain}.conf")
        
        # Check if config exists
        if not os.path.isfile(available_path):
            return json.dumps({
                "success": False,
                "error": f"Configuration not found: {available_path}",
                "available_path": available_path
            })
        
        # Check if already enabled
        if os.path.islink(enabled_path) or os.path.isfile(enabled_path):
            return json.dumps({
                "success": True,
                "enabled": True,
                "domain": domain,
                "message": f"Site {domain} is already enabled"
            })
        
        # Check permissions
        if not os.access(NGINX_SITES_ENABLED, os.W_OK):
            return json.dumps({
                "success": False,
                "error": f"No write permission to {NGINX_SITES_ENABLED}. Run with sudo.",
                "enabled": False
            })
        
        # Create symlink
        os.symlink(available_path, enabled_path)
        
        return json.dumps({
            "success": True,
            "enabled": True,
            "domain": domain,
            "available_path": available_path,
            "enabled_path": enabled_path,
            "message": f"Site {domain} enabled successfully"
        }, indent=2)
        
    except PermissionError as e:
        return json.dumps({
            "success": False,
            "error": f"Permission denied: {str(e)}. Run with sudo.",
            "enabled": False
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "enabled": False
        })


def nginx_disable_site(domain: str) -> str:
    """
    Disable an nginx site by removing symlink.
    
    Args:
        domain: Domain name of the site to disable
        
    Returns:
        JSON string with result
    """
    try:
        # Validate domain
        if not _validate_domain_name(domain):
            return json.dumps({
                "success": False,
                "error": "Invalid domain name",
                "domain": domain
            })
        
        safe_domain = re.sub(r'[^a-zA-Z0-9._-]', '', domain)
        enabled_path = os.path.join(NGINX_SITES_ENABLED, f"{safe_domain}.conf")
        
        # Check if enabled
        if not os.path.islink(enabled_path) and not os.path.isfile(enabled_path):
            return json.dumps({
                "success": True,
                "disabled": True,
                "domain": domain,
                "message": f"Site {domain} is already disabled"
            })
        
        # Check permissions
        if not os.access(enabled_path, os.W_OK) and not os.access(NGINX_SITES_ENABLED, os.W_OK):
            return json.dumps({
                "success": False,
                "error": f"No permission to remove {enabled_path}. Run with sudo.",
                "disabled": False
            })
        
        # Remove symlink
        os.remove(enabled_path)
        
        return json.dumps({
            "success": True,
            "disabled": True,
            "domain": domain,
            "enabled_path": enabled_path,
            "message": f"Site {domain} disabled successfully"
        }, indent=2)
        
    except PermissionError as e:
        return json.dumps({
            "success": False,
            "error": f"Permission denied: {str(e)}. Run with sudo.",
            "disabled": False
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "disabled": False
        })


def nginx_remove_config(domain: str) -> str:
    """
    Remove nginx configuration file for a domain.
    
    Args:
        domain: Domain name of the configuration to remove
        
    Returns:
        JSON string with result
    """
    try:
        # Validate domain
        if not _validate_domain_name(domain):
            return json.dumps({
                "success": False,
                "error": "Invalid domain name",
                "domain": domain
            })
        
        safe_domain = re.sub(r'[^a-zA-Z0-9._-]', '', domain)
        available_path = os.path.join(NGINX_SITES_AVAILABLE, f"{safe_domain}.conf")
        
        # First disable the site
        disable_result = nginx_disable_site(domain)
        disable_data = json.loads(disable_result)
        
        # Check if config exists
        if not os.path.isfile(available_path):
            return json.dumps({
                "success": True,
                "removed": True,
                "domain": domain,
                "message": f"Configuration for {domain} does not exist"
            })
        
        # Check permissions
        if not os.access(available_path, os.W_OK):
            return json.dumps({
                "success": False,
                "error": f"No permission to remove {available_path}. Run with sudo.",
                "removed": False
            })
        
        # Remove configuration
        os.remove(available_path)
        
        return json.dumps({
            "success": True,
            "removed": True,
            "domain": domain,
            "previously_enabled": disable_data.get("disabled", False),
            "config_path": available_path,
            "message": f"Configuration for {domain} removed successfully"
        }, indent=2)
        
    except PermissionError as e:
        return json.dumps({
            "success": False,
            "error": f"Permission denied: {str(e)}. Run with sudo.",
            "removed": False
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "removed": False
        })


def nginx_get_status() -> str:
    """
    Get nginx service status.
    
    Returns:
        JSON string with status information
    """
    try:
        # Check if nginx is running
        result = subprocess.run(
            ["pgrep", "-x", "nginx"],
            capture_output=True,
            timeout=5
        )
        is_running = result.returncode == 0
        
        # Get version
        version_result = subprocess.run(
            [NGINX_BINARY, "-v"],
            capture_output=True,
            text=True,
            timeout=5
        )
        version = version_result.stderr.strip() if version_result.stderr else "unknown"
        
        # Count enabled sites
        enabled_count = 0
        if os.path.isdir(NGINX_SITES_ENABLED):
            enabled_count = len([f for f in os.listdir(NGINX_SITES_ENABLED) if f.endswith('.conf')])
        
        # Count available sites
        available_count = 0
        if os.path.isdir(NGINX_SITES_AVAILABLE):
            available_count = len([f for f in os.listdir(NGINX_SITES_AVAILABLE) if f.endswith('.conf')])
        
        return json.dumps({
            "success": True,
            "running": is_running,
            "version": version,
            "sites_enabled": enabled_count,
            "sites_available": available_count,
            "sites_disabled": available_count - enabled_count,
            "nginx_binary": NGINX_BINARY,
            "sites_available_dir": NGINX_SITES_AVAILABLE,
            "sites_enabled_dir": NGINX_SITES_ENABLED,
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "running": False
        })


def get_nginx_capabilities() -> list[str]:
    """Return list of nginx management capabilities."""
    return [
        "nginx_generate_config",
        "nginx_install_config",
        "nginx_enable_site",
        "nginx_disable_site",
        "nginx_remove_config",
        "nginx_test_config",
        "nginx_reload",
        "nginx_get_status",
    ]
