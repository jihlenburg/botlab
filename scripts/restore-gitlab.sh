#!/bin/bash
# =============================================================================
# GitLab Disaster Recovery Restore Script
# =============================================================================
# This script automates the GitLab restore process from BorgBackup
# Usage: ./restore-gitlab.sh [backup-archive-name]

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root"
    exit 1
fi

# Load Borg configuration
if [[ -f /etc/gitlab-backup.conf ]]; then
    source /etc/gitlab-backup.conf
else
    log_error "Borg configuration not found at /etc/gitlab-backup.conf"
    exit 1
fi

# =============================================================================
# Configuration
# =============================================================================

RESTORE_DIR="/tmp/gitlab-restore-$$"
BACKUP_DIR="/var/opt/gitlab/backups"

# =============================================================================
# Functions
# =============================================================================

list_backups() {
    log_info "Available backups in Borg repository:"
    borg list "$BORG_REPO"
}

cleanup() {
    log_info "Cleaning up temporary files..."
    rm -rf "$RESTORE_DIR"
}

trap cleanup EXIT

# =============================================================================
# Main
# =============================================================================

echo "=============================================="
echo "    GitLab Disaster Recovery Restore"
echo "=============================================="
echo ""

# Get backup name from argument or list available
BACKUP_NAME="${1:-}"

if [[ -z "$BACKUP_NAME" ]]; then
    list_backups
    echo ""
    read -p "Enter backup archive name to restore (or 'latest' for most recent): " BACKUP_NAME
fi

if [[ "$BACKUP_NAME" == "latest" ]]; then
    BACKUP_NAME=$(borg list --last 1 --format '{archive}' "$BORG_REPO")
    log_info "Using most recent backup: $BACKUP_NAME"
fi

# Confirm restore
echo ""
log_warn "This will restore GitLab from backup: $BACKUP_NAME"
log_warn "This is a DESTRUCTIVE operation and will overwrite current data!"
echo ""
read -p "Are you sure you want to continue? (yes/no): " CONFIRM

if [[ "$CONFIRM" != "yes" ]]; then
    log_info "Restore cancelled"
    exit 0
fi

# =============================================================================
# Step 1: Extract backup from Borg
# =============================================================================

log_step "Step 1/6: Extracting backup from Borg repository..."

mkdir -p "$RESTORE_DIR"
cd "$RESTORE_DIR"

borg extract --progress "$BORG_REPO::$BACKUP_NAME"

# Find the extracted files
CONFIG_DIR="$RESTORE_DIR/etc/gitlab"
BACKUP_FILE=$(find "$RESTORE_DIR" -name "*_gitlab_backup.tar" -type f | head -1)

if [[ -z "$BACKUP_FILE" ]]; then
    log_error "No GitLab backup file found in archive"
    exit 1
fi

log_info "Found backup file: $BACKUP_FILE"
log_info "Found config directory: $CONFIG_DIR"

# =============================================================================
# Step 2: Restore configuration files
# =============================================================================

log_step "Step 2/6: Restoring configuration files..."

# Backup current config (just in case)
if [[ -f /etc/gitlab/gitlab.rb ]]; then
    cp /etc/gitlab/gitlab.rb /etc/gitlab/gitlab.rb.pre-restore
fi
if [[ -f /etc/gitlab/gitlab-secrets.json ]]; then
    cp /etc/gitlab/gitlab-secrets.json /etc/gitlab/gitlab-secrets.json.pre-restore
fi

# Restore configuration
cp "$CONFIG_DIR/gitlab.rb" /etc/gitlab/gitlab.rb
cp "$CONFIG_DIR/gitlab-secrets.json" /etc/gitlab/gitlab-secrets.json

chmod 600 /etc/gitlab/gitlab.rb
chmod 600 /etc/gitlab/gitlab-secrets.json

log_info "Configuration files restored"

# =============================================================================
# Step 3: Copy backup file to GitLab backups directory
# =============================================================================

log_step "Step 3/6: Copying backup file to GitLab..."

mkdir -p "$BACKUP_DIR"
cp "$BACKUP_FILE" "$BACKUP_DIR/"
BACKUP_FILENAME=$(basename "$BACKUP_FILE")

# Extract timestamp from backup filename (format: TIMESTAMP_YYYY_MM_DD_VERSION_gitlab_backup.tar)
BACKUP_TIMESTAMP=$(echo "$BACKUP_FILENAME" | sed 's/_gitlab_backup.tar$//')

log_info "Backup timestamp: $BACKUP_TIMESTAMP"

# =============================================================================
# Step 4: Stop GitLab services
# =============================================================================

log_step "Step 4/6: Stopping GitLab services..."

gitlab-ctl stop puma
gitlab-ctl stop sidekiq

# Verify services are stopped
gitlab-ctl status

# =============================================================================
# Step 5: Restore GitLab backup
# =============================================================================

log_step "Step 5/6: Restoring GitLab backup (this may take a while)..."

# Run the restore
gitlab-backup restore BACKUP="$BACKUP_TIMESTAMP" force=yes

# =============================================================================
# Step 6: Reconfigure and restart
# =============================================================================

log_step "Step 6/6: Reconfiguring and restarting GitLab..."

gitlab-ctl reconfigure
gitlab-ctl restart

# Wait for GitLab to be ready
log_info "Waiting for GitLab to be ready..."
sleep 30

# =============================================================================
# Verification
# =============================================================================

log_info "Running verification checks..."

# Check GitLab status
gitlab-ctl status

# Run GitLab check
gitlab-rake gitlab:check SANITIZE=true || log_warn "Some checks failed - review output above"

# Test health endpoint
if curl -sf http://localhost/-/health > /dev/null; then
    log_info "Health check: PASSED"
else
    log_warn "Health check: FAILED - GitLab may still be starting"
fi

# =============================================================================
# Complete
# =============================================================================

echo ""
echo "=============================================="
echo "    Restore Complete!"
echo "=============================================="
echo ""
log_info "GitLab has been restored from backup: $BACKUP_NAME"
echo ""
echo "Next steps:"
echo "1. Verify GitLab is accessible via web UI"
echo "2. Test user login (SSO)"
echo "3. Test git clone/push operations"
echo "4. Update DNS if necessary"
echo "5. Verify object storage (LFS, artifacts) is accessible"
echo ""
