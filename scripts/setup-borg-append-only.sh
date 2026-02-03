#!/bin/bash
# =============================================================================
# Append-Only BorgBackup Setup for Ransomware-Resistant Backups
# =============================================================================
# This script configures a Hetzner Storage Box sub-account with append-only
# access so that a compromised GitLab server cannot delete or modify existing
# backup archives.
#
# Implements: SECURITY-ASSESSMENT.md Section 3.3.1 / DESIGN.md Section 9
#
# How it works:
#   1. A RESTRICTED SSH key is generated for daily backup operations.
#      This key can only APPEND new archives — it cannot prune or delete.
#   2. An ADMIN SSH key (existing or new) retains full access for
#      pruning and maintenance.  Store this key OFFLINE (USB / vault).
#   3. /etc/gitlab-backup.conf is updated to use the restricted key.
#
# Prerequisites:
#   - BorgBackup already installed (apt install borgbackup)
#   - Hetzner Storage Box with SSH access enabled
#   - Existing Borg repo (run setup-borg-backup.sh first)
#
# Usage: sudo ./setup-borg-append-only.sh
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root"
    exit 1
fi

echo "=============================================="
echo "  Append-Only BorgBackup Configuration"
echo "=============================================="
echo ""
echo "This hardens your Borg repository so that the"
echo "backup SSH key can only CREATE new archives."
echo "Prune/delete requires a separate admin key."
echo ""

# =============================================================================
# Configuration
# =============================================================================

RESTRICTED_KEY_PATH="/root/.ssh/storagebox_appendonly_key"
ADMIN_KEY_PATH="/root/.ssh/storagebox_admin_key"
CONF_FILE="/etc/gitlab-backup.conf"

if [[ ! -f "$CONF_FILE" ]]; then
    log_error "$CONF_FILE not found. Run setup-borg-backup.sh first."
    exit 1
fi

# shellcheck disable=SC1090
source "$CONF_FILE"

if [[ -z "${BORG_REPO:-}" ]]; then
    log_error "BORG_REPO not set in $CONF_FILE"
    exit 1
fi

# =============================================================================
# Step 1: Generate restricted (append-only) SSH key
# =============================================================================

log_info "Step 1: Generating restricted SSH key for append-only access..."

if [[ -f "$RESTRICTED_KEY_PATH" ]]; then
    log_warn "Restricted key already exists at $RESTRICTED_KEY_PATH"
    read -rp "Overwrite? (yes/no): " OVERWRITE
    if [[ "$OVERWRITE" != "yes" ]]; then
        log_info "Keeping existing restricted key"
    else
        rm -f "$RESTRICTED_KEY_PATH" "${RESTRICTED_KEY_PATH}.pub"
    fi
fi

if [[ ! -f "$RESTRICTED_KEY_PATH" ]]; then
    ssh-keygen -t ed25519 -f "$RESTRICTED_KEY_PATH" -N "" \
        -C "borg-appendonly@$(hostname)"
    chmod 600 "$RESTRICTED_KEY_PATH"
    log_info "Restricted key generated: $RESTRICTED_KEY_PATH"
fi

# =============================================================================
# Step 2: Preserve or generate admin key
# =============================================================================

log_info "Step 2: Setting up admin key (for prune/delete operations)..."

EXISTING_KEY="/root/.ssh/storagebox_key"

if [[ -f "$ADMIN_KEY_PATH" ]]; then
    log_info "Admin key already exists at $ADMIN_KEY_PATH"
elif [[ -f "$EXISTING_KEY" ]]; then
    log_info "Copying existing Storage Box key as admin key"
    cp "$EXISTING_KEY" "$ADMIN_KEY_PATH"
    cp "${EXISTING_KEY}.pub" "${ADMIN_KEY_PATH}.pub" 2>/dev/null || true
    chmod 600 "$ADMIN_KEY_PATH"
else
    log_info "Generating new admin key..."
    ssh-keygen -t ed25519 -f "$ADMIN_KEY_PATH" -N "" \
        -C "borg-admin@$(hostname)"
    chmod 600 "$ADMIN_KEY_PATH"
fi

# =============================================================================
# Step 3: Display keys for Storage Box configuration
# =============================================================================

echo ""
echo "=============================================="
echo "  Storage Box SSH Key Configuration"
echo "=============================================="
echo ""
echo "You need to add BOTH keys to the Storage Box"
echo "with different permissions:"
echo ""
echo "--- RESTRICTED KEY (append-only) ---"
echo "Add this key with APPEND-ONLY access:"
echo ""
cat "${RESTRICTED_KEY_PATH}.pub"
echo ""
echo "On Hetzner Robot: Storage Box -> Sub-accounts"
echo "  - Create sub-account with 'read-only' + 'create' (no delete)"
echo "  - Or use authorized_keys with forced command:"
echo "    command=\"borg serve --append-only --restrict-to-repository ./gitlab-borg\" $(cat "${RESTRICTED_KEY_PATH}.pub")"
echo ""
echo "--- ADMIN KEY (full access) ---"
echo "This key has full access (prune, delete, check)."
echo "STORE IT OFFLINE after setup — do not leave it on this server!"
echo ""
cat "${ADMIN_KEY_PATH}.pub"
echo ""

read -rp "Press Enter once both keys are configured on the Storage Box..."

# =============================================================================
# Step 4: Test restricted key
# =============================================================================

log_info "Step 4: Testing restricted key access..."

export BORG_RSH="ssh -i $RESTRICTED_KEY_PATH -o StrictHostKeyChecking=accept-new -p 23"

if borg list --last 1 "$BORG_REPO" &>/dev/null; then
    log_info "Restricted key can list archives (OK)"
else
    log_warn "Restricted key could not list archives — verify Storage Box config"
fi

# =============================================================================
# Step 5: Update backup configuration
# =============================================================================

log_info "Step 5: Updating $CONF_FILE to use restricted key..."

# Back up current config
cp "$CONF_FILE" "${CONF_FILE}.bak.$(date +%Y%m%d%H%M%S)"

# Replace the SSH key reference
if grep -q "storagebox_key" "$CONF_FILE"; then
    sed -i "s|storagebox_key|storagebox_appendonly_key|g" "$CONF_FILE"
    log_info "Updated BORG_RSH to use restricted key"
else
    log_warn "Could not find storagebox_key reference in $CONF_FILE"
    log_warn "Please manually update BORG_RSH to use: $RESTRICTED_KEY_PATH"
fi

# =============================================================================
# Step 6: Create admin helper script
# =============================================================================

ADMIN_SCRIPT="/usr/local/bin/borg-admin.sh"

cat > "$ADMIN_SCRIPT" << 'ADMINEOF'
#!/bin/bash
# Borg admin operations (prune, delete, check) using the full-access admin key.
# This key should normally be stored OFFLINE. Copy it to the server only when
# maintenance is needed, then remove it again.

set -euo pipefail

ADMIN_KEY="/root/.ssh/storagebox_admin_key"
CONF="/etc/gitlab-backup.conf"

if [[ ! -f "$ADMIN_KEY" ]]; then
    echo "ERROR: Admin key not found at $ADMIN_KEY"
    echo "Copy the admin key from your offline vault to run this script."
    exit 1
fi

# shellcheck disable=SC1090
source "$CONF"
export BORG_RSH="ssh -i $ADMIN_KEY -o StrictHostKeyChecking=accept-new -p 23"

echo "Borg admin shell — running with full-access key"
echo "Available commands:"
echo "  borg prune --keep-hourly=24 --keep-daily=7 --keep-weekly=4 --keep-monthly=12 \$BORG_REPO"
echo "  borg check \$BORG_REPO"
echo "  borg list \$BORG_REPO"
echo ""

# Pass through any arguments as a borg command
if [[ $# -gt 0 ]]; then
    borg "$@"
else
    echo "Usage: $0 <borg-subcommand> [args...]"
    echo "Example: $0 prune --keep-monthly=12 \$BORG_REPO"
fi
ADMINEOF

chmod 755 "$ADMIN_SCRIPT"
log_info "Admin helper script created: $ADMIN_SCRIPT"

# =============================================================================
# Step 7: Remind about offline key storage
# =============================================================================

echo ""
echo "=============================================="
echo "  Setup Complete!"
echo "=============================================="
echo ""
echo "IMPORTANT — Offline Key Storage:"
echo ""
echo "  1. Copy $ADMIN_KEY_PATH to an OFFLINE location:"
echo "     - Encrypted USB drive"
echo "     - Password manager"
echo "     - Printed QR code in a safe"
echo ""
echo "  2. Then REMOVE the admin key from this server:"
echo "     rm $ADMIN_KEY_PATH ${ADMIN_KEY_PATH}.pub"
echo ""
echo "  3. For routine backups, only the restricted key is needed."
echo "     The backup cron job will continue to work."
echo ""
echo "  4. For prune/maintenance, temporarily copy the admin key back"
echo "     and use: $ADMIN_SCRIPT prune ..."
echo ""
echo "Files created:"
echo "  Restricted key: $RESTRICTED_KEY_PATH"
echo "  Admin key:      $ADMIN_KEY_PATH (move offline!)"
echo "  Admin script:   $ADMIN_SCRIPT"
echo "  Config backup:  ${CONF_FILE}.bak.*"
echo ""
