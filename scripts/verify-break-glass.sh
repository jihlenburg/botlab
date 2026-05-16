#!/bin/bash
# =============================================================================
# scripts/verify-break-glass.sh
# =============================================================================
#
# Quarterly (or more frequent) verification of the GitLab break-glass admin.
#
# Confirms:
#   1. The account exists, is an Administrator, is confirmed, is not
#      blocked, and has TOTP enabled.
#   2. The bypass URL (?auto_sign_in=false) serves the local-auth form
#      rather than auto-redirecting to SSO.
#   3. Writes Prometheus textfile-collector metrics for monitoring:
#        gitlab_break_glass_account_present       (gauge 0|1)
#        gitlab_break_glass_kit_verified_timestamp (gauge, unix time)
#        gitlab_break_glass_verification_ok       (gauge 0|1)
#
# Does NOT log in (that would require an interactive TOTP code). Operators
# must additionally perform a real login from the offline kit at least
# annually — this script verifies the server-side conditions for that
# login to be possible.
#
# Run by hand quarterly, or via systemd timer monthly:
#
#   /etc/systemd/system/gitlab-break-glass-verify.timer:
#     OnCalendar=monthly
#     Persistent=true
#
#   /etc/systemd/system/gitlab-break-glass-verify.service:
#     Type=oneshot
#     ExecStart=/opt/botlab/scripts/verify-break-glass.sh recovery-XXXXXX
#
# See:
#   - DESIGN.md §5.3.3 — account model
#   - RUNBOOK-RECOVERY.md Appendix D — recovery procedure
#   - monitoring/alerts.yml — BreakGlassKitVerificationStale, BreakGlassAccountMissing

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
log()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# Textfile collector path. Override via TEXTFILE_DIR env var if your
# node_exporter is configured differently. See DESIGN.md §7.
TEXTFILE_DIR="${TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
METRIC_FILE="${TEXTFILE_DIR}/gitlab_break_glass.prom"

usage() {
    cat <<EOF
Usage: $0 <username>

  <username>: the break-glass admin username from the offline kit
              (e.g. recovery-a3f7c2)
EOF
}

if [[ $# -ne 1 ]]; then
    usage
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    err "Must be run as root (uses gitlab-rails runner)"
    exit 1
fi

USERNAME="$1"
RESULT_OK=1
NOW=$(date +%s)

if ! [[ "$USERNAME" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    err "Invalid username: '$USERNAME'"
    exit 1
fi

# ---------------------------------------------------------------------------
# Check 1: server-side account state
# ---------------------------------------------------------------------------

log "Checking server-side state of '${USERNAME}' ..."

export GL_USERNAME="$USERNAME"

CHECK_OUTPUT="$(gitlab-rails runner '
username = ENV.fetch("GL_USERNAME")
user = User.find_by(username: username)
if user.nil?
  puts "STATE=missing"
else
  puts "STATE=present"
  puts "ADMIN=#{user.admin?}"
  puts "OTP=#{user.otp_required_for_login}"
  puts "BLOCKED=#{user.blocked?}"
  puts "CONFIRMED=#{user.confirmed?}"
end
' 2>&1)"

STATE=$(grep -E '^STATE=' <<<"$CHECK_OUTPUT" | head -n1 | cut -d= -f2- || echo "error")
ADMIN=$(grep -E '^ADMIN=' <<<"$CHECK_OUTPUT" | head -n1 | cut -d= -f2- || echo "")
OTP_REQ=$(grep -E '^OTP=' <<<"$CHECK_OUTPUT" | head -n1 | cut -d= -f2- || echo "")
BLOCKED=$(grep -E '^BLOCKED=' <<<"$CHECK_OUTPUT" | head -n1 | cut -d= -f2- || echo "")
CONFIRMED=$(grep -E '^CONFIRMED=' <<<"$CHECK_OUTPUT" | head -n1 | cut -d= -f2- || echo "")

if [[ "$STATE" != "present" ]]; then
    err "Account '${USERNAME}' does NOT exist on this server"
    err "Rails output: ${CHECK_OUTPUT}"
    RESULT_OK=0
else
    log "Account exists"
    if [[ "$ADMIN"     == "true"  ]]; then log "  Administrator: yes"; else err "  Administrator: NO"; RESULT_OK=0; fi
    if [[ "$OTP_REQ"   == "true"  ]]; then log "  TOTP enabled:  yes"; else err "  TOTP enabled: NO";  RESULT_OK=0; fi
    if [[ "$BLOCKED"   == "false" ]]; then log "  Blocked:       no";  else err "  Blocked: YES";      RESULT_OK=0; fi
    if [[ "$CONFIRMED" == "true"  ]]; then log "  Confirmed:     yes"; else err "  Confirmed: NO";     RESULT_OK=0; fi
fi

# ---------------------------------------------------------------------------
# Check 2: bypass URL serves local-auth form
# ---------------------------------------------------------------------------

EXT_URL=$(grep -E "^[^#]*external_url" /etc/gitlab/gitlab.rb 2>/dev/null \
    | head -n1 | awk -F\' '{print $2}' | sed 's|/$||')
if [[ -z "$EXT_URL" ]]; then
    err "Could not parse external_url from /etc/gitlab/gitlab.rb"
    RESULT_OK=0
else
    log "Checking bypass URL: ${EXT_URL}/users/sign_in?auto_sign_in=false"

    # Probe via 127.0.0.1 with Host header to avoid DNS / external dependency
    LOCAL_HOST=$(sed -E 's|^https?://||; s|/.*$||' <<<"$EXT_URL")

    BYPASS_HTML=$(curl -sf -k -H "Host: ${LOCAL_HOST}" \
        "https://127.0.0.1/users/sign_in?auto_sign_in=false" 2>/dev/null || echo "")

    if [[ -z "$BYPASS_HTML" ]]; then
        err "Bypass URL did not respond (HTTPS to 127.0.0.1 may be blocked"
        err "or GitLab nginx not yet up). Try the URL from your laptop:"
        err "  curl -sI '${EXT_URL}/users/sign_in?auto_sign_in=false'"
        RESULT_OK=0
    elif grep -q 'name="user\[login\]"' <<<"$BYPASS_HTML" && \
         grep -q 'name="user\[password\]"' <<<"$BYPASS_HTML"; then
        log "Bypass URL serves local-auth form (username+password fields present)"
    else
        err "Bypass URL did NOT serve local-auth form."
        err "Possible causes:"
        err "  - omniauth_auto_sign_in_with_provider is forcing redirect"
        err "    despite the ?auto_sign_in=false override"
        err "  - GitLab login form HTML has changed (check this script)"
        RESULT_OK=0
    fi
fi

# ---------------------------------------------------------------------------
# Emit Prometheus textfile metrics
# ---------------------------------------------------------------------------

if [[ -d "$TEXTFILE_DIR" || $(mkdir -p "$TEXTFILE_DIR" 2>/dev/null && echo yes) == "yes" ]]; then
    {
        echo "# HELP gitlab_break_glass_account_present 1 if break-glass account exists"
        echo "# TYPE gitlab_break_glass_account_present gauge"
        echo "gitlab_break_glass_account_present $([ "$STATE" = "present" ] && echo 1 || echo 0)"
        echo "# HELP gitlab_break_glass_verification_ok 1 if last verification passed all checks"
        echo "# TYPE gitlab_break_glass_verification_ok gauge"
        echo "gitlab_break_glass_verification_ok ${RESULT_OK}"
        echo "# HELP gitlab_break_glass_kit_verified_timestamp Unix time of last successful verification"
        echo "# TYPE gitlab_break_glass_kit_verified_timestamp gauge"
        if [[ $RESULT_OK -eq 1 ]]; then
            echo "gitlab_break_glass_kit_verified_timestamp ${NOW}"
        else
            # Preserve the previous timestamp on failure so we don't reset
            # the "last good" signal. Read from the existing file if present.
            PREV=$(grep -E '^gitlab_break_glass_kit_verified_timestamp ' "$METRIC_FILE" 2>/dev/null \
                | awk '{print $2}' | head -n1)
            echo "gitlab_break_glass_kit_verified_timestamp ${PREV:-0}"
        fi
    } > "${METRIC_FILE}.tmp"
    mv "${METRIC_FILE}.tmp" "$METRIC_FILE"
    log "Metrics written to ${METRIC_FILE}"
else
    warn "Textfile collector dir ${TEXTFILE_DIR} not writable — metrics skipped"
fi

# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

unset GL_USERNAME

echo ""
if [[ $RESULT_OK -eq 1 ]]; then
    log "Break-glass verification PASSED"
    log "Quarterly verification deadline reset for $(date -d '+90 days' +%Y-%m-%d 2>/dev/null || echo '(+90 days)')"
    log "Remember: also do a real login from the offline kit at least annually."
    exit 0
else
    err "Break-glass verification FAILED — see errors above"
    err "DO NOT IGNORE. The account may be unreachable in an SSO outage."
    err "Runbook: docs/RUNBOOK-RECOVERY.md Appendix D"
    exit 1
fi
