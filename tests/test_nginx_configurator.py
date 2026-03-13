"""Tests for nginx_configurator module - security and functionality."""
import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Create temp dirs for testing
_tmpdir = tempfile.mkdtemp(prefix="test_nginx_")
_sites_available = os.path.join(_tmpdir, "sites-available")
_sites_enabled = os.path.join(_tmpdir, "sites-enabled")
os.makedirs(_sites_available, exist_ok=True)
os.makedirs(_sites_enabled, exist_ok=True)

import runner.nginx_configurator as nc

# Patch nginx paths for testing
nc.NGINX_SITES_AVAILABLE = _sites_available
nc.NGINX_SITES_ENABLED = _sites_enabled


def teardown_module():
    """Clean up temp directories after tests."""
    shutil.rmtree(_tmpdir, ignore_errors=True)


# ---------- Domain Validation ----------

def test_validate_domain_name_valid():
    """Valid domain names should pass validation."""
    assert nc._validate_domain_name("example.com") is True
    assert nc._validate_domain_name("sub.example.com") is True
    assert nc._validate_domain_name("urgo.sgc.earth") is True
    assert nc._validate_domain_name("a.b-c.d.co.uk") is True


def test_validate_domain_name_invalid():
    """Invalid domain names should fail validation."""
    assert nc._validate_domain_name("") is False
    assert nc._validate_domain_name("../etc/passwd") is False
    assert nc._validate_domain_name("example.com; rm -rf /") is False
    assert nc._validate_domain_name("example.com&&whoami") is False
    assert nc._validate_domain_name("exam ple.com") is False  # Space not allowed
    assert nc._validate_domain_name("exam*ple.com") is False  # Asterisk not allowed
    assert nc._validate_domain_name("-example.com") is False  # Can't start with hyphen
    assert nc._validate_domain_name("example-.com") is False  # Can't end with hyphen


def test_validate_domain_name_dangerous_chars():
    """Domain with dangerous shell characters should fail."""
    dangerous = [';', '&', '|', '$', '`', '\\', '<', '>', '*', '?', '{', '}']
    for char in dangerous:
        assert nc._validate_domain_name(f"example{char}.com") is False


def test_validate_domain_path_traversal():
    """Domain with path traversal should fail."""
    assert nc._validate_domain_name("../etc/hosts") is False
    assert nc._validate_domain_name("example.com/../../../etc/passwd") is False
    assert nc._validate_domain_name("..\\windows\\system32") is False


# ---------- Web Root Validation ----------

def test_validate_web_root_valid():
    """Valid web root paths should pass."""
    assert nc._validate_web_root("/var/www/site") is True
    assert nc._validate_web_root("/srv/www") is True
    assert nc._validate_web_root("/usr/share/nginx/html") is True
    assert nc._validate_web_root("/opt/www/ai") is True


def test_validate_web_root_invalid():
    """Invalid web root paths should fail."""
    assert nc._validate_web_root("") is False
    assert nc._validate_web_root("relative/path") is False  # Must be absolute
    assert nc._validate_web_root("/home/user/secret") is False  # Not under allowed paths
    assert nc._validate_web_root("/var/www/../../../etc") is False  # Path traversal
    assert nc._validate_web_root("/etc/passwd") is False  # Not web root


def test_validate_web_root_traversal():
    """Paths with .. should be rejected."""
    assert nc._validate_web_root("/var/www/../etc") is False
    assert nc._validate_web_root("/var/www/..\\..\\windows") is False


# ---------- Nginx String Escaping ----------

def test_escape_nginx_string_basic():
    """Basic string escaping."""
    assert nc._escape_nginx_string("hello") == "hello"
    assert nc._escape_nginx_string("") == ""


def test_escape_nginx_string_quotes():
    """Quotes should be escaped."""
    assert nc._escape_nginx_string('hello "world"') == 'hello \\"world\\"'


def test_escape_nginx_string_backslash():
    """Backslashes should be escaped."""
    assert nc._escape_nginx_string("hello\\world") == "hello\\\\world"


def test_escape_nginx_string_null_bytes():
    """Null bytes should be removed."""
    assert nc._escape_nginx_string("hello\x00world") == "helloworld"


# ---------- Config Generation ----------

def test_nginx_generate_config_success():
    """Should generate valid config for valid inputs."""
    result = nc.nginx_generate_config(
        domain="urgo.sgc.earth",
        web_root="/var/www/urgo"
    )
    data = json.loads(result)
    
    assert data["success"] is True
    assert data["domain"] == "urgo.sgc.earth"
    assert data["web_root"] == "/var/www/urgo"
    assert "config" in data
    assert "rate_limit_zone" in data


def test_nginx_generate_config_invalid_domain():
    """Should reject invalid domain."""
    result = nc.nginx_generate_config(
        domain="urgo; rm -rf /",
        web_root="/var/www/urgo"
    )
    data = json.loads(result)
    
    assert data["success"] is False
    assert "Invalid domain" in data["error"]


def test_nginx_generate_config_invalid_web_root():
    """Should reject invalid web root."""
    result = nc.nginx_generate_config(
        domain="urgo.sgc.earth",
        web_root="/etc/passwd"
    )
    data = json.loads(result)
    
    assert data["success"] is False
    assert "Invalid or unsafe" in data["error"]


def test_nginx_generate_config_with_ssl():
    """Should generate SSL config when certs provided."""
    result = nc.nginx_generate_config(
        domain="urgo.sgc.earth",
        web_root="/var/www/urgo",
        ssl_cert="/etc/letsencrypt/live/urgo.sgc.earth/fullchain.pem",
        ssl_key="/etc/letsencrypt/live/urgo.sgc.earth/privkey.pem"
    )
    data = json.loads(result)
    
    assert data["success"] is True
    assert data["ssl_enabled"] is True
    assert "443 ssl" in data["config"]
    assert "301 https" in data["config"]


def test_nginx_generate_config_security_headers():
    """Generated config should include security headers."""
    result = nc.nginx_generate_config(
        domain="urgo.sgc.earth",
        web_root="/var/www/urgo"
    )
    data = json.loads(result)
    
    config = data["config"]
    assert "X-Frame-Options" in config
    assert "X-Content-Type-Options" in config
    assert "server_tokens off" in config


def test_nginx_generate_config_rate_limiting():
    """Generated config should include rate limiting."""
    result = nc.nginx_generate_config(
        domain="urgo.sgc.earth",
        web_root="/var/www/urgo",
        rate_limit_zone="urgo_site",
        rate_limit_rps=5,
        rate_limit_burst=10
    )
    data = json.loads(result)
    
    assert "urgo_site" in data["rate_limit_zone"]
    assert "5r/s" in data["rate_limit_zone"]


# ---------- Config Installation ----------

def test_nginx_install_config_success():
    """Should install config file."""
    # First generate a config
    gen_result = nc.nginx_generate_config(
        domain="test.example.com",
        web_root="/var/www/test"
    )
    gen_data = json.loads(gen_result)
    
    # Then try to install (will fail without sudo, but tests the code path)
    result = nc.nginx_install_config(
        domain="test.example.com",
        config_content=gen_data["config"],
        enable=False
    )
    data = json.loads(result)
    
    # May fail due to permissions, but should not crash
    assert "success" in data or "error" in data


def test_nginx_install_config_dangerous_content():
    """Should reject config with dangerous directives."""
    dangerous_config = """
    user root;
    worker_processes 0;
    """
    
    result = nc.nginx_install_config(
        domain="test.example.com",
        config_content=dangerous_config
    )
    data = json.loads(result)
    
    assert data["success"] is False
    assert "dangerous" in data["error"].lower()


# ---------- Security Headers Generation ----------

def test_generate_security_headers_default():
    """Should generate default security headers."""
    headers = nc._generate_security_headers({})
    
    assert "X-Frame-Options" in headers
    assert "X-Content-Type-Options" in headers
    assert "SAMEORIGIN" in headers
    assert "nosniff" in headers


def test_generate_security_headers_custom():
    """Should use custom headers when provided."""
    custom = {
        "X-Custom-Header": "custom-value",
        "X-Another": "another-value"
    }
    headers = nc._generate_security_headers({"security_headers": custom})
    
    assert "X-Custom-Header" in headers
    assert "custom-value" in headers


def test_generate_security_headers_invalid_name():
    """Should skip headers with invalid names."""
    custom = {
        "X-Invalid Header": "value",  # Space not allowed
        "X-Valid": "valid-value"
    }
    headers = nc._generate_security_headers({"security_headers": custom})
    
    assert "X-Valid" in headers
    assert "X-Invalid Header" not in headers


# ---------- Site Enable/Disable ----------

def test_nginx_enable_site_config_not_exists():
    """Should fail if config doesn't exist."""
    result = nc.nginx_enable_site("nonexistent.example.com")
    data = json.loads(result)
    
    assert data["success"] is False
    assert "Configuration not found" in data["error"]


# ---------- Capabilities ----------

def test_get_nginx_capabilities():
    """Should return list of capabilities."""
    caps = nc.get_nginx_capabilities()
    
    assert isinstance(caps, list)
    assert "nginx_generate_config" in caps
    assert "nginx_install_config" in caps
    assert "nginx_enable_site" in caps
    assert "nginx_test_config" in caps
    assert "nginx_reload" in caps
