#!/bin/bash
# =============================================================================
# Initialize the Borg repository on the append-only Storage Box sub-account
# =============================================================================
#
# Run ONCE per fresh deploy, on the GitLab server, AFTER:
#   1. `terraform apply` provisioned the Storage Box + sub-account
#      (see terraform/storage_box.tf — Hetzner Cloud product as of provider
#      v1.63.0; no longer Hetzner Robot)
#   2. seed.yaml host/user filled in from `terraform output
#      storage_box_post_apply` and `seed_bootstrap.py --target borg-conf`
#      regenerated /etc/gitlab-backup.conf
#   3. /etc/gitlab-backup.conf is in place on this server (chmod 600)
#
# After this script: the Borg repo exists, the sub-account's
# ~/.ssh/authorized_keys holds an UNCONSTRAINED SSH key (server can read,
# write, AND delete). The next script (setup-borg-append-only.sh) replaces
# that with a forced-command CONSTRAINED key so only append is possible.
# Always run the two scripts back-to-back.
#
# Required environment variable:
#   STORAGEBOX_SUBACCOUNT_PASSWORD — the sub-account password from
#   seed.yaml backup.storage_box.subaccount_password. Used for SFTP login
#   so we can install the SSH key. Not persisted anywhere. Rotate the
#   password in the Hetzner Console after setup-borg-append-only.sh
#   completes.
#
# Usage:
#   sudo STORAGEBOX_SUBACCOUNT_PASSWORD='...' ./setup-borg-backup.sh

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
    log_error "Set it from seed.yaml backup.storage_box.subaccount_password:"
    log_error "  sudo STORAGEBOX_SUBACCOUNT_PASSWORD='...' $0"
    exit 1
fi

CONF_FILE="/etc/gitlab-backup.conf"
if [[ ! -f "$CONF_FILE" ]]; then
    log_error "$CONF_FILE not found. Generate it with:"
    log_error "  python scripts/seed_bootstrap.py seed.yaml --target borg-conf"
    log_error "Then SCP it to this server at $CONF_FILE (chmod 600)."
    exit 1
fi

# shellcheck disable=SC1090
source "$CONF_FILE"

# Required exports from the conf
for var in BORG_REPO BORG_PASSPHRASE BORG_RSH; do
    if [[ -z "${!var:-}" ]]; then
        log_error "$var not set in $CONF_FILE. Re-run seed_bootstrap.py."
        exit 1
    fi
done

# Pull the host + user out of $BORG_REPO ("ssh://user@host:23/...")
STORAGE_BOX_USER="$(echo "$BORG_REPO" | sed -E 's|ssh://([^@]+)@.*|\1|')"
STORAGE_BOX_HOST="$(echo "$BORG_REPO" | sed -E 's|ssh://[^@]+@([^:/]+).*|\1|')"

if [[ -z "$STORAGE_BOX_USER" || -z "$STORAGE_BOX_HOST" ]]; then
    log_error "Could not parse user/host from BORG_REPO: $BORG_REPO"
    exit 1
fi

# sshpass is needed for the SFTP key install (no key on Storage Box yet)
if ! command -v sshpass >/dev/null 2>&1; then
    log_error "sshpass not installed. apt-get install -y sshpass"
    exit 1
fi

SUBACCOUNT_KEY_PATH="/root/.ssh/storagebox_subaccount_key"

echo "=============================================="
echo "  Borg repo init on Storage Box sub-account"
echo "=============================================="
echo "  Sub-account:  $STORAGE_BOX_USER@$STORAGE_BOX_HOST"
echo "  Repo:         $BORG_REPO"
echo "  SSH key:      $SUBACCOUNT_KEY_PATH (will be created)"
echo ""

# ---- Step 1: Generate the sub-account SSH key on this server --------------

log_info "Step 1/4: Generating SSH key for sub-account access..."

if [[ -f "$SUBACCOUNT_KEY_PATH" ]]; then
    log_warn "Key already exists at $SUBACCOUNT_KEY_PATH"
    read -rp "Re-use the existing key? (yes/no): " REUSE
    if [[ "$REUSE" != "yes" ]]; then
        log_error "Refusing to overwrite. Delete it manually first if you want to regenerate."
        exit 1
    fi
else
    install -d -m 700 /root/.ssh
    ssh-keygen -t ed25519 -f "$SUBACCOUNT_KEY_PATH" -N "" \
        -C "gitlab-borg-subaccount@$(hostname)"
    chmod 600 "$SUBACCOUNT_KEY_PATH"
fi

# ---- Step 2: Install UNCONSTRAINED authorized_keys via SFTP ---------------

log_info "Step 2/4: Installing SSH key on the sub-account (unconstrained, for init)..."

# Just the pubkey, no forced-command yet. setup-borg-append-only.sh replaces
# this with a forced-command line after init succeeds.
SFTP_BATCH="$(mktemp)"
trap 'rm -f "$SFTP_BATCH"' EXIT
cat > "$SFTP_BATCH" <<EOF
-mkdir .ssh
chmod 700 .ssh
put $SUBACCOUNT_KEY_PATH.pub .ssh/authorized_keys
chmod 600 .ssh/authorized_keys
EOF

if ! SSHPASS="$STORAGEBOX_SUBACCOUNT_PASSWORD" sshpass -e sftp \
        -o StrictHostKeyChecking=accept-new \
        -P 23 -b "$SFTP_BATCH" "$STORAGE_BOX_USER@$STORAGE_BOX_HOST"; then
    log_error "SFTP key install failed. Check that the sub-account password is correct."
    log_error "(rotate it in console.hetzner.cloud and update seed.yaml if needed)"
    exit 1
fi

log_info "Key installed. Testing SSH..."
if ! ssh -i "$SUBACCOUNT_KEY_PATH" -p 23 \
        -o StrictHostKeyChecking=accept-new \
        "$STORAGE_BOX_USER@$STORAGE_BOX_HOST" "echo ok" >/dev/null 2>&1; then
    log_error "SSH test failed even after key install. Aborting before init."
    exit 1
fi

# ---- Step 3: borg init ----------------------------------------------------

log_info "Step 3/4: Initializing Borg repository (repokey-blake2)..."

if borg info "$BORG_REPO" >/dev/null 2>&1; then
    log_warn "Borg repository already exists at $BORG_REPO — skipping init"
else
    borg init --encryption=repokey-blake2 "$BORG_REPO"
    log_info "Repo initialized with repokey-blake2"
fi

# ---- Step 4: Test create + delete (proves unconstrained still works) ------

log_info "Step 4/4: Creating + deleting a test archive..."

TEST_FILE="$(mktemp)"
echo "init-smoke-test $(date -u +%FT%TZ)" > "$TEST_FILE"
TEST_ARCHIVE="${BORG_REPO}::init-test-$(date -u +%Y%m%d-%H%M%S)"

borg create "$TEST_ARCHIVE" "$TEST_FILE"
borg delete "$TEST_ARCHIVE"
rm -f "$TEST_FILE"

log_info "Test archive create + delete succeeded (confirms unconstrained access)."

echo ""
echo "=============================================="
echo "  Init complete — NEXT STEP REQUIRED"
echo "=============================================="
echo ""
echo "The sub-account currently has UNCONSTRAINED access. To enforce"
echo "append-only protection (the whole point of the sub-account), run:"
echo ""
echo "  sudo STORAGEBOX_SUBACCOUNT_PASSWORD='...' /opt/botlab/scripts/setup-borg-append-only.sh"
echo ""
echo "DO NOT run any production backups until that step completes —"
echo "the ransomware-resistance is not yet active."
echo ""
