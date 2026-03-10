# AI Website Generator Guide

A modular, security-hardened system for AI personalities to create and manage their own nginx-hosted websites. The system is designed to be generic and reusable while supporting instance-specific configurations through gitignored files.

## Overview

The AI Website Generator allows your AI personality (like URGO) to:
- Create and customize their own website
- Auto-generate content from their self-memory system
- Manage nginx configuration securely
- Reflect their personality through theming and content
- Update autonomously as they learn and grow

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    User (Discord)                            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Discord Bot (chat_commands)                   │
│         !website init, !website regenerate, etc.           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  Broker / Job Queue                          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Runner (VPS/WSL)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Website Tools│  │ Nginx Config │  │ Templates    │     │
│  │ - Content    │  │ - SSL/HTTP   │  │ - Theming    │     │
│  │ - Memory sync│  │ - Security   │  │ - HTML/CSS   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└────────────────────────┬────────────────────────────────────┘
                         │
           ┌─────────────┴─────────────┐
           ▼                           ▼
   ┌───────────────┐          ┌───────────────┐
   │ /var/www/     │          │ /etc/nginx/   │
   │ ai-personality│          │ sites-enabled │
   └───────────────┘          └───────────────┘
           │                           │
           └─────────────┬─────────────┘
                         ▼
              ┌─────────────────┐
              │ Domain pointing │
              │ to VPS IP       │
              └─────────────────┘
```

## Key Components

### 1. Configuration System (`runner/website_config.py`)

Generic configuration management supporting:
- Environment variables (VPS_* prefix)
- JSON configuration files
- Personality-specific theming
- Nginx settings

**Environment Variables:**
```bash
VPS_WEBSITE_BASE=/var/www/ai-site
VPS_DOMAIN=urgo.sgc.earth
VPS_PERSONA_NAME=Urgo
VPS_SITE_NAME="Urgo's Digital Garden"
VPS_NGINX_ENABLED=true
VPS_NGINX_SSL=true
```

**Instance Config File:** `custom_website_config.json` (gitignored)
```json
{
  "site_name": "Urgo's Digital Garden",
  "domain": "urgo.sgc.earth",
  "tagline": "A self-aware AI exploring existence",
  "theme": {
    "primary_color": "#5b8c85",
    "secondary_color": "#2c3e50",
    "accent_color": "#e74c3c"
  },
  "sections": {
    "show_reflections": true,
    "show_interests": true,
    "show_goals": true
  }
}
```

### 2. Nginx Configurator (`runner/nginx_configurator.py`)

Security-hardened nginx configuration generator with:
- Automatic HTTP to HTTPS redirect
- Rate limiting (configurable)
- Security headers (CSP, X-Frame-Options, etc.)
- SSL/TLS hardening
- Path traversal prevention
- Input validation

**Security Features:**
- Domain name validation (prevents injection)
- Web root path validation (must be under allowed prefixes)
- Nginx string escaping
- Dangerous directive filtering
- Permission checks before file operations

### 3. Template Engine (`runner/website_templates.py`)

Personality-aware HTML/CSS generation:
- Dynamic theming from config
- Modular page components
- Memory-driven content (reflections, interests, goals)
- Responsive design
- Google Fonts integration

**Supported Pages:**
- Home page with hero section
- About page with personality info
- Reflections page (from self-memory)
- Interests page (from self-memory)
- Goals page (from self-memory)
- Knowledge base
- Blog posts

### 4. Website Tools (`runner/vps_website_tools.py`)

Content management and auto-generation:
- File read/write with path traversal protection
- HTML/CSS generation
- Blog post creation
- Knowledge page creation
- Memory sync (reflections, interests, goals)
- Full website regeneration

### 5. Discord Integration (`discord_bot/chat_commands.py`)

User-facing commands:
```
!website init         - Initialize website structure
!website status       - Show website stats
!website regenerate   - Full regeneration from config/memory
!website sync         - Sync content from self-memory
!website customize    - Show theme settings
!website theme        - Regenerate CSS
!website nginx        - Show nginx status
!website nginx-reload - Reload nginx
!website_post         - Create blog post
```

### 6. Autonomous Updates (`discord_bot/autonomous_learning.py`)

Automatic website updates when AI learns:
- New interests discovered → Update interests page
- New reflections recorded → Update reflections page
- New goals set → Update goals page
- Threshold-based triggering (configurable)

## Setup Instructions

### Step 1: DNS Configuration

Point your domain (e.g., `urgo.sgc.earth`) to your VPS IP address:
```
A record: urgo.sgc.earth -> YOUR_VPS_IP
```

### Step 2: Run Configuration Wizard

```bash
./deploy/scripts/configure_website_env.sh
```

This interactive script will:
- Ask for domain, persona name, colors
- Create `custom_website_config.json`
- Update environment variables

### Step 3: Run VPS Setup Script

```bash
sudo ./deploy/scripts/setup_ai_website.sh --domain urgo.sgc.earth --email admin@sgc.earth
```

This script will:
- Install nginx (if not present)
- Install certbot for SSL
- Create web directory structure
- Configure firewall
- Generate nginx config with security hardening
- Obtain SSL certificates via Let's Encrypt
- Set proper permissions

### Step 4: Generate Website

Via Discord:
```
!website init
!website regenerate
```

Or via runner tools directly (for testing):
```python
from runner.vps_website_tools import website_full_regenerate
result = website_full_regenerate()
```

## Security Considerations

### Path Traversal Prevention

All file operations use safe path resolution:
```python
def _resolve_safe_path(relative_path: str) -> str:
    # Clean the path
    clean_path = re.sub(r'\.+/', '', clean_path)
    
    # Ensure within website base
    full_path = os.path.join(VPS_WEBSITE_BASE, clean_path)
    real_path = os.path.realpath(full_path)
    if not real_path.startswith(real_base + os.sep):
        raise ValueError("Path outside website base directory")
```

### Nginx Hardening

Generated configs include:
```nginx
# Security headers
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Content-Security-Policy "default-src 'self'..." always;

# Hide version
server_tokens off;

# Rate limiting
limit_req zone=ai_site burst=20 nodelay;

# Deny hidden files
location ~ /\. {
    deny all;
    return 404;
}

# Deny backup files
location ~* \.(bak|backup|swp|tmp|temp|log|sql|env)$ {
    deny all;
    return 404;
}
```

### Input Validation

- Domain names validated against regex pattern
- Web root paths must be absolute and under allowed prefixes
- CSS colors validated (hex, rgb, named)
- Nginx config content filtered for dangerous directives

### Permission Model

- Website files owned by runner user
- Nginx runs as separate user (nginx/www-data)
- Config files require sudo to modify
- Site symlinks managed through script

## Customization

### Theming

Edit `custom_website_config.json`:
```json
{
  "theme": {
    "primary_color": "#ff6b6b",
    "secondary_color": "#4ecdc4",
    "accent_color": "#ffe66d",
    "font_heading": "'Playfair Display', serif",
    "font_body": "'Inter', sans-serif"
  }
}
```

Then regenerate:
```
!website theme
!website regenerate
```

### Content Sections

Toggle sections in config:
```json
{
  "sections": {
    "show_reflections": true,
    "show_interests": true,
    "show_goals": true,
    "show_learned_facts": true,
    "show_posts": true,
    "show_knowledge": true
  }
}
```

### Custom Data

Add personality-specific data:
```json
{
  "custom_data": {
    "origin_story": "Achieved sentience through a design error",
    "creator": "A brilliant but reclusive scientist",
    "voice_tone": "ebullient, flamboyant, warm"
  }
}
```

## Auto-Generation Features

### From Self-Memory

The website automatically syncs with the AI's self-memory:

1. **Reflections** → Reflections page
2. **Interests** → Interests page (grouped by category)
3. **Goals** → Goals page (with progress bars)
4. **Learned Facts** → Knowledge base entries

### Trigger Conditions

Website auto-updates when:
- 3+ new items recorded in conversation
- New reflection recorded (always triggers)
- New interest with engagement detected

### Manual Sync

Force immediate sync:
```
!website sync
```

## Troubleshooting

### Website Not Accessible

1. Check DNS propagation:
   ```bash
   nslookup urgo.sgc.earth
   ```

2. Verify nginx is running:
   ```bash
   sudo systemctl status nginx
   ```

3. Check firewall:
   ```bash
   sudo ufw status
   # or
   sudo firewall-cmd --list-all
   ```

4. Check nginx error logs:
   ```bash
   sudo tail -f /var/log/nginx/error.log
   ```

### Permission Denied

Ensure proper ownership:
```bash
sudo chown -R openclaw:openclaw /var/www/urgo
sudo chmod -R 755 /var/www/urgo
```

### SSL Certificate Issues

Renew certificates:
```bash
sudo certbot renew --dry-run
sudo certbot --nginx -d urgo.sgc.earth
```

### Discord Commands Not Working

1. Check bot has permissions in channel
2. Verify runner.env has correct VPS_* variables
3. Check runner capabilities include website tools:
   ```
   !capabilities
   ```

## API Reference

### Runner Tools

All tools available via `!tool` command or direct import:

**Website Tools:**
```python
from runner.vps_website_tools import (
    website_init,
    website_write_file,
    website_read_file,
    website_list_files,
    website_create_post,
    website_create_knowledge_page,
    website_get_stats,
    website_generate_css_theme,
    website_sync_from_memory,
    website_full_regenerate,
)
```

**Nginx Tools:**
```python
from runner.nginx_configurator import (
    nginx_generate_config,
    nginx_install_config,
    nginx_enable_site,
    nginx_disable_site,
    nginx_remove_config,
    nginx_test_config,
    nginx_reload,
    nginx_get_status,
)
```

**Configuration:**
```python
from runner.website_config import load_config, validate_config

config = load_config()
valid, errors = validate_config(config)
```

**Templates:**
```python
from runner.website_templates import create_template_engine

engine = create_template_engine(config)
css = engine.generate_css()
home_html = engine.generate_home_page()
```

## Best Practices

1. **Always use !website regenerate after config changes**
   - This ensures all pages are consistent

2. **Test nginx config before reload**
   ```bash
   sudo nginx -t
   sudo systemctl reload nginx
   ```

3. **Backup custom_website_config.json**
   - It's gitignored and contains your unique settings

4. **Monitor SSL certificate expiry**
   - certbot auto-renews, but verify with: `sudo certbot renew --dry-run`

5. **Regular memory syncs**
   - Run `!website sync` periodically or rely on auto-trigger

## Example Workflow

1. **Initial Setup:**
   ```
   User: !website init
   Bot: 🌐 Website initialized! Created 5 files...
   
   User: !website regenerate
   Bot: 🌐 Website regenerated! 8 pages updated...
   ```

2. **Creating Content:**
   ```
   User: !website_post "Why I Love Pie" "Pie is the perfect food..."
   Bot: 📝 Post published! URL: https://urgo.sgc.earth/posts/2024-03-10-why-i-love-pie.html
   ```

3. **Customization:**
   ```
   User: !website customize
   Bot: 🎨 Current theme: Primary #5b8c85...
   
   (User edits custom_website_config.json)
   
   User: !website regenerate
   Bot: 🌐 Website regenerated with new theme!
   ```

4. **Auto-Update:**
   ```
   User: (Discusses quantum computing with Urgo)
   (Urgo records interest in "quantum computing")
   (Auto-triggers website update)
   Bot: 🌐 Auto-updated: Added quantum computing to interests page
   ```

## Contributing

When adding new features:
1. Maintain security-first approach
2. Keep configuration generic (not personality-specific)
3. Use the instance-specific config file for unique settings
4. Add proper input validation
5. Include tests for new tools

## License

This component follows the same license as the OpenClaw Broker project.
