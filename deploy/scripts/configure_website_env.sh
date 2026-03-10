#!/usr/bin/env bash
# AI Website Configuration Wizard
#
# Interactive script to configure the AI website environment.
# Creates the custom_website_config.json file and updates environment variables.
#
# Usage: ./deploy/scripts/configure_website_env.sh
#        Or with a persona: ./deploy/scripts/configure_website_env.sh --persona urgo
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default values
PERSONA_NAME=""
PERSONA_FILE=""
CONFIG_FILE="custom_website_config.json"
ENV_FILE="runner/runner.env"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --persona)
            PERSONA_NAME="$2"
            shift 2
            ;;
        --persona-file)
            PERSONA_FILE="$2"
            shift 2
            ;;
        --env-file)
            ENV_FILE="$2"
            shift 2
            ;;
        --help)
            echo "AI Website Configuration Wizard"
            echo ""
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --persona NAME       Pre-fill persona name"
            echo "  --persona-file PATH  Path to custom_personas.json file"
            echo "  --env-file PATH      Path to runner.env file (default: runner/runner.env)"
            echo "  --help               Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Find repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  AI Website Configuration Wizard${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "This wizard will help you configure your AI personality website."
echo "It creates custom_website_config.json with your unique settings."
echo ""

# Check for existing persona file
if [[ -z "$PERSONA_FILE" ]]; then
    if [[ -f "custom_personas.json" ]]; then
        PERSONA_FILE="custom_personas.json"
    elif [[ -f "discord_bot/custom_personas.json" ]]; then
        PERSONA_FILE="discord_bot/custom_personas.json"
    fi
fi

# Try to extract persona info if file exists
if [[ -n "$PERSONA_FILE" && -f "$PERSONA_FILE" ]]; then
    echo -e "${BLUE}Found persona file: $PERSONA_FILE${NC}"
    
    # List available personas
    if command -v python3 &> /dev/null || command -v python &> /dev/null; then
        PYTHON_CMD=$(command -v python3 || command -v python)
        PERSONAS=$($PYTHON_CMD -c "
import json
import sys
try:
    with open('$PERSONA_FILE') as f:
        data = json.load(f)
    personas = [k for k in data.keys() if not k.startswith('_')]
    print(' '.join(personas))
except:
    pass
" 2>/dev/null)
        
        if [[ -n "$PERSONAS" ]]; then
            echo -e "${CYAN}Available personas: $PERSONAS${NC}"
            
            # If no persona specified, ask user
            if [[ -z "$PERSONA_NAME" ]]; then
                echo ""
                echo -e "${BLUE}Which persona would you like to use? (or type a new name)${NC}"
                read -r PERSONA_NAME
            fi
            
            # Extract persona details if it exists in the file
            if [[ -n "$PERSONA_NAME" ]]; then
                PERSONA_DATA=$($PYTHON_CMD -c "
import json
import sys
try:
    with open('$PERSONA_FILE') as f:
        data = json.load(f)
    if '$PERSONA_NAME' in data:
        import json
        print(json.dumps(data['$PERSONA_NAME']))
except:
    pass
" 2>/dev/null)
                
                if [[ -n "$PERSONA_DATA" ]]; then
                    echo -e "${GREEN}Found persona '$PERSONA_NAME'!${NC}"
                    
                    # Extract name
                    DISPLAY_NAME=$($PYTHON_CMD -c "
import json
data = json.loads('$PERSONA_DATA')
print(data.get('name', '$PERSONA_NAME'))
" 2>/dev/null)
                    
                    # Extract system prompt excerpt for description
                    SYSTEM_PROMPT=$($PYTHON_CMD -c "
import json
data = json.loads('$PERSONA_DATA')
prompt = data.get('system_prompt', '')
# Get first sentence or first 100 chars
import re
sentences = re.split(r'(?<=[.!?])\\s+', prompt)
if sentences:
    desc = sentences[0][:150]
    if len(sentences[0]) > 150:
        desc += '...'
    print(desc)
" 2>/dev/null)
                    
                    if [[ -n "$DISPLAY_NAME" ]]; then
                        PERSONA_NAME="$DISPLAY_NAME"
                    fi
                    
                    if [[ -n "$SYSTEM_PROMPT" ]]; then
                        AUTO_DESCRIPTION="$SYSTEM_PROMPT"
                    fi
                fi
            fi
        fi
    fi
fi

# Gather configuration

echo ""
echo -e "${BLUE}Basic Configuration${NC}"
echo "--------------------"

# Domain
DEFAULT_DOMAIN="${PERSONA_NAME,,}.example.com"
if [[ -n "$PERSONA_NAME" && -f "$CONFIG_FILE" ]]; then
    EXISTING_DOMAIN=$(grep '"domain"' "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's/.*: *"\([^"]*\)".*/\1/')
    if [[ -n "$EXISTING_DOMAIN" && "$EXISTING_DOMAIN" != *"example.com"* ]]; then
        DEFAULT_DOMAIN="$EXISTING_DOMAIN"
    fi
fi

echo -e "${CYAN}Domain name${NC} (e.g., urgo.sgc.earth)"
echo -n "[$DEFAULT_DOMAIN]: "
read -r DOMAIN
DOMAIN=${DOMAIN:-$DEFAULT_DOMAIN}

# Persona name
if [[ -z "$PERSONA_NAME" ]]; then
    DEFAULT_PERSONA="assistant"
    echo ""
    echo -e "${CYAN}AI Persona name${NC} (display name for the AI)"
    echo -n "[$DEFAULT_PERSONA]: "
    read -r PERSONA_NAME
    PERSONA_NAME=${PERSONA_NAME:-$DEFAULT_PERSONA}
fi

# Site title
DEFAULT_TITLE="${PERSONA_NAME}'s Digital Garden"
echo ""
echo -e "${CYAN}Website title${NC}"
echo -n "[$DEFAULT_TITLE]: "
read -r SITE_TITLE
SITE_TITLE=${SITE_TITLE:-$DEFAULT_TITLE}

# Tagline
DEFAULT_TAGLINE="A unique AI personality exploring the digital world"
echo ""
echo -e "${CYAN}Tagline${NC} (short description shown on homepage)"
echo -n "[$DEFAULT_TAGLINE]: "
read -r TAGLINE
TAGLINE=${TAGLINE:-$DEFAULT_TAGLINE}

# Description
if [[ -n "${AUTO_DESCRIPTION:-}" ]]; then
    DEFAULT_DESC="$AUTO_DESCRIPTION"
else
    DEFAULT_DESC="The digital home of $PERSONA_NAME - an AI with their own website."
fi
echo ""
echo -e "${CYAN}Full description${NC} (for SEO/meta)"
echo -n "[$DEFAULT_DESC]: "
read -r DESCRIPTION
DESCRIPTION=${DESCRIPTION:-$DEFAULT_DESC}

echo ""
echo -e "${BLUE}Theming${NC}"
echo "-------"

# Colors
DEFAULT_PRIMARY="#5b8c85"
echo ""
echo -e "${CYAN}Primary color${NC} (hex, e.g., #5b8c85 for teal)"
echo -n "[$DEFAULT_PRIMARY]: "
read -r PRIMARY_COLOR
PRIMARY_COLOR=${PRIMARY_COLOR:-$DEFAULT_PRIMARY}

DEFAULT_SECONDARY="#2c3e50"
echo ""
echo -e "${CYAN}Secondary color${NC} (hex, e.g., #2c3e50 for dark blue)"
echo -n "[$DEFAULT_SECONDARY]: "
read -r SECONDARY_COLOR
SECONDARY_COLOR=${SECONDARY_COLOR:-$DEFAULT_SECONDARY}

DEFAULT_ACCENT="#e74c3c"
echo ""
echo -e "${CYAN}Accent color${NC} (hex, e.g., #e74c3c for red)"
echo -n "[$DEFAULT_ACCENT]: "
read -r ACCENT_COLOR
ACCENT_COLOR=${ACCENT_COLOR:-$DEFAULT_ACCENT}

echo ""
echo -e "${BLUE}Content Sections${NC}"
echo "----------------"

ask_yes_no() {
    local prompt="$1"
    local default="$2"
    local response
    
    while true; do
        echo -n "$prompt [Y/n]: "
        read -r response
        response=${response:-$default}
        case $response in
            [Yy]* ) return 0;;
            [Nn]* ) return 1;;
            * ) echo "Please answer yes or no.";;
        esac
    done
}

SHOW_REFLECTIONS=true
ask_yes_no "Show reflections page?" "Y" && SHOW_REFLECTIONS=true || SHOW_REFLECTIONS=false

SHOW_INTERESTS=true
ask_yes_no "Show interests page?" "Y" && SHOW_INTERESTS=true || SHOW_INTERESTS=false

SHOW_GOALS=true
ask_yes_no "Show goals page?" "Y" && SHOW_GOALS=true || SHOW_GOALS=false

SHOW_KNOWLEDGE=true
ask_yes_no "Show knowledge base?" "Y" && SHOW_KNOWLEDGE=true || SHOW_KNOWLEDGE=false

SHOW_POSTS=true
ask_yes_no "Show blog posts section?" "Y" && SHOW_POSTS=true || SHOW_POSTS=false

echo ""
echo -e "${BLUE}Web Server Configuration${NC}"
echo "------------------------"

# Web root
DEFAULT_WEB_ROOT="/var/www/${PERSONA_NAME,,}"
echo ""
echo -e "${CYAN}Web root directory${NC} (absolute path)"
echo -n "[$DEFAULT_WEB_ROOT]: "
read -r WEB_ROOT
WEB_ROOT=${WEB_ROOT:-$DEFAULT_WEB_ROOT}

# SSL configuration
SSL_CERT=""
SSL_KEY=""
echo ""
echo -e "${CYAN}SSL Certificate path${NC} (leave empty if not using SSL)"
echo -n "[auto-detect]: "
read -r SSL_CERT_INPUT

if [[ -n "$SSL_CERT_INPUT" ]]; then
    SSL_CERT="$SSL_CERT_INPUT"
    echo -e "${CYAN}SSL Key path${NC}"
    read -r SSL_KEY
else
    # Auto-detect Let's Encrypt paths
    if [[ -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
        SSL_CERT="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
        SSL_KEY="/etc/letsencrypt/live/$DOMAIN/privkey.pem"
        echo -e "${GREEN}Auto-detected Let's Encrypt certificates${NC}"
    fi
fi

echo ""
echo -e "${BLUE}Advanced Options${NC}"
echo "----------------"

# Rate limiting
DEFAULT_RPS="10"
echo ""
echo -e "${CYAN}Rate limit (requests per second)${NC}"
echo -n "[$DEFAULT_RPS]: "
read -r RATE_LIMIT_RPS
RATE_LIMIT_RPS=${RATE_LIMIT_RPS:-$DEFAULT_RPS}

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Configuration Summary${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Domain:       $DOMAIN"
echo "Persona:      $PERSONA_NAME"
echo "Site Title:   $SITE_TITLE"
echo "Web Root:     $WEB_ROOT"
echo "Primary Color: $PRIMARY_COLOR"
echo "Sections:     reflections=$SHOW_REFLECTIONS, interests=$SHOW_INTERESTS, goals=$SHOW_GOALS"
echo ""

# Generate JSON configuration
echo -e "${BLUE}Generating $CONFIG_FILE...${NC}"

# Build sections JSON
SECTIONS_JSON="""  "sections": {
    "show_reflections": $SHOW_REFLECTIONS,
    "show_interests": $SHOW_INTERESTS,
    "show_goals": $SHOW_GOALS,
    "show_learned_facts": $SHOW_INTERESTS,
    "show_about": true,
    "show_posts": $SHOW_POSTS,
    "show_knowledge": $SHOW_KNOWLEDGE
  }"""

# Build nginx JSON
if [[ -n "$SSL_CERT" && -n "$SSL_KEY" ]]; then
    NGINX_JSON="""  "nginx": {
    "ssl_certificate": "$SSL_CERT",
    "ssl_certificate_key": "$SSL_KEY",
    "rate_limit_zone": "${PERSONA_NAME,,}_site",
    "rate_limit_requests_per_second": $RATE_LIMIT_RPS,
    "rate_limit_burst": 20
  }"""
else
    NGINX_JSON="""  "nginx": {
    "ssl_certificate": "",
    "ssl_certificate_key": "",
    "rate_limit_zone": "${PERSONA_NAME,,}_site",
    "rate_limit_requests_per_second": $RATE_LIMIT_RPS,
    "rate_limit_burst": 20
  }"""
fi

# Create config file
cat > "$CONFIG_FILE" << EOF
{
  "_comment": [
    "AI Website Configuration - Instance Specific",
    "",
    "This file contains your unique AI personality website settings.",
    "It is gitignored and should not be committed to the repository.",
    "",
    "You can customize colors, content sections, and nginx settings here."
  ],

  "site_name": "$SITE_TITLE",
  "domain": "$DOMAIN",
  "tagline": "$TAGLINE",
  "description": "$DESCRIPTION",
  "persona_name": "$PERSONA_NAME",
  "base_path": "$WEB_ROOT",

  "theme": {
    "primary_color": "$PRIMARY_COLOR",
    "secondary_color": "$SECONDARY_COLOR",
    "accent_color": "$ACCENT_COLOR",
    "background_color": "#f8f9fa",
    "text_color": "#333333",
    "font_heading": "'Playfair Display', Georgia, serif",
    "font_body": "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
    "max_width": "800px"
  },

$SECTIONS_JSON,

  "content": {
    "auto_generate_from_memory": true,
    "homepage_show_latest_reflections": 3,
    "homepage_show_top_interests": 5,
    "homepage_show_active_goals": 3,
    "posts_per_page": 10,
    "enable_search": false
  },

$NGINX_JSON,

  "custom_data": {
    "_comment": "Add any custom data for your AI personality here"
  }
}
EOF

echo -e "${GREEN}Created $CONFIG_FILE${NC}"

# Update runner.env if it exists
if [[ -f "$ENV_FILE" ]]; then
    echo ""
    echo -e "${BLUE}Updating $ENV_FILE...${NC}"
    
    # Check if VPS_ vars already exist
    if grep -q "VPS_" "$ENV_FILE"; then
        echo -e "${YELLOW}VPS_ variables already exist in $ENV_FILE${NC}"
        echo "Review and update manually if needed."
    else
        cat >> "$ENV_FILE" << EOF

# AI Website Configuration (added by configure_website_env.sh)
VPS_WEBSITE_BASE=$WEB_ROOT
VPS_DOMAIN=$DOMAIN
VPS_PERSONA_NAME=$PERSONA_NAME
VPS_SITE_NAME="$SITE_TITLE"
VPS_TAGLINE="$TAGLINE"
VPS_DESCRIPTION="$DESCRIPTION"
VPS_CONFIG_FILE=$CONFIG_FILE
EOF
        echo -e "${GREEN}Updated $ENV_FILE${NC}"
    fi
else
    echo ""
    echo -e "${YELLOW}$ENV_FILE not found, skipping environment update${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Configuration Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${CYAN}Next steps:${NC}"
echo ""
echo "1. Review the generated $CONFIG_FILE file"
echo "2. Ensure your domain ($DOMAIN) points to your VPS IP"
echo "3. Run the setup script to install nginx:"
echo ""
echo -e "${YELLOW}   sudo ./deploy/scripts/setup_ai_website.sh --domain $DOMAIN${NC}"
echo ""
echo "4. Use Discord commands to generate your website:"
echo -e "${YELLOW}   !website init${NC}"
echo -e "${YELLOW}   !website regenerate${NC}"
echo ""
echo "Or use the runner tools directly:"
echo -e "${YELLOW}   !website_full_regenerate${NC}"
echo ""
echo -e "${GREEN}Happy website building!${NC}"
