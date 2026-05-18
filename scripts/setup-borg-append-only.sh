#!/bin/bash
# =============================================================================
# Replace the sub-account's authorized_keys with a forced-command, append-only
# constraint. After this runs, the GitLab server's SSH key can create new
# archives but cannot delete or modify existing ones — even if the server is
# fully compromised at root.
# =============================================================================
#
# Run ONCE per fresh deploy, AFTER setup-borg-backup.sh has succeeded.
#
# Append-only IS NOT a Hetzner-side permission (the sub-account API only
# offers `readonly` or full r/w/d). The constraint is enforced at the SSH
# command layer via a forced `borg serve --append-only` prefix in the
# sub-account's authorized_keys.
#
# Required environment variable (same as setup-borg-backup.sh):
#   STORAGEBOX_SUBACCOUNT_PASSWORD — sub-account password for the SFTP
#   install. After this script succeeds, rotate the password in the
#   Hetzner Cloud Console (it has been in shell history).
#
# Usage:
#   sudo STORAGEBOX_SUBACCOUNT_PASSWORD='...' ./setup-borg-append-only.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ---- Sanity checks --------------------------------------------------------

if [[ $EUID -ne 0 ]]; then
    log_error "Must run as root."
    exit 1
fi

if [[ -z "${STORAGEBOX_SUBACCOUNT_PASSWORD:-}" ]]; then
    log_error "STORAGEBOX_SUBACCOUNT_PASSWORD env var not set."
    exit 1
fi

CONF_FILE="/etc/gitlab-backup.conf"
if [[ ! -f "$CONF_FILE" ]]; then
    log_error "$CONF_FILE not found. Run setup-borg-backup.sh first."
    exit 1
fi

# shellcheck disable=SC1090
source "$CONF_FILE"

for var in BORG_REPO BORG_PASSPHRASE; do
    if [[ -z "${!var:-}" ]]; then
        log_error "$var not set in $CONF_FILE."
        exit 1
    fi
done

STORAGE_BOX_USER="$(echo "$BORG_REPO" | sed -E 's|ssh://([^@]+)@.*|\1|')"
STORAGE_BOX_HOST="$(echo "$BORG_REPO" | sed -E 's|ssh://[^@]+@([^:/]+).*|\1|')"
REPO_PATH="$(echo "$BORG_REPO" | sed -E 's|.*:23/(.*)|\1|')"

SUBACCOUNT_KEY_PATH="/root/.ssh/storagebox_subaccount_key"

if [[ ! -f "$SUBACCOUNT_KEY_PATH" ]]; then
    log_error "Sub-account SSH key not found at $SUBACCOUNT_KEY_PATH."
    log_error "Run setup-borg-backup.sh first."
    exit 1
fi

if ! command -v sshpass >/dev/null 2>&1; then
    log_error "sshpass not installed. apt-get install -y sshpass"
    exit 1
fi

echo "=============================================="
echo "  Enabling append-only constraint"
echo "=============================================="
echo "  Sub-account:  $STORAGE_BOX_USER@$STORAGE_BOX_HOST"
echo "  Repo path:    $REPO_PATH"
echo ""

# ---- Step 1: Build the constrained authorized_keys line -------------------

log_info "Step 1/3: Building forced-command authorized_keys line..."

PUBKEY="$(cat "${SUBACCOUNT_KEY_PATH}.pub")"
FORCED_CMD="command=\"borg serve --append-only --restrict-to-repository $REPO_PATH\",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-user-rc"
AUTH_KEYS_LINE="${FORCED_CMD} ${PUBKEY}"

AUTH_KEYS_FILE="$(mktemp)"
trap 'rm -f "$AUTH_KEYS_FILE"' EXIT
echo "$AUTH_KEYS_LINE" > "$AUTH_KEYS_FILE"

# ---- Step 2: SFTP REPLACE the existing authorized_keys --------------------

log_info "Step 2/3: Uploading constrained authorized_keys (replaces unconstrained)..."

SFTP_BATCH="$(mktemp)"
trap 'rm -f "$AUTH_KEYS_FILE" "$SFTP_BATCH"' EXIT
cat > "$SFTP_BATCH" <<EOF
put $AUTH_KEYS_FILE .ssh/authorized_keys
chmod 600 .ssh/authorized_keys
EOF

if ! SSHPASS="$STORAGEBOX_SUBACCOUNT_PASSWORD" sshpass -e sftp \
        -o StrictHostKeyChecking=accept-new \
        -P 23 -b "$SFTP_BATCH" "$STORAGE_BOX_USER@$STORAGE_BOX_HOST"; then
    log_error "SFTP install of constrained authorized_keys failed."
    log_error "The repo is still UNCONSTRAINED. Investigate and re-run."
    exit 1
fi

# ---- Step 3: Test that append works AND delete is blocked -----------------

log_info "Step 3/3: Verifying constraint (create should pass, delete should fail)..."

TEST_FILE="$(mktemp)"
echo "append-test $(date -u +%FT%TZ)" > "$TEST_FILE"
TEST_ARCHIVE_NAME="append-test-$(date -u +%Y%m%d-%H%M%S)"
TEST_ARCHIVE="${BORG_REPO}::${TEST_ARCHIVE_NAME}"

if ! borg create "$TEST_ARCHIVE" "$TEST_FILE"; then
    log_error "Create FAILED under the constrained key. Append-only setup is broken."
    log_error "Repo is currently inaccessible from this server. Re-run setup-borg-backup.sh"
    log_error "to restore unconstrained access, fix the issue, then re-run this script."
    rm -f "$TEST_FILE"
    exit 1
fi
log_info "  Create: succeeded (expected)"

# Try to delete; we WANT this to fail. `borg delete` on a constrained server
# returns non-zero. We invert with `!` and check for the expected failure.
if borg delete "$TEST_ARCHIVE" 2>/dev/null; then
    log_error "Delete SUCCEEDED — append-only is NOT being enforced!"
    log_error "Investigate the authorized_keys file on the sub-account."
    rm -f "$TEST_FILE"
    exit 1
fi
log_info "  Delete: blocked (expected)"

rm -f "$TEST_FILE"

# The append-test archive is now stuck in the repo (we can't delete it from
# the constrained key). That's OK — it's tiny. Use the OFFLINE full-access
# key (from recovery kit) to prune it during the next maintenance window.
log_warn "The smoke-test archive '$TEST_ARCHIVE_NAME' is now in the repo."
log_warn "It cannot be removed from this server (that's the point). Prune it"
log_warn "from your offline workstation during the next maintenance window."

echo ""
echo "=============================================="
echo "  Append-only constraint active"
echo "=============================================="
echo ""
echo "Backup repo:       $BORG_REPO"
echo "Append-only key:   $SUBACCOUNT_KEY_PATH"
echo "Forced command:    borg serve --append-only --restrict-to-repository $REPO_PATH"
echo ""
echo "ROTATE THE SUB-ACCOUNT PASSWORD NOW:"
echo "  console.hetzner.cloud -> Storage Boxes -> $STORAGE_BOX_USER -> Sub-accounts"
echo "  → Reset password (do NOT update seed.yaml or terraform.tfvars — the"
echo "    password is only needed once, by these two setup scripts)."
echo ""
echo "After rotation, the only way the GitLab server can talk to the backup"
echo "repo is the constrained SSH key — exactly the property we want."
echo ""
echo "Verify no full-access secrets remain on this server:"
echo "  ls /root/.ssh/        # should only show storagebox_subaccount_key{,.pub}"
echo ""
