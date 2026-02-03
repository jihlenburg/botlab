#!/bin/bash
# =============================================================================
# S3 Immutable Backup Script
# =============================================================================
# Exports the latest Borg archive and uploads it to an S3-compatible bucket
# with Object Lock (WORM) retention for ransomware-resistant off-site backups.
#
# Implements: SECURITY-ASSESSMENT.md Section 3.3.3 / DESIGN.md Section 6.3.3
#
# Compatible with:
#   - Backblaze B2 (S3-compatible API)
#   - AWS S3 (with Object Lock enabled)
#   - Wasabi (with Object Lock enabled)
#
# Prerequisites:
#   - aws CLI v2 installed (apt install awscli or pip install awscli)
#   - BorgBackup configured (/etc/gitlab-backup.conf)
#   - S3 bucket with Object Lock enabled and a default retention policy
#   - /etc/gitlab-s3-backup.conf with credentials (see below)
#
# Configuration file: /etc/gitlab-s3-backup.conf
#   export S3_ENDPOINT="s3.us-west-002.backblazeb2.com"
#   export S3_BUCKET="gitlab-immutable-backups"
#   export AWS_ACCESS_KEY_ID="your-access-key"
#   export AWS_SECRET_ACCESS_KEY="your-secret-key"
#   export S3_RETENTION_DAYS=90
#
# Usage:
#   sudo ./backup-to-s3.sh              # Export latest archive and upload
#   sudo ./backup-to-s3.sh --verify     # Verify the most recent S3 upload
#
# Schedule (cron): Run weekly — see setup instructions at end of file.
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"; }

LOG_FILE="/var/log/gitlab-s3-backup.log"
WORK_DIR="/var/tmp/gitlab-s3-export"

# Redirect all output to log file as well
exec > >(tee -a "$LOG_FILE") 2>&1

# =============================================================================
# Load configuration
# =============================================================================

BORG_CONF="/etc/gitlab-backup.conf"
S3_CONF="/etc/gitlab-s3-backup.conf"

if [[ ! -f "$BORG_CONF" ]]; then
    log_error "Borg config not found: $BORG_CONF"
    exit 1
fi

if [[ ! -f "$S3_CONF" ]]; then
    log_error "S3 config not found: $S3_CONF"
    log_error "Create $S3_CONF with S3_ENDPOINT, S3_BUCKET, AWS_ACCESS_KEY_ID,"
    log_error "AWS_SECRET_ACCESS_KEY, and S3_RETENTION_DAYS."
    exit 1
fi

# shellcheck disable=SC1090
source "$BORG_CONF"
# shellcheck disable=SC1090
source "$S3_CONF"

# Validate required variables
for var in S3_ENDPOINT S3_BUCKET AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; do
    if [[ -z "${!var:-}" ]]; then
        log_error "Required variable $var not set in $S3_CONF"
        exit 1
    fi
done

S3_RETENTION_DAYS="${S3_RETENTION_DAYS:-90}"

# Check for aws CLI
if ! command -v aws &>/dev/null; then
    log_error "aws CLI not found. Install with: apt install awscli"
    exit 1
fi

# =============================================================================
# Verify mode
# =============================================================================

if [[ "${1:-}" == "--verify" ]]; then
    log_info "Verifying most recent S3 backup..."

    LATEST=$(aws s3 ls "s3://${S3_BUCKET}/" \
        --endpoint-url "https://${S3_ENDPOINT}" \
        | sort | tail -1 | awk '{print $NF}')

    if [[ -z "$LATEST" ]]; then
        log_error "No backups found in s3://${S3_BUCKET}/"
        exit 1
    fi

    log_info "Latest S3 backup: $LATEST"

    # Check object lock status
    aws s3api head-object \
        --bucket "$S3_BUCKET" \
        --key "$LATEST" \
        --endpoint-url "https://${S3_ENDPOINT}" \
        2>&1 | grep -i -E "retention|lock" || log_warn "Could not verify Object Lock status"

    log_info "Verification complete"
    exit 0
fi

# =============================================================================
# Step 1: Find latest Borg archive
# =============================================================================

log_info "=== S3 Immutable Backup Started ==="

log_info "Step 1: Finding latest Borg archive..."

LATEST_ARCHIVE=$(borg list --last 1 --format '{archive}' "$BORG_REPO" 2>/dev/null)

if [[ -z "$LATEST_ARCHIVE" ]]; then
    log_error "No archives found in Borg repository"
    exit 1
fi

log_info "Latest archive: $LATEST_ARCHIVE"

# =============================================================================
# Step 2: Export archive to tarball
# =============================================================================

log_info "Step 2: Exporting Borg archive to tarball..."

mkdir -p "$WORK_DIR"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
EXPORT_FILE="${WORK_DIR}/gitlab-backup-${TIMESTAMP}.tar.gz"

borg export-tar --tar-filter="gzip" \
    "${BORG_REPO}::${LATEST_ARCHIVE}" \
    "$EXPORT_FILE"

EXPORT_SIZE=$(stat -c %s "$EXPORT_FILE" 2>/dev/null || stat -f %z "$EXPORT_FILE")
EXPORT_SIZE_MB=$((EXPORT_SIZE / 1024 / 1024))

log_info "Exported: $EXPORT_FILE ($EXPORT_SIZE_MB MB)"

# =============================================================================
# Step 3: Compute checksum
# =============================================================================

log_info "Step 3: Computing SHA-256 checksum..."

CHECKSUM=$(sha256sum "$EXPORT_FILE" | awk '{print $1}')
echo "$CHECKSUM  $(basename "$EXPORT_FILE")" > "${EXPORT_FILE}.sha256"

log_info "Checksum: $CHECKSUM"

# =============================================================================
# Step 4: Upload to S3 with Object Lock metadata
# =============================================================================

log_info "Step 4: Uploading to s3://${S3_BUCKET}/..."

S3_KEY="$(basename "$EXPORT_FILE")"
S3_KEY_CHECKSUM="$(basename "${EXPORT_FILE}.sha256")"

# Calculate retention date
RETAIN_UNTIL=$(date -u -d "+${S3_RETENTION_DAYS} days" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
    || date -u -v "+${S3_RETENTION_DAYS}d" +%Y-%m-%dT%H:%M:%SZ)

# Upload tarball
aws s3 cp "$EXPORT_FILE" "s3://${S3_BUCKET}/${S3_KEY}" \
    --endpoint-url "https://${S3_ENDPOINT}" \
    --metadata "borg-archive=${LATEST_ARCHIVE},sha256=${CHECKSUM}" \
    --no-progress

# Upload checksum file
aws s3 cp "${EXPORT_FILE}.sha256" "s3://${S3_BUCKET}/${S3_KEY_CHECKSUM}" \
    --endpoint-url "https://${S3_ENDPOINT}" \
    --no-progress

log_info "Upload complete: s3://${S3_BUCKET}/${S3_KEY}"

# =============================================================================
# Step 5: Apply Object Lock retention (if supported)
# =============================================================================

log_info "Step 5: Applying Object Lock retention (${S3_RETENTION_DAYS} days)..."

if aws s3api put-object-retention \
    --bucket "$S3_BUCKET" \
    --key "$S3_KEY" \
    --retention "{\"Mode\":\"COMPLIANCE\",\"RetainUntilDate\":\"${RETAIN_UNTIL}\"}" \
    --endpoint-url "https://${S3_ENDPOINT}" 2>/dev/null; then
    log_info "Object Lock retention set until $RETAIN_UNTIL"
else
    log_warn "Could not set Object Lock retention."
    log_warn "Ensure the bucket has Object Lock enabled with a default retention policy."
fi

# =============================================================================
# Step 6: Verify upload integrity
# =============================================================================

log_info "Step 6: Verifying upload integrity..."

# Get the ETag (MD5 for non-multipart uploads)
REMOTE_META=$(aws s3api head-object \
    --bucket "$S3_BUCKET" \
    --key "$S3_KEY" \
    --endpoint-url "https://${S3_ENDPOINT}" 2>&1)

REMOTE_SIZE=$(echo "$REMOTE_META" | grep -i "ContentLength" | awk '{print $2}' | tr -d ',' || true)

if [[ "$REMOTE_SIZE" == "$EXPORT_SIZE" ]]; then
    log_info "Size verification passed ($EXPORT_SIZE bytes)"
else
    log_warn "Size mismatch: local=$EXPORT_SIZE remote=${REMOTE_SIZE:-unknown}"
fi

# =============================================================================
# Step 7: Cleanup local export
# =============================================================================

log_info "Step 7: Cleaning up local export files..."

rm -f "$EXPORT_FILE" "${EXPORT_FILE}.sha256"
rmdir "$WORK_DIR" 2>/dev/null || true

log_info "=== S3 Immutable Backup Complete ==="
log_info "Archive:   $LATEST_ARCHIVE"
log_info "S3 key:    s3://${S3_BUCKET}/${S3_KEY}"
log_info "Size:      ${EXPORT_SIZE_MB} MB"
log_info "Checksum:  ${CHECKSUM}"
log_info "Retention: ${S3_RETENTION_DAYS} days (until ${RETAIN_UNTIL})"

# =============================================================================
# Cron setup instructions (run weekly, Sunday 04:00 UTC — after Borg prune):
#
#   cat > /etc/cron.d/gitlab-s3-backup << 'EOF'
#   0 4 * * 0 root /usr/local/bin/backup-to-s3.sh >> /var/log/gitlab-s3-backup.log 2>&1
#   EOF
#   chmod 644 /etc/cron.d/gitlab-s3-backup
#
# =============================================================================
