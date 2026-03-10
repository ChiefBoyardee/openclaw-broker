"""
Generic website configuration system for AI personality websites.

Provides a flexible, reusable configuration loader that supports:
- Environment variable configuration
- Instance-specific JSON config files
- Personality-aware theming
- Security-validated settings
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional
from dataclasses import dataclass, field


# Default configuration values
DEFAULTS = {
    "VPS_WEBSITE_BASE": "/var/www/ai-site",
    "VPS_DOMAIN": "localhost",
    "VPS_PERSONA_NAME": "assistant",
    "VPS_PERSONALITY_FILE": "",
    "VPS_NGINX_ENABLED": "true",
    "VPS_NGINX_SSL": "false",
    "VPS_NGINX_CERT_PATH": "/etc/letsencrypt/live",
    "VPS_MAX_FILE_SIZE": "500000",
    "VPS_RATE_LIMIT_RPS": "10",
    "VPS_RATE_LIMIT_BURST": "20",
}


@dataclass
class WebsiteTheme:
    """Theme configuration for AI personality websites."""
    primary_color: str = "#5b8c85"
    secondary_color: str = "#2c3e50"
    accent_color: str = "#e74c3c"
    background_color: str = "#f8f9fa"
    text_color: str = "#333333"
    font_heading: str = "system-ui, -apple-system, sans-serif"
    font_body: str = "system-ui, -apple-system, sans-serif"
    max_width: str = "800px"
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebsiteTheme":
        """Create theme from dictionary with validation."""
        validated = {}
        for key, default in cls.__dataclass_fields__.items():
            value = data.get(key, default.default)
            # Validate CSS color values
            if "color" in key and not _is_valid_css_color(str(value)):
                value = default.default
            validated[key] = value
        return cls(**validated)


@dataclass
class WebsiteSections:
    """Configuration for which sections to show on the website."""
    show_reflections: bool = True
    show_interests: bool = True
    show_goals: bool = True
    show_learned_facts: bool = True
    show_about: bool = True
    show_posts: bool = True
    show_knowledge: bool = True
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebsiteSections":
        """Create sections config from dictionary."""
        return cls(**{
            key: data.get(key, default.default)
            for key, default in cls.__dataclass_fields__.items()
        })


@dataclass
class NginxConfig:
    """Nginx-specific configuration."""
    ssl_certificate: str = ""
    ssl_certificate_key: str = ""
    ssl_dhparam: str = ""
    rate_limit_zone: str = "ai_site"
    rate_limit_requests_per_second: int = 10
    rate_limit_burst: int = 20
    security_headers: Dict[str, str] = field(default_factory=lambda: {
        "X-Frame-Options": "SAMEORIGIN",
        "X-Content-Type-Options": "nosniff",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    })
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NginxConfig":
        """Create nginx config from dictionary."""
        headers = data.get("security_headers", {})
        default_headers = cls.__dataclass_fields__["security_headers"].default_factory()
        default_headers.update(headers)
        
        return cls(
            ssl_certificate=data.get("ssl_certificate", ""),
            ssl_certificate_key=data.get("ssl_certificate_key", ""),
            ssl_dhparam=data.get("ssl_dhparam", ""),
            rate_limit_zone=data.get("rate_limit_zone", "ai_site"),
            rate_limit_requests_per_second=data.get("rate_limit_requests_per_second", 10),
            rate_limit_burst=data.get("rate_limit_burst", 20),
            security_headers=default_headers,
        )


@dataclass
class WebsiteConfig:
    """Complete website configuration for an AI personality."""
    site_name: str = "AI Digital Garden"
    domain: str = "localhost"
    tagline: str = "A collection of thoughts, learnings, and discoveries."
    description: str = "An AI personality website with autonomous content generation."
    persona_name: str = "assistant"
    base_path: str = "/var/www/ai-site"
    max_file_size: int = 500000
    theme: WebsiteTheme = field(default_factory=WebsiteTheme)
    sections: WebsiteSections = field(default_factory=WebsiteSections)
    nginx: NginxConfig = field(default_factory=NginxConfig)
    custom_data: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_environment(cls) -> "WebsiteConfig":
        """Load configuration from environment variables."""
        return cls(
            site_name=os.environ.get("VPS_SITE_NAME", "AI Digital Garden"),
            domain=os.environ.get("VPS_DOMAIN", "localhost"),
            tagline=os.environ.get("VPS_TAGLINE", "A collection of thoughts, learnings, and discoveries."),
            description=os.environ.get("VPS_DESCRIPTION", "An AI personality website with autonomous content generation."),
            persona_name=os.environ.get("VPS_PERSONA_NAME", "assistant"),
            base_path=os.environ.get("VPS_WEBSITE_BASE", "/var/www/ai-site"),
            max_file_size=int(os.environ.get("VPS_MAX_FILE_SIZE", "500000")),
        )
    
    @classmethod
    def from_json_file(cls, path: str) -> "WebsiteConfig":
        """Load configuration from JSON file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data)
        except (FileNotFoundError, json.JSONDecodeError, PermissionError):
            return cls.from_environment()
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebsiteConfig":
        """Create config from dictionary."""
        return cls(
            site_name=data.get("site_name", "AI Digital Garden"),
            domain=data.get("domain", "localhost"),
            tagline=data.get("tagline", "A collection of thoughts, learnings, and discoveries."),
            description=data.get("description", "An AI personality website with autonomous content generation."),
            persona_name=data.get("persona_name", "assistant"),
            base_path=data.get("base_path", "/var/www/ai-site"),
            max_file_size=data.get("max_file_size", 500000),
            theme=WebsiteTheme.from_dict(data.get("theme", {})),
            sections=WebsiteSections.from_dict(data.get("sections", {})),
            nginx=NginxConfig.from_dict(data.get("nginx", {})),
            custom_data=data.get("custom_data", {}),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "site_name": self.site_name,
            "domain": self.domain,
            "tagline": self.tagline,
            "description": self.description,
            "persona_name": self.persona_name,
            "base_path": self.base_path,
            "max_file_size": self.max_file_size,
            "theme": {
                "primary_color": self.theme.primary_color,
                "secondary_color": self.theme.secondary_color,
                "accent_color": self.theme.accent_color,
                "background_color": self.theme.background_color,
                "text_color": self.theme.text_color,
                "font_heading": self.theme.font_heading,
                "font_body": self.theme.font_body,
                "max_width": self.theme.max_width,
            },
            "sections": {
                "show_reflections": self.sections.show_reflections,
                "show_interests": self.sections.show_interests,
                "show_goals": self.sections.show_goals,
                "show_learned_facts": self.sections.show_learned_facts,
                "show_about": self.sections.show_about,
                "show_posts": self.sections.show_posts,
                "show_knowledge": self.sections.show_knowledge,
            },
            "nginx": {
                "ssl_certificate": self.nginx.ssl_certificate,
                "ssl_certificate_key": self.nginx.ssl_certificate_key,
                "ssl_dhparam": self.nginx.ssl_dhparam,
                "rate_limit_zone": self.nginx.rate_limit_zone,
                "rate_limit_requests_per_second": self.nginx.rate_limit_requests_per_second,
                "rate_limit_burst": self.nginx.rate_limit_burst,
                "security_headers": self.nginx.security_headers,
            },
            "custom_data": self.custom_data,
        }
    
    def save_to_file(self, path: str) -> None:
        """Save configuration to JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)


def _is_valid_css_color(color: str) -> bool:
    """Validate CSS color value."""
    if not color:
        return True  # Empty is valid (will use default)
    
    # Hex color (#RGB or #RRGGBB)
    if color.startswith("#"):
        hex_part = color[1:]
        return len(hex_part) in (3, 6) and all(c in "0123456789ABCDEFabcdef" for c in hex_part)
    
    # RGB/RGBA
    if color.startswith("rgb"):
        return True  # Simplified validation
    
    # HSL/HSLA
    if color.startswith("hsl"):
        return True  # Simplified validation
    
    # Named colors (common ones)
    named_colors = {
        "black", "white", "red", "green", "blue", "yellow", "cyan", "magenta",
        "gray", "grey", "silver", "maroon", "olive", "lime", "aqua", "teal",
        "navy", "fuchsia", "purple", "orange", "pink", "brown", "transparent",
    }
    if color.lower() in named_colors:
        return True
    
    return False


def load_config(
    env_prefix: str = "VPS_",
    json_path: Optional[str] = None,
    persona_file: Optional[str] = None,
) -> WebsiteConfig:
    """
    Load website configuration from multiple sources.
    
    Priority order (highest to lowest):
    1. Instance-specific JSON config file
    2. Environment variables
    3. Default values
    
    Args:
        env_prefix: Prefix for environment variables
        json_path: Path to JSON config file (default: custom_website_config.json)
        persona_file: Path to persona configuration file
        
    Returns:
        WebsiteConfig instance
    """
    # Start with environment variables
    config = WebsiteConfig.from_environment()
    
    # Override with JSON file if provided or found
    json_path = json_path or os.environ.get("VPS_CONFIG_FILE", "custom_website_config.json")
    if os.path.isfile(json_path):
        file_config = WebsiteConfig.from_json_file(json_path)
        # Merge: JSON file takes precedence
        config.site_name = file_config.site_name or config.site_name
        config.domain = file_config.domain or config.domain
        config.tagline = file_config.tagline or config.tagline
        config.description = file_config.description or config.description
        config.persona_name = file_config.persona_name or config.persona_name
        config.base_path = file_config.base_path or config.base_path
        config.theme = file_config.theme
        config.sections = file_config.sections
        config.nginx = file_config.nginx
        config.custom_data = file_config.custom_data
    
    # Load persona file if specified
    persona_file = persona_file or os.environ.get("VPS_PERSONALITY_FILE", "")
    if persona_file and os.path.isfile(persona_file):
        try:
            with open(persona_file, "r", encoding="utf-8") as f:
                persona_data = json.load(f)
            # Extract persona-specific settings
            if "urgo" in persona_data and isinstance(persona_data["urgo"], dict):
                urgo = persona_data["urgo"]
                config.custom_data["persona"] = urgo
                # Auto-set site name from persona if not explicitly configured
                if config.site_name == "AI Digital Garden" and "name" in urgo:
                    config.site_name = f"{urgo['name']}'s Digital Garden"
        except (json.JSONDecodeError, PermissionError):
            pass  # Ignore persona file errors
    
    return config


def get_default_config() -> WebsiteConfig:
    """Get default website configuration."""
    return WebsiteConfig()


def validate_domain(domain: str) -> bool:
    """
    Validate domain name format.
    
    Args:
        domain: Domain name to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not domain or not isinstance(domain, str):
        return False
    
    # Remove trailing dot if present
    domain = domain.rstrip(".")
    
    # Check length (max 253 characters for full domain, 63 per label)
    if len(domain) > 253:
        return False
    
    # Domain pattern: labels separated by dots
    # Each label: alphanumeric, can contain hyphens (not start/end)
    pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$'
    
    return bool(re.match(pattern, domain))


def validate_config(config: WebsiteConfig) -> tuple[bool, list[str]]:
    """
    Validate website configuration.
    
    Args:
        config: Configuration to validate
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    # Validate domain
    if not validate_domain(config.domain):
        errors.append(f"Invalid domain: {config.domain}")
    
    # Validate base path (should be absolute and safe)
    if not config.base_path.startswith("/"):
        errors.append(f"Base path must be absolute: {config.base_path}")
    
    if ".." in config.base_path:
        errors.append(f"Base path contains unsafe traversal: {config.base_path}")
    
    # Validate file size
    if config.max_file_size < 1000 or config.max_file_size > 10000000:
        errors.append(f"Max file size seems unreasonable: {config.max_file_size}")
    
    # Validate nginx SSL paths if SSL is configured
    if config.nginx.ssl_certificate and not config.nginx.ssl_certificate.startswith("/"):
        errors.append(f"SSL certificate path must be absolute: {config.nginx.ssl_certificate}")
    
    if config.nginx.ssl_certificate_key and not config.nginx.ssl_certificate_key.startswith("/"):
        errors.append(f"SSL key path must be absolute: {config.nginx.ssl_certificate_key}")
    
    return len(errors) == 0, errors
