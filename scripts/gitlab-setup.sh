#!/bin/bash
# =============================================================================
# GitLab CE Setup Script
# =============================================================================
# Run this script after the server is provisioned to complete GitLab setup
# Usage: ./gitlab-setup.sh

set -euo pipefail

echo "=== GitLab CE Setup Script ==="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root"
    exit 1
fi

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

GITLAB_DOMAIN="${GITLAB_DOMAIN:-gitlab.example.com}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"

# Check if GitLab is already installed
if command -v gitlab-ctl &> /dev/null; then
    log_info "GitLab is already installed"
    gitlab-ctl status
else
    log_info "Installing GitLab CE..."

    # Install dependencies
    apt-get update
    apt-get install -y curl openssh-server ca-certificates tzdata perl postfix

    # Add GitLab repository
    curl https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh | bash

    # Install GitLab CE
    EXTERNAL_URL="https://${GITLAB_DOMAIN}" apt-get install -y gitlab-ce
fi

# -----------------------------------------------------------------------------
# Volume Configuration
# -----------------------------------------------------------------------------

log_info "Checking volume mounts..."

# Check data volume
if ! mountpoint -q /var/opt/gitlab; then
    log_warn "/var/opt/gitlab is not mounted. Check volume attachment."
fi

# Check backup volume
if ! mountpoint -q /var/opt/gitlab/backups; then
    log_warn "/var/opt/gitlab/backups is not mounted. Check volume attachment."
fi

# -----------------------------------------------------------------------------
# Security Hardening
# -----------------------------------------------------------------------------

log_info "Applying security hardening..."

# Set secure permissions
chmod 600 /etc/gitlab/gitlab.rb 2>/dev/null || true
chmod 600 /etc/gitlab/gitlab-secrets.json 2>/dev/null || true

# Ensure fail2ban is running
systemctl enable fail2ban
systemctl start fail2ban

# -----------------------------------------------------------------------------
# Configure Prometheus Exporters
# -----------------------------------------------------------------------------

log_info "Enabling Prometheus exporters..."

# Enable GitLab Prometheus (already included in Omnibus)
# Modify gitlab.rb if needed via the configuration template

# -----------------------------------------------------------------------------
# Final Reconfigure
# -----------------------------------------------------------------------------

log_info "Running GitLab reconfigure..."
gitlab-ctl reconfigure

# -----------------------------------------------------------------------------
# Status Check
# -----------------------------------------------------------------------------

log_info "GitLab installation complete!"
echo ""
echo "=== Status ==="
gitlab-ctl status

echo ""
echo "=== Next Steps ==="
echo "1. Configure DNS: Point ${GITLAB_DOMAIN} to the load balancer IP"
echo "2. Configure /etc/gitlab/gitlab.rb with your settings"
echo "3. Set up Azure AD SSO (see docs/DESIGN.md)"
echo "4. Configure backup to Storage Box (see /etc/gitlab-backup.conf.template)"
echo "5. Run 'gitlab-ctl reconfigure' after any changes"
echo ""
echo "Initial root password is stored in: /etc/gitlab/initial_root_password"
echo "(This file will be deleted after 24 hours)"
