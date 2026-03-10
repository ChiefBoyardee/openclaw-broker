"""Tests for website_config module - configuration management."""
import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runner.website_config import (
    WebsiteConfig,
    WebsiteTheme,
    WebsiteSections,
    NginxConfig,
    load_config,
    validate_config,
    validate_domain,
    _is_valid_css_color,
)


def test_website_theme_defaults():
    """Theme should have sensible defaults."""
    theme = WebsiteTheme()
    
    assert theme.primary_color == "#5b8c85"
    assert theme.secondary_color == "#2c3e50"
    assert theme.accent_color == "#e74c3c"
    assert theme.font_body == "system-ui, -apple-system, sans-serif"


def test_website_theme_from_dict():
    """Theme should load from dict with validation."""
    data = {
        "primary_color": "#ff0000",
        "secondary_color": "#00ff00",
        "accent_color": "invalid",  # Invalid, should use default
        "font_heading": "Custom Font"
    }
    theme = WebsiteTheme.from_dict(data)
    
    assert theme.primary_color == "#ff0000"
    assert theme.secondary_color == "#00ff00"
    assert theme.accent_color == "#e74c3c"  # Default (invalid input)
    assert theme.font_heading == "Custom Font"


def test_website_sections_defaults():
    """Sections should default to enabled."""
    sections = WebsiteSections()
    
    assert sections.show_reflections is True
    assert sections.show_interests is True
    assert sections.show_goals is True
    assert sections.show_about is True


def test_website_sections_from_dict():
    """Sections should load from dict."""
    data = {
        "show_reflections": False,
        "show_interests": True,
        "show_goals": False
    }
    sections = WebsiteSections.from_dict(data)
    
    assert sections.show_reflections is False
    assert sections.show_interests is True
    assert sections.show_goals is False
    assert sections.show_about is True  # Default


def test_website_config_defaults():
    """Config should have sensible defaults."""
    config = WebsiteConfig()
    
    assert config.site_name == "AI Digital Garden"
    assert config.domain == "localhost"
    assert config.base_path == "/var/www/ai-site"
    assert config.max_file_size == 500000
    assert isinstance(config.theme, WebsiteTheme)
    assert isinstance(config.sections, WebsiteSections)
    assert isinstance(config.nginx, NginxConfig)


def test_website_config_to_dict():
    """Config should serialize to dict."""
    config = WebsiteConfig(
        site_name="Test Site",
        domain="test.example.com"
    )
    data = config.to_dict()
    
    assert data["site_name"] == "Test Site"
    assert data["domain"] == "test.example.com"
    assert "theme" in data
    assert "sections" in data
    assert "nginx" in data


def test_website_config_save_and_load():
    """Config should save and load correctly."""
    tmpdir = tempfile.mkdtemp()
    try:
        config_path = os.path.join(tmpdir, "test_config.json")
        
        # Create and save
        config = WebsiteConfig(
            site_name="Test Site",
            domain="test.example.com",
            theme=WebsiteTheme(primary_color="#123456")
        )
        config.save_to_file(config_path)
        
        # Load
        loaded = WebsiteConfig.from_json_file(config_path)
        
        assert loaded.site_name == "Test Site"
        assert loaded.domain == "test.example.com"
        assert loaded.theme.primary_color == "#123456"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_validate_domain_valid():
    """Valid domains should pass validation."""
    assert validate_domain("example.com") is True
    assert validate_domain("sub.example.com") is True
    assert validate_domain("urgo.sgc.earth") is True
    assert validate_domain("a-b.co.uk") is True
    assert validate_domain("test123.example456.com") is True


def test_validate_domain_invalid():
    """Invalid domains should fail validation."""
    assert validate_domain("") is False
    assert validate_domain("not a domain") is False
    assert validate_domain("-example.com") is False  # Can't start with hyphen
    assert validate_domain("example-.com") is False  # Can't end with hyphen
    assert validate_domain("exam..ple.com") is False  # Double dot


def test_is_valid_css_color_hex():
    """Hex colors should be validated."""
    assert _is_valid_css_color("#fff") is True
    assert _is_valid_css_color("#FFF") is True
    assert _is_valid_css_color("#123abc") is True
    assert _is_valid_css_color("#123ABc") is True
    assert _is_valid_css_color("#12345") is False  # Wrong length
    assert _is_valid_css_color("#ggg") is False  # Invalid hex
    assert _is_valid_css_color("123abc") is False  # Missing #


def test_is_valid_css_color_named():
    """Named colors should be validated."""
    assert _is_valid_css_color("red") is True
    assert _is_valid_css_color("blue") is True
    assert _is_valid_css_color("transparent") is True
    assert _is_valid_css_color("invalidcolorname") is False


def test_is_valid_css_color_rgb():
    """RGB colors should be validated."""
    assert _is_valid_css_color("rgb(255, 0, 0)") is True
    assert _is_valid_css_color("rgba(255, 0, 0, 0.5)") is True


def test_is_valid_css_color_empty():
    """Empty color should be valid (uses default)."""
    assert _is_valid_css_color("") is True
    assert _is_valid_css_color(None) is True


def test_validate_config_valid():
    """Valid config should pass validation."""
    config = WebsiteConfig(
        domain="test.example.com",
        base_path="/var/www/test"
    )
    
    is_valid, errors = validate_config(config)
    
    assert is_valid is True
    assert len(errors) == 0


def test_validate_config_invalid_domain():
    """Config with invalid domain should fail."""
    config = WebsiteConfig(
        domain="not a valid domain",
        base_path="/var/www/test"
    )
    
    is_valid, errors = validate_config(config)
    
    assert is_valid is False
    assert any("domain" in e.lower() for e in errors)


def test_validate_config_relative_path():
    """Config with relative base path should fail."""
    config = WebsiteConfig(
        domain="test.example.com",
        base_path="relative/path"
    )
    
    is_valid, errors = validate_config(config)
    
    assert is_valid is False
    assert any("absolute" in e.lower() for e in errors)


def test_validate_config_traversal_path():
    """Config with path traversal should fail."""
    config = WebsiteConfig(
        domain="test.example.com",
        base_path="/var/www/../../../etc"
    )
    
    is_valid, errors = validate_config(config)
    
    assert is_valid is False
    assert any("traversal" in e.lower() or "unsafe" in e.lower() for e in errors)


def test_load_config_from_file():
    """Config should load from file."""
    tmpdir = tempfile.mkdtemp()
    try:
        config_path = os.path.join(tmpdir, "custom_website_config.json")
        
        # Create config file
        test_config = {
            "site_name": "File Test",
            "domain": "file.example.com",
            "theme": {
                "primary_color": "#abcdef"
            }
        }
        
        with open(config_path, "w") as f:
            json.dump(test_config, f)
        
        # Load config
        config = load_config(json_path=config_path)
        
        assert config.site_name == "File Test"
        assert config.domain == "file.example.com"
        assert config.theme.primary_color == "#abcdef"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_load_config_missing_file():
    """Should use defaults if config file missing."""
    config = load_config(json_path="/nonexistent/path/config.json")
    
    # Should have default values
    assert config.site_name == "AI Digital Garden"  # From environment


def test_nginx_config_defaults():
    """NginxConfig should have sensible defaults."""
    nginx = NginxConfig()
    
    assert nginx.ssl_certificate == ""
    assert nginx.ssl_certificate_key == ""
    assert nginx.rate_limit_zone == "ai_site"
    assert nginx.rate_limit_requests_per_second == 10
    assert nginx.rate_limit_burst == 20
    assert isinstance(nginx.security_headers, dict)
