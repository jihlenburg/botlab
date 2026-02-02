#!/bin/bash
# =============================================================================
# BorgBackup Setup Script for GitLab
# =============================================================================
# This script sets up BorgBackup for GitLab backups to Hetzner Storage Box
# Usage: ./setup-borg-backup.sh

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
echo "    BorgBackup Setup for GitLab"
echo "=============================================="
echo ""

# =============================================================================
# Configuration
# =============================================================================

read -p "Enter Storage Box hostname (e.g., uXXXXX.your-storagebox.de): " STORAGE_BOX_HOST
read -p "Enter Storage Box username (e.g., uXXXXX): " STORAGE_BOX_USER
read -sp "Enter Borg encryption passphrase (min 20 chars): " BORG_PASSPHRASE
echo ""

if [[ ${#BORG_PASSPHRASE} -lt 20 ]]; then
    log_error "Passphrase must be at least 20 characters"
    exit 1
fi

BORG_REPO="ssh://${STORAGE_BOX_USER}@${STORAGE_BOX_HOST}:23/./gitlab-borg"
SSH_KEY_PATH="/root/.ssh/storagebox_key"

# =============================================================================
# Step 1: Generate SSH key for Storage Box
# =============================================================================

log_info "Step 1: Setting up SSH key for Storage Box..."

if [[ -f "$SSH_KEY_PATH" ]]; then
    log_warn "SSH key already exists at $SSH_KEY_PATH"
    read -p "Overwrite? (yes/no): " OVERWRITE
    if [[ "$OVERWRITE" == "yes" ]]; then
        rm -f "$SSH_KEY_PATH" "${SSH_KEY_PATH}.pub"
    else
        log_info "Using existing key"
    fi
fi

if [[ ! -f "$SSH_KEY_PATH" ]]; then
    ssh-keygen -t ed25519 -f "$SSH_KEY_PATH" -N "" -C "gitlab-backup@$(hostname)"
    log_info "SSH key generated: $SSH_KEY_PATH"
fi

echo ""
echo "=============================================="
echo "IMPORTANT: Add this public key to Storage Box"
echo "=============================================="
echo ""
cat "${SSH_KEY_PATH}.pub"
echo ""
echo "Add this key to Storage Box via:"
echo "  1. Hetzner Robot Panel -> Storage Box -> SSH keys"
echo "  2. Or append to ~/.ssh/authorized_keys on Storage Box"
echo ""
read -p "Press Enter once the key is added to the Storage Box..."

# =============================================================================
# Step 2: Test SSH connection
# =============================================================================

log_info "Step 2: Testing SSH connection to Storage Box..."

SSH_CMD="ssh -i $SSH_KEY_PATH -p 23 -o StrictHostKeyChecking=accept-new ${STORAGE_BOX_USER}@${STORAGE_BOX_HOST}"

if $SSH_CMD "echo 'Connection successful'" 2>/dev/null; then
    log_info "SSH connection successful!"
else
    log_error "SSH connection failed. Check your Storage Box configuration."
    exit 1
fi

# =============================================================================
# Step 3: Initialize Borg repository
# =============================================================================

log_info "Step 3: Initializing Borg repository..."

export BORG_PASSPHRASE
export BORG_RSH="ssh -i $SSH_KEY_PATH -o StrictHostKeyChecking=accept-new"

# Check if repo already exists
if borg info "$BORG_REPO" &>/dev/null; then
    log_warn "Borg repository already exists at $BORG_REPO"
    read -p "Continue with existing repo? (yes/no): " CONTINUE
    if [[ "$CONTINUE" != "yes" ]]; then
        exit 1
    fi
else
    log_info "Creating new Borg repository (this may take a moment)..."
    borg init --encryption=repokey-blake2 "$BORG_REPO"
    log_info "Borg repository initialized with repokey-blake2 encryption"
fi

# =============================================================================
# Step 4: Create configuration file
# =============================================================================

log_info "Step 4: Creating configuration file..."

cat > /etc/gitlab-backup.conf << EOF
# BorgBackup configuration for GitLab
# Generated: $(date)
# DO NOT SHARE THIS FILE - Contains sensitive credentials

export BORG_REPO="$BORG_REPO"
export BORG_PASSPHRASE="$BORG_PASSPHRASE"
export BORG_RSH="ssh -i $SSH_KEY_PATH -o StrictHostKeyChecking=accept-new"

# Backup settings
export BACKUP_KEEP_HOURLY=24
export BACKUP_KEEP_DAILY=7
export BACKUP_KEEP_WEEKLY=4
export BACKUP_KEEP_MONTHLY=6
EOF

chmod 600 /etc/gitlab-backup.conf
log_info "Configuration saved to /etc/gitlab-backup.conf"

# =============================================================================
# Step 5: Test backup
# =============================================================================

log_info "Step 5: Running test backup..."

# Create a small test archive
TEST_ARCHIVE="${BORG_REPO}::test-$(date +%Y%m%d-%H%M%S)"

echo "Test backup content" > /tmp/borg-test-file.txt
borg create --stats "$TEST_ARCHIVE" /tmp/borg-test-file.txt

log_info "Test archive created successfully!"

# List archives
log_info "Current archives in repository:"
borg list "$BORG_REPO"

# Clean up test
borg delete "$TEST_ARCHIVE"
rm /tmp/borg-test-file.txt

# =============================================================================
# Step 6: Create backup script (if not exists from cloud-init)
# =============================================================================

log_info "Step 6: Setting up backup script..."

BACKUP_SCRIPT="/usr/local/bin/gitlab-backup-to-borg.sh"

if [[ ! -f "$BACKUP_SCRIPT" ]]; then
    log_info "Creating backup script..."
    cat > "$BACKUP_SCRIPT" << 'SCRIPT_EOF'
#!/bin/bash
# GitLab backup script with BorgBackup
# Run hourly via cron

set -euo pipefail

LOG_FILE="/var/log/gitlab-backup.log"
BACKUP_DIR="/var/opt/gitlab/backups"

# Source Borg configuration
if [[ -f /etc/gitlab-backup.conf ]]; then
    source /etc/gitlab-backup.conf
else
    echo "$(date): ERROR - /etc/gitlab-backup.conf not found" >> "$LOG_FILE"
    exit 1
fi

echo "$(date): Starting GitLab backup" >> "$LOG_FILE"

# Create GitLab backup (skip artifacts/LFS as they're in object storage)
gitlab-backup create STRATEGY=copy SKIP=artifacts,lfs >> "$LOG_FILE" 2>&1

# Find the latest backup file
LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/*_gitlab_backup.tar 2>/dev/null | head -1)

if [[ -z "$LATEST_BACKUP" ]]; then
    echo "$(date): ERROR - No backup file found" >> "$LOG_FILE"
    exit 1
fi

echo "$(date): Sending backup to Borg repository" >> "$LOG_FILE"

# Send to BorgBackup
borg create --stats --compression zstd \
    "${BORG_REPO}::{hostname}-{now:%Y-%m-%d_%H:%M}" \
    "$LATEST_BACKUP" \
    /etc/gitlab/gitlab.rb \
    /etc/gitlab/gitlab-secrets.json \
    >> "$LOG_FILE" 2>&1

# Prune old backups (keep hourly for 24h, daily for 7d, weekly for 4w, monthly for 6m)
borg prune --keep-hourly=24 --keep-daily=7 --keep-weekly=4 --keep-monthly=6 \
    "$BORG_REPO" >> "$LOG_FILE" 2>&1

# Clean local backups older than 24 hours
find "$BACKUP_DIR" -name "*_gitlab_backup.tar" -mtime +1 -delete

echo "$(date): Backup completed successfully" >> "$LOG_FILE"
SCRIPT_EOF
    chmod 755 "$BACKUP_SCRIPT"
    log_info "Backup script created: $BACKUP_SCRIPT"
else
    log_info "Backup script already exists (from cloud-init)"
fi

# =============================================================================
# Step 7: Enable cron job
# =============================================================================

log_info "Step 7: Enabling backup cron job..."

cat > /etc/cron.d/gitlab-backup << 'EOF'
# GitLab backup - runs hourly at minute 0
0 * * * * root /usr/local/bin/gitlab-backup-to-borg.sh >> /var/log/gitlab-backup.log 2>&1
EOF

chmod 644 /etc/cron.d/gitlab-backup

log_info "Cron job enabled (hourly backups)"

# =============================================================================
# Step 8: Run initial backup test
# =============================================================================

log_info "Step 8: Running initial backup verification..."

# Verify the backup script works
if "$BACKUP_SCRIPT" --help 2>&1 | grep -q "gitlab-backup" || bash -n "$BACKUP_SCRIPT"; then
    log_info "Backup script syntax OK"
else
    log_warn "Backup script may have issues - check manually"
fi

# =============================================================================
# Complete
# =============================================================================

echo ""
echo "=============================================="
echo "    BorgBackup Setup Complete!"
echo "=============================================="
echo ""
echo "Configuration:"
echo "  Repository: $BORG_REPO"
echo "  SSH Key: $SSH_KEY_PATH"
echo "  Config: /etc/gitlab-backup.conf"
echo "  Cron: /etc/cron.d/gitlab-backup"
echo "  Script: /usr/local/bin/gitlab-backup-to-borg.sh"
echo "  Log: /var/log/gitlab-backup.log"
echo ""
echo "IMPORTANT: Save the encryption passphrase securely!"
echo "Without it, backups CANNOT be restored."
echo ""
echo "To run a manual backup:"
echo "  /usr/local/bin/gitlab-backup-to-borg.sh"
echo ""
echo "To list backups:"
echo "  source /etc/gitlab-backup.conf && borg list \$BORG_REPO"
echo ""
echo "To verify backups:"
echo "  /path/to/scripts/verify-backup.sh"
echo ""
