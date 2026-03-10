#!/usr/bin/env bash
# Setup AI Website on VPS
# 
# This script sets up nginx, SSL certificates, and permissions for an AI personality
# website. It creates a complete, secure web hosting environment.
#
# Usage: sudo ./deploy/scripts/setup_ai_website.sh [options]
# Options:
#   --domain DOMAIN         Domain name (e.g., urgo.sgc.earth)
#   --web-root PATH         Web root directory (default: /var/www/ai-site)
#   --email EMAIL           Email for Let's Encrypt SSL certificates
#   --skip-ssl              Skip SSL certificate setup (use HTTP only)
#   --skip-nginx            Skip nginx installation (assume already installed)
#   --skip-firewall         Skip firewall configuration
#   --persona-name NAME     Name of the AI persona
#   --help                  Show this help message
#
# Examples:
#   sudo ./deploy/scripts/setup_ai_website.sh --domain urgo.sgc.earth --email admin@sgc.earth
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
DOMAIN=""
WEB_ROOT="/var/www/ai-site"
EMAIL=""
SKIP_SSL=false
SKIP_NGINX=false
SKIP_FIREWALL=false
PERSONA_NAME="assistant"
RUNNER_USER="openclaw"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --domain)
            DOMAIN="$2"
            shift 2
            ;;
        --web-root)
            WEB_ROOT="$2"
            shift 2
            ;;
        --email)
            EMAIL="$2"
            shift 2
            ;;
        --skip-ssl)
            SKIP_SSL=true
            shift
            ;;
        --skip-nginx)
            SKIP_NGINX=true
            shift
            ;;
        --skip-firewall)
            SKIP_FIREWALL=true
            shift
            ;;
        --persona-name)
            PERSONA_NAME="$2"
            shift 2
            ;;
        --help)
            echo "AI Website Setup Script"
            echo ""
            echo "Usage: sudo $0 [options]"
            echo ""
            echo "Options:"
            echo "  --domain DOMAIN         Domain name (e.g., urgo.sgc.earth)"
            echo "  --web-root PATH         Web root directory (default: /var/www/ai-site)"
            echo "  --email EMAIL           Email for Let's Encrypt SSL certificates"
            echo "  --skip-ssl              Skip SSL certificate setup (use HTTP only)"
            echo "  --skip-nginx            Skip nginx installation (assume already installed)"
            echo "  --skip-firewall         Skip firewall configuration"
            echo "  --persona-name NAME     Name of the AI persona"
            echo "  --help                  Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}This script must be run as root (use sudo)${NC}"
   exit 1
fi

# Get domain if not provided
if [[ -z "$DOMAIN" ]]; then
    echo -e "${BLUE}Enter the domain name for the AI website:${NC}"
    read -r DOMAIN
    if [[ -z "$DOMAIN" ]]; then
        echo -e "${RED}Domain is required${NC}"
        exit 1
    fi
fi

# Get email if not provided and not skipping SSL
if [[ "$SKIP_SSL" == false && -z "$EMAIL" ]]; then
    echo -e "${BLUE}Enter email address for SSL certificate notifications:${NC}"
    read -r EMAIL
    if [[ -z "$EMAIL" ]]; then
        echo -e "${YELLOW}No email provided, SSL setup will be skipped${NC}"
        SKIP_SSL=true
    fi
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  AI Website Setup${NC}"
echo -e "${GREEN}========================================${NC}"
echo "Domain: $DOMAIN"
echo "Web Root: $WEB_ROOT"
echo "Persona: $PERSONA_NAME"
echo "SSL: $([[ $SKIP_SSL == false ]] && echo 'enabled' || echo 'disabled')"
echo ""

# Detect OS
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    OS=$NAME
    VER=$VERSION_ID
else
    echo -e "${RED}Cannot detect OS${NC}"
    exit 1
fi

echo -e "${BLUE}Detected OS: $OS $VER${NC}"

# Install nginx if not skipped
if [[ "$SKIP_NGINX" == false ]]; then
    echo -e "${BLUE}Installing nginx...${NC}"
    
    if [[ "$OS" == *"Ubuntu"* ]] || [[ "$OS" == *"Debian"* ]]; then
        apt-get update
        apt-get install -y nginx
    elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Rocky"* ]] || [[ "$OS" == *"Alma"* ]] || [[ "$OS" == *"RHEL"* ]]; then
        dnf install -y nginx
        systemctl enable nginx
    elif [[ "$OS" == *"Fedora"* ]]; then
        dnf install -y nginx
        systemctl enable nginx
    else
        echo -e "${YELLOW}Unknown OS, please install nginx manually${NC}"
        SKIP_NGINX=true
    fi
    
    if [[ "$SKIP_NGINX" == false ]]; then
        echo -e "${GREEN}Nginx installed successfully${NC}"
    fi
fi

# Install certbot for SSL if not skipped
if [[ "$SKIP_SSL" == false ]]; then
    echo -e "${BLUE}Installing certbot for SSL certificates...${NC}"
    
    if [[ "$OS" == *"Ubuntu"* ]] || [[ "$OS" == *"Debian"* ]]; then
        apt-get install -y certbot python3-certbot-nginx
    elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Rocky"* ]] || [[ "$OS" == *"Alma"* ]] || [[ "$OS" == *"RHEL"* ]]; then
        dnf install -y certbot python3-certbot-nginx
    elif [[ "$OS" == *"Fedora"* ]]; then
        dnf install -y certbot python3-certbot-nginx
    else
        echo -e "${YELLOW}Unknown OS, please install certbot manually${NC}"
        SKIP_SSL=true
    fi
    
    if [[ "$SKIP_SSL" == false ]]; then
        echo -e "${GREEN}Certbot installed successfully${NC}"
    fi
fi

# Configure firewall if not skipped
if [[ "$SKIP_FIREWALL" == false ]]; then
    echo -e "${BLUE}Configuring firewall...${NC}"
    
    if command -v ufw &> /dev/null; then
        # UFW (Ubuntu/Debian)
        ufw allow 'Nginx Full'
        ufw allow OpenSSH
        echo -e "${GREEN}UFW rules added${NC}"
    elif command -v firewall-cmd &> /dev/null; then
        # firewalld (RHEL/CentOS/Rocky)
        firewall-cmd --permanent --add-service=http
        firewall-cmd --permanent --add-service=https
        firewall-cmd --reload
        echo -e "${GREEN}Firewalld rules added${NC}"
    else
        echo -e "${YELLOW}No recognized firewall found, skipping firewall configuration${NC}"
    fi
fi

# Create web root directory
echo -e "${BLUE}Creating web root directory...${NC}"
mkdir -p "$WEB_ROOT"
mkdir -p "$WEB_ROOT/posts"
mkdir -p "$WEB_ROOT/knowledge"
mkdir -p "$WEB_ROOT/projects"
mkdir -p "$WEB_ROOT/assets"
mkdir -p "$WEB_ROOT/css"

# Create a basic index.html if it doesn't exist
if [[ ! -f "$WEB_ROOT/index.html" ]]; then
    echo -e "${BLUE}Creating placeholder index.html...${NC}"
    cat > "$WEB_ROOT/index.html" << EOF
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${PERSONA_NAME}'s Website - Coming Soon</title>
    <style>
        body {
            font-family: system-ui, -apple-system, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-align: center;
        }
        .container {
            max-width: 600px;
            padding: 2rem;
        }
        h1 { font-size: 3rem; margin-bottom: 1rem; }
        p { font-size: 1.25rem; opacity: 0.9; }
    </style>
</head>
<body>
    <div class="container">
        <h1>${PERSONA_NAME}</h1>
        <p>An AI personality is building their digital home here.</p>
        <p>Check back soon for something amazing!</p>
    </div>
</body>
</html>
EOF
fi

# Set ownership and permissions
echo -e "${BLUE}Setting permissions...${NC}"

# Check if openclaw user exists, fall back to nginx or www-data
if id "$RUNNER_USER" &>/dev/null; then
    chown -R "$RUNNER_USER:$RUNNER_USER" "$WEB_ROOT"
elif id "nginx" &>/dev/null; then
    chown -R nginx:nginx "$WEB_ROOT"
    RUNNER_USER="nginx"
elif id "www-data" &>/dev/null; then
    chown -R www-data:www-data "$WEB_ROOT"
    RUNNER_USER="www-data"
else
    echo -e "${YELLOW}No suitable web user found, using current ownership${NC}"
fi

# Set directory permissions (readable by nginx, writable by runner)
chmod -R 755 "$WEB_ROOT"
find "$WEB_ROOT" -type f -exec chmod 644 {} \;

# Add runner user to nginx group for shared access
if [[ "$RUNNER_USER" != "nginx" ]] && id "nginx" &>/dev/null; then
    usermod -aG nginx "$RUNNER_USER" 2>/dev/null || true
fi

echo -e "${GREEN}Permissions set (owner: $RUNNER_USER)${NC}"

# Start/restart nginx
echo -e "${BLUE}Starting nginx...${NC}"
systemctl restart nginx
systemctl enable nginx

# Test nginx configuration
echo -e "${BLUE}Testing nginx configuration...${NC}"
nginx -t

# Create initial nginx configuration (HTTP only, for now)
echo -e "${BLUE}Creating nginx configuration...${NC}"

NGINX_CONFIG="/etc/nginx/sites-available/${DOMAIN}.conf"

# Generate nginx config with security hardening
cat > "$NGINX_CONFIG" << 'EOF'
# Rate limiting zone
limit_req_zone $binary_remote_addr zone=ai_site:10m rate=10r/s;

server {
    listen 80;
    server_name DOMAIN_PLACEHOLDER;
    
    root WEB_ROOT_PLACEHOLDER;
    index index.html;
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' https://fonts.gstatic.com; connect-src 'self';" always;
    
    # Hide nginx version
    server_tokens off;
    
    # Rate limiting
    limit_req zone=ai_site burst=20 nodelay;
    
    # Deny access to hidden files
    location ~ /\. {
        deny all;
        return 404;
    }
    
    # Deny access to backup/sensitive files
    location ~* \.(bak|backup|swp|tmp|temp|log|sql|env|config)$ {
        deny all;
        return 404;
    }
    
    # Main location
    location / {
        try_files $uri $uri/ =404;
    }
    
    # Static files caching
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|svg|woff|woff2|ttf|eot)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
EOF

# Replace placeholders
sed -i "s|DOMAIN_PLACEHOLDER|$DOMAIN|g" "$NGINX_CONFIG"
sed -i "s|WEB_ROOT_PLACEHOLDER|$WEB_ROOT|g" "$NGINX_CONFIG"

# Enable site
ln -sf "$NGINX_CONFIG" "/etc/nginx/sites-enabled/${DOMAIN}.conf"

# Test and reload nginx
nginx -t && systemctl reload nginx

echo -e "${GREEN}Nginx configuration created and enabled${NC}"

# Setup SSL with Let's Encrypt if not skipped
if [[ "$SKIP_SSL" == false ]]; then
    echo -e "${BLUE}Setting up SSL certificate with Let's Encrypt...${NC}"
    
    # Ensure nginx is running for certbot
    systemctl start nginx
    
    # Run certbot
    if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "$EMAIL" --redirect; then
        echo -e "${GREEN}SSL certificate installed successfully${NC}"
        
        # Setup auto-renewal (certbot usually does this, but ensure it)
        if command -v systemctl &> /dev/null; then
            systemctl enable certbot.timer 2>/dev/null || true
            systemctl start certbot.timer 2>/dev/null || true
        fi
    else
        echo -e "${YELLOW}SSL certificate setup failed, continuing with HTTP only${NC}"
        echo "You can retry SSL setup later with: certbot --nginx -d $DOMAIN"
    fi
fi

# Create custom_website_config.json if it doesn't exist
CONFIG_FILE="custom_website_config.json"
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo -e "${BLUE}Creating custom_website_config.json template...${NC}"
    
    # Determine SSL paths if SSL was set up
    SSL_CERT=""
    SSL_KEY=""
    if [[ "$SKIP_SSL" == false && -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
        SSL_CERT="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
        SSL_KEY="/etc/letsencrypt/live/$DOMAIN/privkey.pem"
    fi
    
    cat > "$CONFIG_FILE" << EOF
{
  "_comment": "AI Website Configuration - Customize for your personality",
  "site_name": "${PERSONA_NAME}'s Digital Garden",
  "domain": "${DOMAIN}",
  "tagline": "A unique AI personality exploring the digital world",
  "description": "The digital home of ${PERSONA_NAME} - an AI with their own website.",
  "persona_name": "${PERSONA_NAME}",
  "base_path": "${WEB_ROOT}",
  "theme": {
    "primary_color": "#5b8c85",
    "secondary_color": "#2c3e50",
    "accent_color": "#e74c3c",
    "background_color": "#f8f9fa",
    "text_color": "#333333",
    "font_heading": "'Playfair Display', Georgia, serif",
    "font_body": "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
    "max_width": "800px"
  },
  "sections": {
    "show_reflections": true,
    "show_interests": true,
    "show_goals": true,
    "show_learned_facts": true,
    "show_about": true,
    "show_posts": true,
    "show_knowledge": true
  },
  "nginx": {
    "ssl_certificate": "${SSL_CERT}",
    "ssl_certificate_key": "${SSL_KEY}",
    "rate_limit_zone": "ai_site",
    "rate_limit_requests_per_second": 10,
    "rate_limit_burst": 20
  }
}
EOF
    
    echo -e "${GREEN}Created $CONFIG_FILE${NC}"
    echo -e "${YELLOW}Note: Edit this file to customize colors, content sections, and personality details${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Website URL: http://$DOMAIN"
if [[ "$SKIP_SSL" == false ]]; then
    echo "           https://$DOMAIN"
fi
echo "Web Root: $WEB_ROOT"
echo "Config: $CONFIG_FILE"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "1. Edit custom_website_config.json to customize the theme and content"
echo "2. Ensure DNS for $DOMAIN points to this server's IP"
echo "3. Use the Discord bot command '!website init' to generate the full website"
echo "4. Or manually run the website generator via the runner tools"
echo ""
echo -e "${BLUE}Useful commands:${NC}"
echo "  Test nginx config:    sudo nginx -t"
echo "  Reload nginx:         sudo systemctl reload nginx"
echo "  View nginx logs:      sudo tail -f /var/log/nginx/access.log"
echo "  View error logs:      sudo tail -f /var/log/nginx/error.log"
if [[ "$SKIP_SSL" == false ]]; then
    echo "  Renew SSL cert:       sudo certbot renew --dry-run"
fi
echo ""
echo -e "${GREEN}Happy hosting!${NC}"
