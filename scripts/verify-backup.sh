#!/bin/bash
# =============================================================================
# Backup Verification Script
# =============================================================================
# Verifies GitLab backups are working correctly
# Usage: ./verify-backup.sh

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
log_fail() { echo -e "${RED}[FAIL]${NC} $1"; }

CHECKS_PASSED=0
CHECKS_FAILED=0

check() {
    local name="$1"
    local result="$2"

    if [[ "$result" == "0" ]]; then
        log_pass "$name"
        ((CHECKS_PASSED++))
    else
        log_fail "$name"
        ((CHECKS_FAILED++))
    fi
}

echo "=============================================="
echo "    GitLab Backup Verification"
echo "=============================================="
echo ""

# Load configuration
if [[ -f /etc/gitlab-backup.conf ]]; then
    source /etc/gitlab-backup.conf
else
    log_error "Borg configuration not found"
    exit 1
fi

# =============================================================================
# Check 1: Local backup file exists
# =============================================================================

log_info "Checking local backup files..."

BACKUP_DIR="/var/opt/gitlab/backups"
LATEST_LOCAL=$(find "$BACKUP_DIR" -name "*_gitlab_backup.tar" -type f -mtime -1 2>/dev/null | head -1)

if [[ -n "$LATEST_LOCAL" ]]; then
    BACKUP_AGE_HOURS=$(( ($(date +%s) - $(stat -c %Y "$LATEST_LOCAL")) / 3600 ))
    check "Local backup exists (age: ${BACKUP_AGE_HOURS}h)" "0"

    if [[ $BACKUP_AGE_HOURS -gt 4 ]]; then
        log_warn "Local backup is older than 4 hours"
    fi
else
    check "Local backup exists" "1"
fi

# =============================================================================
# Check 2: Borg repository accessible
# =============================================================================

log_info "Checking Borg repository access..."

if borg info "$BORG_REPO" &>/dev/null; then
    check "Borg repository accessible" "0"
else
    check "Borg repository accessible" "1"
fi

# =============================================================================
# Check 3: Recent Borg archive exists
# =============================================================================

log_info "Checking Borg archives..."

BORG_ARCHIVES=$(borg list --last 5 --format '{archive}{NL}' "$BORG_REPO" 2>/dev/null || echo "")

if [[ -n "$BORG_ARCHIVES" ]]; then
    check "Borg archives exist" "0"
    echo "  Recent archives:"
    echo "$BORG_ARCHIVES" | sed 's/^/    /'

    # Check age of most recent archive
    LATEST_ARCHIVE=$(borg list --last 1 --format '{archive}' "$BORG_REPO")
    ARCHIVE_TIME=$(borg info "$BORG_REPO::$LATEST_ARCHIVE" --json | jq -r '.archives[0].start')
    ARCHIVE_EPOCH=$(date -d "$ARCHIVE_TIME" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%S" "$ARCHIVE_TIME" +%s 2>/dev/null)
    ARCHIVE_AGE_HOURS=$(( ($(date +%s) - $ARCHIVE_EPOCH) / 3600 ))

    if [[ $ARCHIVE_AGE_HOURS -lt 2 ]]; then
        check "Borg archive is recent (${ARCHIVE_AGE_HOURS}h old)" "0"
    else
        check "Borg archive is recent (${ARCHIVE_AGE_HOURS}h old)" "1"
        log_warn "Most recent Borg archive is older than 2 hours"
    fi
else
    check "Borg archives exist" "1"
fi

# =============================================================================
# Check 4: Verify archive integrity
# =============================================================================

log_info "Verifying archive integrity (quick check)..."

if [[ -n "${LATEST_ARCHIVE:-}" ]]; then
    if borg info "$BORG_REPO::$LATEST_ARCHIVE" &>/dev/null; then
        check "Archive integrity check" "0"

        # Show archive stats
        ARCHIVE_SIZE=$(borg info "$BORG_REPO::$LATEST_ARCHIVE" --json | jq -r '.archives[0].stats.original_size')
        ARCHIVE_SIZE_GB=$(echo "scale=2; $ARCHIVE_SIZE / 1073741824" | bc)
        echo "  Archive size: ${ARCHIVE_SIZE_GB} GB"
    else
        check "Archive integrity check" "1"
    fi
else
    log_warn "Skipping integrity check - no archive to check"
fi

# =============================================================================
# Check 5: Configuration files in backup
# =============================================================================

log_info "Checking backup contents..."

if [[ -n "${LATEST_ARCHIVE:-}" ]]; then
    BACKUP_CONTENTS=$(borg list "$BORG_REPO::$LATEST_ARCHIVE" 2>/dev/null || echo "")

    if echo "$BACKUP_CONTENTS" | grep -q "gitlab.rb"; then
        check "gitlab.rb in backup" "0"
    else
        check "gitlab.rb in backup" "1"
    fi

    if echo "$BACKUP_CONTENTS" | grep -q "gitlab-secrets.json"; then
        check "gitlab-secrets.json in backup" "0"
    else
        check "gitlab-secrets.json in backup" "1"
    fi

    if echo "$BACKUP_CONTENTS" | grep -q "_gitlab_backup.tar"; then
        check "GitLab backup tarball in backup" "0"
    else
        check "GitLab backup tarball in backup" "1"
    fi
fi

# =============================================================================
# Check 6: Backup log
# =============================================================================

log_info "Checking backup log..."

LOG_FILE="/var/log/gitlab-backup.log"
if [[ -f "$LOG_FILE" ]]; then
    LAST_LOG_TIME=$(stat -c %Y "$LOG_FILE")
    LOG_AGE_HOURS=$(( ($(date +%s) - $LAST_LOG_TIME) / 3600 ))

    if [[ $LOG_AGE_HOURS -lt 2 ]]; then
        check "Backup log updated recently" "0"
    else
        check "Backup log updated recently" "1"
    fi

    # Check for recent errors
    RECENT_ERRORS=$(tail -50 "$LOG_FILE" | grep -i "error" | tail -5 || echo "")
    if [[ -n "$RECENT_ERRORS" ]]; then
        log_warn "Recent errors in backup log:"
        echo "$RECENT_ERRORS" | sed 's/^/    /'
    fi
else
    check "Backup log exists" "1"
fi

# =============================================================================
# Summary
# =============================================================================

echo ""
echo "=============================================="
echo "    Verification Summary"
echo "=============================================="
echo ""
echo "Checks passed: $CHECKS_PASSED"
echo "Checks failed: $CHECKS_FAILED"
echo ""

if [[ $CHECKS_FAILED -eq 0 ]]; then
    log_info "All backup checks passed!"
    exit 0
else
    log_error "Some backup checks failed. Review output above."
    exit 1
fi
