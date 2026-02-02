#!/bin/bash
# =============================================================================
# GitLab Disaster Recovery Restore Script
# =============================================================================
# This script automates the GitLab restore process from BorgBackup
# Usage: ./restore-gitlab.sh [backup-archive-name]
#
# Features:
# - Extracts backup from Borg repository
# - Restores configuration files
# - Restores GitLab backup
# - Verifies restoration
# - Supports rollback on failure

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_NAME=$(basename "$0")
RESTORE_DIR="/tmp/gitlab-restore-$$"
BACKUP_DIR="/var/opt/gitlab/backups"
LOG_FILE="/var/log/gitlab-restore.log"
ROLLBACK_DIR="/tmp/gitlab-rollback-$$"

# Exit codes
EXIT_SUCCESS=0
EXIT_ERROR=1
EXIT_CONFIG_ERROR=2
EXIT_BACKUP_ERROR=3
EXIT_RESTORE_ERROR=4
EXIT_VERIFY_ERROR=5

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# =============================================================================
# Logging Functions
# =============================================================================

log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" >> "$LOG_FILE"
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
    log "INFO" "$1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    log "WARN" "$1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
    log "ERROR" "$1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
    log "STEP" "$1"
}

log_debug() {
    if [[ "${DEBUG:-false}" == "true" ]]; then
        echo -e "[DEBUG] $1"
    fi
    log "DEBUG" "$1"
}

# =============================================================================
# Utility Functions
# =============================================================================

die() {
    log_error "$1"
    exit "${2:-$EXIT_ERROR}"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        die "This script must be run as root" "$EXIT_ERROR"
    fi
}

check_dependencies() {
    local deps=("borg" "gitlab-ctl" "gitlab-backup" "curl")
    local missing=()

    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &>/dev/null; then
            missing+=("$dep")
        fi
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        die "Missing dependencies: ${missing[*]}" "$EXIT_CONFIG_ERROR"
    fi
}

load_config() {
    if [[ -f /etc/gitlab-backup.conf ]]; then
        # shellcheck source=/dev/null
        source /etc/gitlab-backup.conf
        log_debug "Loaded config from /etc/gitlab-backup.conf"
    else
        die "Borg configuration not found at /etc/gitlab-backup.conf" "$EXIT_CONFIG_ERROR"
    fi

    # Validate required variables
    if [[ -z "${BORG_REPO:-}" ]]; then
        die "BORG_REPO not set in configuration" "$EXIT_CONFIG_ERROR"
    fi
}

# =============================================================================
# Cleanup and Rollback Functions
# =============================================================================

cleanup() {
    log_info "Cleaning up temporary files..."
    rm -rf "$RESTORE_DIR" 2>/dev/null || true
}

create_rollback_point() {
    log_info "Creating rollback point..."
    mkdir -p "$ROLLBACK_DIR"

    # Backup current configuration
    if [[ -f /etc/gitlab/gitlab.rb ]]; then
        cp /etc/gitlab/gitlab.rb "$ROLLBACK_DIR/gitlab.rb.rollback"
    fi
    if [[ -f /etc/gitlab/gitlab-secrets.json ]]; then
        cp /etc/gitlab/gitlab-secrets.json "$ROLLBACK_DIR/gitlab-secrets.json.rollback"
    fi

    # Store current GitLab version
    if command -v gitlab-rake &>/dev/null; then
        gitlab-rake gitlab:env:info 2>/dev/null | grep "GitLab version" > "$ROLLBACK_DIR/version.txt" || true
    fi

    log_debug "Rollback point created at $ROLLBACK_DIR"
}

rollback() {
    log_warn "Rolling back changes..."

    if [[ -d "$ROLLBACK_DIR" ]]; then
        # Restore configuration files
        if [[ -f "$ROLLBACK_DIR/gitlab.rb.rollback" ]]; then
            cp "$ROLLBACK_DIR/gitlab.rb.rollback" /etc/gitlab/gitlab.rb
            log_info "Restored gitlab.rb"
        fi
        if [[ -f "$ROLLBACK_DIR/gitlab-secrets.json.rollback" ]]; then
            cp "$ROLLBACK_DIR/gitlab-secrets.json.rollback" /etc/gitlab/gitlab-secrets.json
            log_info "Restored gitlab-secrets.json"
        fi

        # Reconfigure GitLab
        log_info "Reconfiguring GitLab after rollback..."
        gitlab-ctl reconfigure || log_warn "Reconfigure failed during rollback"
        gitlab-ctl restart || log_warn "Restart failed during rollback"
    else
        log_warn "No rollback point available"
    fi

    rm -rf "$ROLLBACK_DIR" 2>/dev/null || true
}

cleanup_rollback() {
    rm -rf "$ROLLBACK_DIR" 2>/dev/null || true
}

trap cleanup EXIT

# =============================================================================
# Backup Functions
# =============================================================================

list_backups() {
    log_info "Available backups in Borg repository:"
    echo ""
    borg list "$BORG_REPO" 2>/dev/null || die "Failed to list Borg archives" "$EXIT_BACKUP_ERROR"
    echo ""
}

get_latest_backup() {
    borg list --last 1 --format '{archive}' "$BORG_REPO" 2>/dev/null
}

validate_backup() {
    local backup_name="$1"
    log_info "Validating backup archive: $backup_name"

    # Check archive exists and is readable
    if ! borg info "$BORG_REPO::$backup_name" &>/dev/null; then
        die "Backup archive not found or not accessible: $backup_name" "$EXIT_BACKUP_ERROR"
    fi

    # Check archive contains required files
    local contents
    contents=$(borg list "$BORG_REPO::$backup_name" 2>/dev/null)

    if ! echo "$contents" | grep -q "gitlab.rb"; then
        log_warn "Archive may not contain gitlab.rb"
    fi
    if ! echo "$contents" | grep -q "gitlab-secrets.json"; then
        log_warn "Archive may not contain gitlab-secrets.json"
    fi
    if ! echo "$contents" | grep -q "_gitlab_backup.tar"; then
        die "Archive does not contain GitLab backup tarball" "$EXIT_BACKUP_ERROR"
    fi

    log_info "Backup validation passed"
}

# =============================================================================
# Restore Functions
# =============================================================================

extract_backup() {
    local backup_name="$1"

    log_step "Extracting backup from Borg repository..."
    mkdir -p "$RESTORE_DIR"
    cd "$RESTORE_DIR"

    if ! borg extract --progress "$BORG_REPO::$backup_name" 2>&1 | tee -a "$LOG_FILE"; then
        die "Failed to extract backup from Borg" "$EXIT_BACKUP_ERROR"
    fi

    # Find extracted files
    CONFIG_DIR=$(find "$RESTORE_DIR" -type d -name "gitlab" -path "*/etc/*" | head -1)
    BACKUP_FILE=$(find "$RESTORE_DIR" -name "*_gitlab_backup.tar" -type f | head -1)

    if [[ -z "$BACKUP_FILE" ]]; then
        die "No GitLab backup file found in archive" "$EXIT_BACKUP_ERROR"
    fi

    log_info "Found backup file: $BACKUP_FILE"
    log_info "Found config directory: ${CONFIG_DIR:-'(none)'}"
}

restore_configuration() {
    log_step "Restoring configuration files..."

    # Backup current config first
    if [[ -f /etc/gitlab/gitlab.rb ]]; then
        cp /etc/gitlab/gitlab.rb /etc/gitlab/gitlab.rb.pre-restore
    fi
    if [[ -f /etc/gitlab/gitlab-secrets.json ]]; then
        cp /etc/gitlab/gitlab-secrets.json /etc/gitlab/gitlab-secrets.json.pre-restore
    fi

    # Restore configuration
    if [[ -n "${CONFIG_DIR:-}" ]] && [[ -d "$CONFIG_DIR" ]]; then
        if [[ -f "$CONFIG_DIR/gitlab.rb" ]]; then
            cp "$CONFIG_DIR/gitlab.rb" /etc/gitlab/gitlab.rb
            chmod 600 /etc/gitlab/gitlab.rb
            log_info "Restored gitlab.rb"
        fi

        if [[ -f "$CONFIG_DIR/gitlab-secrets.json" ]]; then
            cp "$CONFIG_DIR/gitlab-secrets.json" /etc/gitlab/gitlab-secrets.json
            chmod 600 /etc/gitlab/gitlab-secrets.json
            log_info "Restored gitlab-secrets.json"
        fi
    else
        log_warn "Configuration directory not found in backup, keeping existing config"
    fi
}

copy_backup_file() {
    log_step "Copying backup file to GitLab backups directory..."

    mkdir -p "$BACKUP_DIR"
    cp "$BACKUP_FILE" "$BACKUP_DIR/"
    BACKUP_FILENAME=$(basename "$BACKUP_FILE")

    # Extract timestamp from backup filename
    # Format: TIMESTAMP_YYYY_MM_DD_VERSION_gitlab_backup.tar
    BACKUP_TIMESTAMP=$(echo "$BACKUP_FILENAME" | sed 's/_gitlab_backup.tar$//')

    log_info "Backup timestamp: $BACKUP_TIMESTAMP"
}

stop_services() {
    log_step "Stopping GitLab services for restore..."

    gitlab-ctl stop puma || log_warn "Could not stop puma"
    gitlab-ctl stop sidekiq || log_warn "Could not stop sidekiq"

    # Wait for services to stop
    sleep 5

    # Verify services are stopped
    log_debug "Current service status:"
    gitlab-ctl status || true
}

run_restore() {
    log_step "Running GitLab backup restore (this may take a while)..."

    # Run the restore with force=yes to avoid prompts
    if ! gitlab-backup restore BACKUP="$BACKUP_TIMESTAMP" force=yes 2>&1 | tee -a "$LOG_FILE"; then
        log_error "GitLab restore command failed"
        return 1
    fi

    return 0
}

reconfigure_gitlab() {
    log_step "Reconfiguring and restarting GitLab..."

    if ! gitlab-ctl reconfigure 2>&1 | tee -a "$LOG_FILE"; then
        log_error "GitLab reconfigure failed"
        return 1
    fi

    if ! gitlab-ctl restart 2>&1 | tee -a "$LOG_FILE"; then
        log_error "GitLab restart failed"
        return 1
    fi

    # Wait for GitLab to start
    log_info "Waiting for GitLab to be ready..."
    sleep 30

    return 0
}

# =============================================================================
# Verification Functions
# =============================================================================

verify_restore() {
    log_step "Running verification checks..."

    local checks_passed=0
    local checks_failed=0

    # Check GitLab status
    log_info "Checking GitLab service status..."
    if gitlab-ctl status | grep -q "down:"; then
        log_warn "Some services are down"
        ((checks_failed++))
    else
        log_info "All services running"
        ((checks_passed++))
    fi

    # Run GitLab check
    log_info "Running GitLab integrity check..."
    if gitlab-rake gitlab:check SANITIZE=true 2>&1 | grep -qi "failure\|error"; then
        log_warn "GitLab check found some issues"
        ((checks_failed++))
    else
        log_info "GitLab check passed"
        ((checks_passed++))
    fi

    # Test health endpoint
    log_info "Testing health endpoint..."
    if curl -sf http://localhost/-/health > /dev/null 2>&1; then
        log_info "Health check: PASSED"
        ((checks_passed++))
    else
        log_warn "Health check: FAILED (GitLab may still be starting)"
        ((checks_failed++))
    fi

    # Test readiness endpoint
    log_info "Testing readiness endpoint..."
    if curl -sf http://localhost/-/readiness > /dev/null 2>&1; then
        log_info "Readiness check: PASSED"
        ((checks_passed++))
    else
        log_warn "Readiness check: FAILED"
        ((checks_failed++))
    fi

    # Check database connectivity
    log_info "Testing database connectivity..."
    if gitlab-psql -c "SELECT 1;" > /dev/null 2>&1; then
        log_info "Database check: PASSED"
        ((checks_passed++))
    else
        log_warn "Database check: FAILED"
        ((checks_failed++))
    fi

    echo ""
    log_info "Verification summary: $checks_passed passed, $checks_failed failed"

    if [[ $checks_failed -gt 0 ]]; then
        return 1
    fi
    return 0
}

# =============================================================================
# Main
# =============================================================================

main() {
    echo "=============================================="
    echo "    GitLab Disaster Recovery Restore"
    echo "=============================================="
    echo ""

    # Pre-flight checks
    check_root
    check_dependencies
    load_config

    # Get backup name from argument or interactive selection
    BACKUP_NAME="${1:-}"

    if [[ -z "$BACKUP_NAME" ]]; then
        list_backups
        echo ""
        read -r -p "Enter backup archive name to restore (or 'latest' for most recent): " BACKUP_NAME
    fi

    if [[ -z "$BACKUP_NAME" ]]; then
        die "No backup name specified" "$EXIT_ERROR"
    fi

    if [[ "$BACKUP_NAME" == "latest" ]]; then
        BACKUP_NAME=$(get_latest_backup)
        if [[ -z "$BACKUP_NAME" ]]; then
            die "No backups found in repository" "$EXIT_BACKUP_ERROR"
        fi
        log_info "Using most recent backup: $BACKUP_NAME"
    fi

    # Validate the backup
    validate_backup "$BACKUP_NAME"

    # Confirm restore
    echo ""
    log_warn "This will restore GitLab from backup: $BACKUP_NAME"
    log_warn "This is a DESTRUCTIVE operation and will overwrite current data!"
    echo ""
    read -r -p "Are you sure you want to continue? (yes/no): " CONFIRM

    if [[ "$CONFIRM" != "yes" ]]; then
        log_info "Restore cancelled by user"
        exit "$EXIT_SUCCESS"
    fi

    # Create rollback point
    create_rollback_point

    # Start restore process
    log_info "Starting restore process..."
    log "INFO" "=== Restore started for backup: $BACKUP_NAME ==="

    # Step 1: Extract backup
    extract_backup "$BACKUP_NAME"

    # Step 2: Restore configuration
    restore_configuration

    # Step 3: Copy backup file
    copy_backup_file

    # Step 4: Stop services
    stop_services

    # Step 5: Run restore
    if ! run_restore; then
        log_error "Restore failed!"
        read -r -p "Do you want to attempt rollback? (yes/no): " DO_ROLLBACK
        if [[ "$DO_ROLLBACK" == "yes" ]]; then
            rollback
        fi
        exit "$EXIT_RESTORE_ERROR"
    fi

    # Step 6: Reconfigure
    if ! reconfigure_gitlab; then
        log_error "Reconfigure failed!"
        read -r -p "Do you want to attempt rollback? (yes/no): " DO_ROLLBACK
        if [[ "$DO_ROLLBACK" == "yes" ]]; then
            rollback
        fi
        exit "$EXIT_RESTORE_ERROR"
    fi

    # Step 7: Verify
    echo ""
    if ! verify_restore; then
        log_warn "Some verification checks failed. GitLab may need additional time to start."
        log_warn "Please check the services and try again in a few minutes."
    fi

    # Clean up rollback point on success
    cleanup_rollback

    # Complete
    echo ""
    echo "=============================================="
    echo "    Restore Complete!"
    echo "=============================================="
    echo ""
    log_info "GitLab has been restored from backup: $BACKUP_NAME"
    log_info "Restore log available at: $LOG_FILE"
    echo ""
    echo "Next steps:"
    echo "1. Verify GitLab is accessible via web UI"
    echo "2. Test user login (SSO if configured)"
    echo "3. Test git clone/push operations"
    echo "4. Update DNS if this is a new server"
    echo "5. Verify object storage (LFS, artifacts) is accessible"
    echo "6. Check Runner connectivity if using CI/CD"
    echo ""

    log "INFO" "=== Restore completed successfully ==="
}

# Run main function
main "$@"
