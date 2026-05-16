#!/bin/bash
# =============================================================================
# scripts/setup-break-glass.sh
# =============================================================================
#
# Create the GitLab break-glass local admin account programmatically.
#
# Run ON THE GITLAB SERVER as root:
#   - AFTER `gitlab-ctl reconfigure` has succeeded once
#   - BEFORE `omniauth_auto_sign_in_with_provider = 'saml'` is added
#     to /etc/gitlab/gitlab.rb (otherwise the operator has no way to
#     verify the break-glass actually works — see DEPLOY.md §5b)
#
# What this script does:
#   1. Generates a non-obvious username, an email outside Azure AD,
#      and a 32-char random password
#   2. Creates the user via `gitlab-rails runner` with admin level
#   3. Attempts to provision TOTP server-side (works on GitLab 17.x);
#      falls back to "operator enables 2FA via UI" if it can't
#   4. Prints all credentials in a single structured block for the
#      operator to copy into the offline recovery kit (template:
#      docs/OFFLINE-KIT-TEMPLATE.md)
#
# See:
#   - DESIGN.md §5.3.3 — account model
#   - DEPLOY.md §5b   — when to run this in the deploy sequence
#   - RUNBOOK-RECOVERY.md Appendix D — how to use the account

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'
log()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

if [[ $EUID -ne 0 ]]; then
    err "Must be run as root (uses gitlab-rails runner)"
    exit 1
fi

if ! command -v gitlab-rails &>/dev/null; then
    err "gitlab-rails not found — is GitLab Omnibus installed and reconfigured?"
    exit 1
fi

# Reject if SAML auto-redirect is already enabled (out-of-order risk).
# If it is, the operator cannot verify the break-glass before going live
# with auto-redirect, which defeats the whole sequencing in DEPLOY.md §5b.
if grep -qE "^[^#]*omniauth_auto_sign_in_with_provider" /etc/gitlab/gitlab.rb 2>/dev/null; then
    err "Detected omniauth_auto_sign_in_with_provider in /etc/gitlab/gitlab.rb."
    err "Comment it out, run 'gitlab-ctl reconfigure', then re-run this script."
    err "See DEPLOY.md §5b for the correct ordering."
    exit 1
fi

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

usage() {
    cat <<EOF
Usage: $0 <local-email-domain>

  <local-email-domain>: a domain that does NOT exist in your Azure AD
                        tenant. Prevents accidental SSO auto-link via
                        omniauth_auto_link_saml_user (see DESIGN.md §5.3.3).
                        A subdomain you control but don't sync to Entra
                        is ideal.

Example:
  $0 acme.local
  $0 break-glass.acme.example
EOF
}

if [[ $# -ne 1 ]]; then
    usage
    exit 1
fi

LOCAL_DOMAIN="$1"

if ! [[ "$LOCAL_DOMAIN" =~ ^[a-zA-Z0-9.-]+$ ]]; then
    err "Invalid domain: '$LOCAL_DOMAIN'"
    exit 1
fi

# ---------------------------------------------------------------------------
# Generate credentials
# ---------------------------------------------------------------------------

GL_USERNAME="recovery-$(openssl rand -hex 3)"
GL_EMAIL="break-glass-$(openssl rand -hex 4)@${LOCAL_DOMAIN}"
GL_PASSWORD="$(openssl rand -base64 24)"

log "Generated:"
echo "    Username: ${GL_USERNAME}"
echo "    Email:    ${GL_EMAIL}"
echo "    Password: (printed in the kit block below)"
echo ""

# ---------------------------------------------------------------------------
# Create account + provision TOTP
# ---------------------------------------------------------------------------
# Credentials are passed via env, not via shell interpolation into Ruby
# code, to eliminate quoting bugs. Ruby reads via ENV.fetch().

log "Creating account via gitlab-rails runner ..."

export GL_USERNAME GL_EMAIL GL_PASSWORD

RAILS_OUTPUT="$(gitlab-rails runner '
begin
  username = ENV.fetch("GL_USERNAME")
  email    = ENV.fetch("GL_EMAIL")
  password = ENV.fetch("GL_PASSWORD")

  if User.find_by(username: username)
    abort "ERROR: user #{username} already exists; re-run for a fresh username"
  end

  user = User.new(
    username:              username,
    email:                 email,
    name:                  "Break-Glass Admin",
    password:              password,
    password_confirmation: password,
    admin:                 true,
    external:              false
  )
  user.skip_confirmation!

  # Newer GitLab requires assigning a personal namespace under the
  # default organization. Older versions do not have this API.
  if user.respond_to?(:assign_personal_namespace) && defined?(Organizations::Organization)
    user.assign_personal_namespace(Organizations::Organization.default_organization)
  end

  user.save!

  # Server-side TOTP provisioning. APIs change between GitLab versions;
  # on failure, the account is still created — operator enables 2FA via
  # the UI as a fallback.
  begin
    user.otp_secret = User.generate_otp_secret
    user.otp_grace_period_started_at = nil
    user.otp_required_for_login = true
    backup_codes = user.generate_otp_backup_codes!
    user.save!

    provisioning_uri = user.otp_provisioning_uri(user.email, issuer: "GitLab ACME Corp")

    puts "---BEGIN-CREDENTIALS---"
    puts "OTP_OK=yes"
    puts "OTP_SECRET=#{user.otp_secret}"
    puts "OTP_URI=#{provisioning_uri}"
    puts "BACKUP_CODES=#{backup_codes.join(",")}"
    puts "---END-CREDENTIALS---"
  rescue => totp_err
    puts "---BEGIN-CREDENTIALS---"
    puts "OTP_OK=no"
    puts "OTP_ERR=#{totp_err.class}: #{totp_err.message}"
    puts "---END-CREDENTIALS---"
  end
rescue => e
  abort "FAILED: #{e.class}: #{e.message}"
end
' 2>&1)"

if ! grep -q -- '---BEGIN-CREDENTIALS---' <<<"$RAILS_OUTPUT"; then
    err "Account creation failed. Rails output below:"
    echo "----"
    echo "$RAILS_OUTPUT"
    echo "----"
    exit 1
fi

OTP_OK=$(grep -E '^OTP_OK=' <<<"$RAILS_OUTPUT" | head -n1 | cut -d= -f2-)
OTP_SECRET=$(grep -E '^OTP_SECRET=' <<<"$RAILS_OUTPUT" | head -n1 | cut -d= -f2- || true)
OTP_URI=$(grep -E '^OTP_URI=' <<<"$RAILS_OUTPUT" | head -n1 | cut -d= -f2- || true)
BACKUP_CODES=$(grep -E '^BACKUP_CODES=' <<<"$RAILS_OUTPUT" | head -n1 | cut -d= -f2- || true)
OTP_ERR=$(grep -E '^OTP_ERR=' <<<"$RAILS_OUTPUT" | head -n1 | cut -d= -f2- || true)

# Discover the external URL from gitlab.rb (best-effort)
EXT_URL=$(grep -E "^[^#]*external_url" /etc/gitlab/gitlab.rb 2>/dev/null \
    | head -n1 | awk -F\' '{print $2}' | sed 's|/$||')
if [[ -z "$EXT_URL" ]]; then
    EXT_URL="https://<your-gitlab-domain>"
fi
BYPASS_URL="${EXT_URL}/users/sign_in?auto_sign_in=false"

# ---------------------------------------------------------------------------
# Print the kit-ready block
# ---------------------------------------------------------------------------

cat <<EOF

====================================================================
${BOLD}BREAK-GLASS ADMIN CREATED${NC}
${BOLD}COPY EVERYTHING BELOW INTO THE OFFLINE RECOVERY KIT — NOW.${NC}
${BOLD}THIS IS THE ONLY TIME THE TOTP SECRET AND BACKUP CODES ARE${NC}
${BOLD}DISPLAYED IN PLAINTEXT.${NC}
====================================================================

Username:       ${GL_USERNAME}
Email:          ${GL_EMAIL}
Password:       ${GL_PASSWORD}
EOF

if [[ "$OTP_OK" == "yes" ]]; then
    cat <<EOF
TOTP secret:    ${OTP_SECRET}
TOTP URI:       ${OTP_URI}
Backup codes:   (each can be used ONCE; mark as used in the kit)
EOF
    IFS=',' read -ra codes_arr <<<"$BACKUP_CODES"
    for c in "${codes_arr[@]}"; do
        echo "                ${c}"
    done
else
    cat <<EOF
TOTP:           NOT PROVISIONED (rails error: ${OTP_ERR})
                Log in via the bypass URL, then:
                  Profile → Account → Two-Factor Authentication → Enable.
                Capture the secret + backup codes manually into the kit.
EOF
fi

cat <<EOF

Bypass URL:     ${BYPASS_URL}

Created:        $(date -u +%Y-%m-%dT%H:%M:%SZ)
Last verified:  (fill in after running scripts/verify-break-glass.sh)

====================================================================

EOF

warn "Before you continue the deploy:"
echo "  1. Save EVERY field above into the offline recovery kit"
echo "     (template: docs/OFFLINE-KIT-TEMPLATE.md)"
if [[ "$OTP_OK" == "yes" ]]; then
    echo "  2. Load the TOTP URI into your authenticator app (Apple Passwords,"
    echo "     1Password, Bitwarden, Aegis — see DESIGN.md §5.3.3)"
    echo "  3. Log in via the bypass URL with the password + a TOTP code"
else
    echo "  2. Log in via the bypass URL with the password (no TOTP yet)"
    echo "  3. Enable TOTP through the GitLab UI; capture seed + backup codes"
fi
echo "  4. Run: scripts/verify-break-glass.sh ${GL_USERNAME}"
echo "  5. ONLY THEN: add omniauth_auto_sign_in_with_provider = 'saml' to"
echo "     /etc/gitlab/gitlab.rb and run 'gitlab-ctl reconfigure'"
echo ""
warn "Clear your terminal scrollback before disconnecting:"
echo "  history -c && clear"
echo ""

unset GL_USERNAME GL_EMAIL GL_PASSWORD
