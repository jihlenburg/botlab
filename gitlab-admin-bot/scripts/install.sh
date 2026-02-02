#!/bin/bash
# =============================================================================
# GitLab Admin Bot Installation Script
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root"
    exit 1
fi

echo "=============================================="
echo "    GitLab Admin Bot Installation"
echo "=============================================="
echo ""

# =============================================================================
# Prerequisites
# =============================================================================

log_info "Installing prerequisites..."

apt-get update
apt-get install -y \
    python3.12 \
    python3.12-venv \
    python3-pip \
    git \
    curl \
    jq

# =============================================================================
# Create directories
# =============================================================================

log_info "Creating directories..."

mkdir -p /opt/gitlab-admin-bot/{data,logs,config}
mkdir -p /var/log/gitlab-admin-bot

# =============================================================================
# Install application
# =============================================================================

log_info "Installing Admin Bot..."

cd /opt/gitlab-admin-bot

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install from source (assumes code is already copied)
if [[ -f pyproject.toml ]]; then
    pip install -e .
else
    log_error "pyproject.toml not found. Copy the admin bot code first."
    exit 1
fi

# =============================================================================
# Create systemd service
# =============================================================================

log_info "Creating systemd service..."

cat > /etc/systemd/system/gitlab-admin-bot.service << 'EOF'
[Unit]
Description=GitLab Admin Bot
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/gitlab-admin-bot
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/opt/gitlab-admin-bot/.env
ExecStart=/opt/gitlab-admin-bot/.venv/bin/python -m src.main
Restart=always
RestartSec=10

# Security
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/opt/gitlab-admin-bot/data /opt/gitlab-admin-bot/logs /var/log/gitlab-admin-bot

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# =============================================================================
# Setup environment file template
# =============================================================================

log_info "Creating environment file template..."

if [[ ! -f /opt/gitlab-admin-bot/.env ]]; then
    cat > /opt/gitlab-admin-bot/.env << 'EOF'
# GitLab Admin Bot Environment Variables
# Fill in these values

# GitLab API token (with admin access)
ADMIN_BOT_GITLAB__PRIVATE_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx

# Hetzner Cloud API token
ADMIN_BOT_HETZNER__API_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Borg backup encryption passphrase
ADMIN_BOT_BACKUP__BORG_PASSPHRASE=your-secure-passphrase

# SMTP password for email alerts
ADMIN_BOT_ALERTING__EMAIL_SMTP_PASSWORD=your-smtp-password

# Claude API key for AI analysis
ADMIN_BOT_CLAUDE__API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx

# Optional settings
ADMIN_BOT_LOG_LEVEL=INFO
ADMIN_BOT_DEBUG=false
EOF
    chmod 600 /opt/gitlab-admin-bot/.env
    log_warn "Edit /opt/gitlab-admin-bot/.env with your credentials"
fi

# =============================================================================
# Final setup
# =============================================================================

log_info "Setting permissions..."

chown -R root:root /opt/gitlab-admin-bot
chmod 700 /opt/gitlab-admin-bot

echo ""
echo "=============================================="
echo "    Installation Complete!"
echo "=============================================="
echo ""
echo "Next steps:"
echo "1. Edit /opt/gitlab-admin-bot/.env with your credentials"
echo "2. Copy config/config.yaml to /opt/gitlab-admin-bot/config/"
echo "3. Set up SSH key for GitLab server access"
echo "4. Start the service: systemctl start gitlab-admin-bot"
echo "5. Enable on boot: systemctl enable gitlab-admin-bot"
echo "6. Check logs: journalctl -u gitlab-admin-bot -f"
echo ""
