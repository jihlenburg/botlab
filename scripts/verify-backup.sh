#!/bin/bash
# =============================================================================
# Backup Verification Script
# =============================================================================
# Verifies GitLab backups are working correctly
# Usage: ./verify-backup.sh [--json] [--quiet]
#
# Options:
#   --json   Output results in JSON format
#   --quiet  Only show failures and summary

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

OUTPUT_JSON=false
QUIET=false
BACKUP_DIR="/var/opt/gitlab/backups"
LOG_FILE="/var/log/gitlab-backup.log"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --json)
            OUTPUT_JSON=true
            shift
            ;;
        --quiet)
            QUIET=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Colors (disabled for JSON output)
if [[ "$OUTPUT_JSON" == "true" ]]; then
    RED=''
    GREEN=''
    YELLOW=''
    NC=''
else
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m'
fi

# =============================================================================
# Logging Functions
# =============================================================================

log_info() {
    if [[ "$QUIET" == "false" ]] && [[ "$OUTPUT_JSON" == "false" ]]; then
        echo -e "${GREEN}[INFO]${NC} $1"
    fi
}

log_warn() {
    if [[ "$OUTPUT_JSON" == "false" ]]; then
        echo -e "${YELLOW}[WARN]${NC} $1"
    fi
}

log_error() {
    if [[ "$OUTPUT_JSON" == "false" ]]; then
        echo -e "${RED}[ERROR]${NC} $1" >&2
    fi
}

log_pass() {
    if [[ "$QUIET" == "false" ]] && [[ "$OUTPUT_JSON" == "false" ]]; then
        echo -e "${GREEN}[PASS]${NC} $1"
    fi
}

log_fail() {
    if [[ "$OUTPUT_JSON" == "false" ]]; then
        echo -e "${RED}[FAIL]${NC} $1"
    fi
}

# =============================================================================
# Utility Functions
# =============================================================================

CHECKS_PASSED=0
CHECKS_FAILED=0
declare -a CHECK_RESULTS=()

check() {
    local name="$1"
    local result="$2"

    if [[ "$result" == "0" ]]; then
        log_pass "$name"
        ((CHECKS_PASSED++)) || true
        CHECK_RESULTS+=("{\"name\": \"$name\", \"passed\": true}")
    else
        log_fail "$name"
        ((CHECKS_FAILED++)) || true
        CHECK_RESULTS+=("{\"name\": \"$name\", \"passed\": false}")
    fi
}

# Cross-platform stat command for file modification time
get_mtime() {
    local file="$1"
    if [[ "$(uname)" == "Darwin" ]]; then
        stat -f %m "$file"
    else
        stat -c %Y "$file"
    fi
}

# Cross-platform date parsing
parse_date() {
    local date_str="$1"
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS date
        date -j -f "%Y-%m-%dT%H:%M:%S" "${date_str%%.*}" +%s 2>/dev/null || \
        date -j -f "%Y-%m-%d %H:%M:%S" "$date_str" +%s 2>/dev/null || \
        echo "0"
    else
        # Linux date
        date -d "$date_str" +%s 2>/dev/null || echo "0"
    fi
}

output_json() {
    local results_json
    results_json=$(printf '%s\n' "${CHECK_RESULTS[@]}" | paste -sd ',' -)

    cat <<EOF
{
    "timestamp": "$(date -Iseconds)",
    "checks_passed": $CHECKS_PASSED,
    "checks_failed": $CHECKS_FAILED,
    "success": $([ $CHECKS_FAILED -eq 0 ] && echo "true" || echo "false"),
    "checks": [$results_json]
}
EOF
}

# =============================================================================
# Main
# =============================================================================

if [[ "$OUTPUT_JSON" == "false" ]]; then
    echo "=============================================="
    echo "    GitLab Backup Verification"
    echo "=============================================="
    echo ""
fi

# Load configuration
if [[ -f /etc/gitlab-backup.conf ]]; then
    # shellcheck source=/dev/null
    source /etc/gitlab-backup.conf
else
    log_error "Borg configuration not found at /etc/gitlab-backup.conf"
    if [[ "$OUTPUT_JSON" == "true" ]]; then
        echo '{"error": "Configuration not found", "success": false}'
    fi
    exit 1
fi

# Validate required config
if [[ -z "${BORG_REPO:-}" ]]; then
    log_error "BORG_REPO not set in configuration"
    if [[ "$OUTPUT_JSON" == "true" ]]; then
        echo '{"error": "BORG_REPO not configured", "success": false}'
    fi
    exit 1
fi

# =============================================================================
# Check 1: Local backup file exists
# =============================================================================

log_info "Checking local backup files..."

LATEST_LOCAL=$(find "$BACKUP_DIR" -name "*_gitlab_backup.tar" -type f -mtime -1 2>/dev/null | head -1 || echo "")

if [[ -n "$LATEST_LOCAL" ]]; then
    MTIME=$(get_mtime "$LATEST_LOCAL")
    BACKUP_AGE_HOURS=$(( ($(date +%s) - MTIME) / 3600 ))
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
    if [[ "$QUIET" == "false" ]] && [[ "$OUTPUT_JSON" == "false" ]]; then
        echo "  Recent archives:"
        echo "$BORG_ARCHIVES" | sed 's/^/    /'
    fi

    # Check age of most recent archive
    LATEST_ARCHIVE=$(borg list --last 1 --format '{archive}' "$BORG_REPO" 2>/dev/null || echo "")

    if [[ -n "$LATEST_ARCHIVE" ]]; then
        ARCHIVE_TIME=$(borg info "$BORG_REPO::$LATEST_ARCHIVE" --json 2>/dev/null | jq -r '.archives[0].start' 2>/dev/null || echo "")

        if [[ -n "$ARCHIVE_TIME" ]]; then
            ARCHIVE_EPOCH=$(parse_date "$ARCHIVE_TIME")
            if [[ "$ARCHIVE_EPOCH" != "0" ]]; then
                ARCHIVE_AGE_HOURS=$(( ($(date +%s) - ARCHIVE_EPOCH) / 3600 ))

                if [[ $ARCHIVE_AGE_HOURS -lt 2 ]]; then
                    check "Borg archive is recent (${ARCHIVE_AGE_HOURS}h old)" "0"
                else
                    check "Borg archive is recent (${ARCHIVE_AGE_HOURS}h old)" "1"
                    log_warn "Most recent Borg archive is older than 2 hours"
                fi
            else
                log_warn "Could not parse archive timestamp"
            fi
        fi
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
        ARCHIVE_SIZE=$(borg info "$BORG_REPO::$LATEST_ARCHIVE" --json 2>/dev/null | jq -r '.archives[0].stats.original_size' 2>/dev/null || echo "0")
        if [[ "$ARCHIVE_SIZE" != "0" ]] && [[ -n "$ARCHIVE_SIZE" ]]; then
            ARCHIVE_SIZE_GB=$(echo "scale=2; $ARCHIVE_SIZE / 1073741824" | bc 2>/dev/null || echo "unknown")
            if [[ "$QUIET" == "false" ]] && [[ "$OUTPUT_JSON" == "false" ]]; then
                echo "  Archive size: ${ARCHIVE_SIZE_GB} GB"
            fi
        fi
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

if [[ -f "$LOG_FILE" ]]; then
    LAST_LOG_TIME=$(get_mtime "$LOG_FILE")
    LOG_AGE_HOURS=$(( ($(date +%s) - LAST_LOG_TIME) / 3600 ))

    if [[ $LOG_AGE_HOURS -lt 2 ]]; then
        check "Backup log updated recently" "0"
    else
        check "Backup log updated recently" "1"
    fi

    # Check for recent errors
    RECENT_ERRORS=$(tail -50 "$LOG_FILE" 2>/dev/null | grep -i "error" | tail -5 || echo "")
    if [[ -n "$RECENT_ERRORS" ]]; then
        log_warn "Recent errors in backup log:"
        if [[ "$OUTPUT_JSON" == "false" ]]; then
            echo "$RECENT_ERRORS" | sed 's/^/    /'
        fi
    fi
else
    check "Backup log exists" "1"
fi

# =============================================================================
# Summary
# =============================================================================

# =============================================================================
# Summary
# =============================================================================

if [[ "$OUTPUT_JSON" == "true" ]]; then
    output_json
else
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
    else
        log_error "Some backup checks failed. Review output above."
    fi
fi

if [[ $CHECKS_FAILED -eq 0 ]]; then
    exit 0
else
    exit 1
fi
