#!/bin/bash
# =============================================================================
# scripts/restore-test.sh
# =============================================================================
#
# Weekly automated restore test. Per DEPLOY.md §8: "the single most important
# thing in the entire deployment. Backups you haven't tested are aspirations,
# not insurance." This script makes that single most important thing actually
# happen.
#
# Provisions an ephemeral Hetzner Cloud CX21 in a different network, installs
# the same pinned GitLab CE version, restores the latest Borg archive, runs
# `gitlab-rake gitlab:check`, then destroys the VM. Writes a Prometheus
# textfile metric:
#
#   gitlab_restore_test_success   1 if restore + check passed, 0 if failed
#   gitlab_restore_test_timestamp unix time of the test
#   gitlab_restore_test_duration_seconds wall-clock time of the test
#
# Alertmanager rules in monitoring/alerts.yml consume these:
#   RestoreTestFail   — fires on gitlab_restore_test_success == 0
#   RestoreTestStale  — fires if metric is absent for > 8 days
#
# Scheduling: via systemd timer at systemd/gitlab-restore-test.{service,timer}.
# Recommended cadence: weekly (Sunday early morning when CI/dev traffic is low).
#
# Cost: ~0.10 EUR per run (CX21 hourly + ephemeral IPv4 for ~30-90 min).
# Roughly 0.50 EUR/month for weekly runs.
#
# Requirements on the runner (the GitLab server):
#   - hcloud CLI installed and configured (token at /etc/hcloud-token,
#     mode 0600 root)
#   - SSH key whose public half is in the project (allows ssh into the
#     ephemeral VM); private half at /root/.ssh/restore_test_key
#   - jq for parsing hcloud JSON output
#   - The same Borg credentials the hourly backup uses (via systemd-creds
#     or /etc/gitlab-backup.conf)
#
# Hard cap: this script will hcloud-destroy the ephemeral VM no matter what,
# in the trap. Cost-runaway is the worst failure mode for a recurring job
# that provisions cloud resources; the trap is the safety net.

set -euo pipefail

CONF_FILE="/etc/gitlab-backup.conf"
TEXTFILE_DIR="${TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
METRIC_FILE="${TEXTFILE_DIR}/gitlab_restore_test.prom"
LOG_FILE="/var/log/gitlab-restore-test.log"

HCLOUD_TOKEN_FILE="${HCLOUD_TOKEN_FILE:-/etc/hcloud-token}"
SSH_KEY="${SSH_KEY:-/root/.ssh/restore_test_key}"
SSH_KEY_NAME="${SSH_KEY_NAME:-restore-test-key}"  # name as registered in Hetzner Cloud
GITLAB_VERSION="${GITLAB_VERSION:-17.10.0-ce.0}"
SERVER_TYPE="${SERVER_TYPE:-cx21}"
LOCATION="${LOCATION:-hel1}"
IMAGE="${IMAGE:-ubuntu-24.04}"

NOW=$(date +%s)
RUN_ID="restore-test-$(date -u +%Y%m%d-%H%M%S)"
SERVER_NAME="$RUN_ID"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $RUN_ID $1" | tee -a "$LOG_FILE"; }

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

for cmd in hcloud jq ssh scp curl; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        log "ERROR preflight: missing required command '$cmd'"
        exit 2
    fi
done

if [[ ! -f "$HCLOUD_TOKEN_FILE" ]]; then
    log "ERROR preflight: $HCLOUD_TOKEN_FILE not found"
    exit 2
fi
export HCLOUD_TOKEN
HCLOUD_TOKEN="$(cat "$HCLOUD_TOKEN_FILE")"

if [[ ! -f "$CONF_FILE" ]]; then
    log "ERROR preflight: $CONF_FILE not found"
    exit 2
fi
# shellcheck disable=SC1090
source "$CONF_FILE"

# Layer-2 systemd-creds for Borg passphrase (preferred, see DESIGN.md C.4)
if [[ -n "${CREDENTIALS_DIRECTORY:-}" && -f "${CREDENTIALS_DIRECTORY}/borg_passphrase" ]]; then
    BORG_PASSPHRASE=$(cat "${CREDENTIALS_DIRECTORY}/borg_passphrase")
    export BORG_PASSPHRASE
fi

if [[ ! -f "$SSH_KEY" ]]; then
    log "ERROR preflight: SSH key $SSH_KEY not found"
    exit 2
fi

# ---------------------------------------------------------------------------
# Cleanup trap — fires on ANY exit including kill/crash. Cost-safety.
# ---------------------------------------------------------------------------

SERVER_ID=""
cleanup() {
    local rc=$?
    if [[ -n "$SERVER_ID" ]]; then
        log "cleanup: destroying server $SERVER_NAME (id $SERVER_ID)"
        if ! hcloud server delete "$SERVER_ID" >>"$LOG_FILE" 2>&1; then
            log "WARN cleanup: server delete failed; check Hetzner console manually"
        fi
    fi
    return $rc
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# 1. Identify the latest Borg archive
# ---------------------------------------------------------------------------

log "starting restore test"
START=$(date +%s)

LATEST_ARCHIVE=$(borg list --short "$BORG_REPO" 2>>"$LOG_FILE" | tail -n 1 || true)
if [[ -z "$LATEST_ARCHIVE" ]]; then
    log "ERROR borg list returned no archives — aborting"
    exit 1
fi
log "will restore from archive: $LATEST_ARCHIVE"

# ---------------------------------------------------------------------------
# 2. Provision ephemeral server
# ---------------------------------------------------------------------------

log "provisioning ephemeral server $SERVER_NAME ($SERVER_TYPE, $LOCATION)"
SERVER_JSON=$(hcloud server create \
    --name "$SERVER_NAME" \
    --type "$SERVER_TYPE" \
    --image "$IMAGE" \
    --location "$LOCATION" \
    --ssh-key "$SSH_KEY_NAME" \
    --label purpose=restore-test \
    --label "run-id=$RUN_ID" \
    --output json 2>>"$LOG_FILE")

SERVER_ID=$(echo "$SERVER_JSON" | jq -r '.server.id')
SERVER_IP=$(echo "$SERVER_JSON" | jq -r '.server.public_net.ipv4.ip')
log "server up: id=$SERVER_ID ip=$SERVER_IP"

# Wait for SSH to be ready
log "waiting for SSH (up to 5 min) ..."
for i in $(seq 1 30); do
    if ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new \
       -o ConnectTimeout=5 -o BatchMode=yes \
       "root@$SERVER_IP" "echo ssh-ready" >/dev/null 2>&1; then
        log "SSH ready after $((i * 10))s"
        break
    fi
    sleep 10
    if [[ $i -eq 30 ]]; then
        log "ERROR ssh never became ready"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# 3. Install pinned GitLab CE on ephemeral
# ---------------------------------------------------------------------------

log "installing gitlab-ce=$GITLAB_VERSION on ephemeral"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "root@$SERVER_IP" \
    "GITLAB_VERSION='$GITLAB_VERSION' bash -s" <<'REMOTE_INSTALL' >>"$LOG_FILE" 2>&1
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y curl openssh-server ca-certificates tzdata perl postfix borgbackup jq
curl -fsS https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh | bash
EXTERNAL_URL="http://localhost" apt-get install -y "gitlab-ce=${GITLAB_VERSION}"
apt-mark hold gitlab-ce
REMOTE_INSTALL

# ---------------------------------------------------------------------------
# 4. Restore from Borg (extract archive, push backup tar to ephemeral, restore)
# ---------------------------------------------------------------------------

log "extracting latest backup tar from Borg"
EXTRACT_DIR=$(mktemp -d)
# shellcheck disable=SC2064  # we want EXTRACT_DIR expanded now
trap "rm -rf '$EXTRACT_DIR'; cleanup" EXIT INT TERM

(
    cd "$EXTRACT_DIR"
    borg extract "${BORG_REPO}::${LATEST_ARCHIVE}" 'var/opt/gitlab/backups/*_gitlab_backup.tar' \
        >>"$LOG_FILE" 2>&1
)
BACKUP_TAR=$(find "$EXTRACT_DIR" -name '*_gitlab_backup.tar' | head -n1)
if [[ -z "$BACKUP_TAR" ]]; then
    log "ERROR no _gitlab_backup.tar in archive $LATEST_ARCHIVE"
    exit 1
fi
log "extracted backup tar: $(basename "$BACKUP_TAR") ($(du -h "$BACKUP_TAR" | cut -f1))"

# Also pull gitlab-secrets.json from the archive — required for restore
(
    cd "$EXTRACT_DIR"
    borg extract "${BORG_REPO}::${LATEST_ARCHIVE}" 'etc/gitlab/gitlab-secrets.json' \
        >>"$LOG_FILE" 2>&1
)
SECRETS_JSON="$EXTRACT_DIR/etc/gitlab/gitlab-secrets.json"

log "uploading to ephemeral"
scp -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new \
    "$BACKUP_TAR" "root@$SERVER_IP:/var/opt/gitlab/backups/" >>"$LOG_FILE" 2>&1
scp -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new \
    "$SECRETS_JSON" "root@$SERVER_IP:/etc/gitlab/gitlab-secrets.json" >>"$LOG_FILE" 2>&1

log "running gitlab-backup restore"
BACKUP_BASENAME=$(basename "$BACKUP_TAR" | sed 's|_gitlab_backup\.tar$||')
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "root@$SERVER_IP" \
    "BACKUP='$BACKUP_BASENAME' bash -s" <<'REMOTE_RESTORE' >>"$LOG_FILE" 2>&1
set -euo pipefail
chown git:git /var/opt/gitlab/backups/*_gitlab_backup.tar
chmod 600 /etc/gitlab/gitlab-secrets.json
gitlab-ctl reconfigure
gitlab-ctl stop puma
gitlab-ctl stop sidekiq
gitlab-backup restore "BACKUP=${BACKUP}" force=yes
gitlab-ctl reconfigure
gitlab-ctl start
REMOTE_RESTORE

# ---------------------------------------------------------------------------
# 5. Verify
# ---------------------------------------------------------------------------

log "verifying restored instance"
RESULT=1
if ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "root@$SERVER_IP" \
    "gitlab-rake gitlab:check SANITIZE=true && curl -fsS http://localhost/-/health" \
    >>"$LOG_FILE" 2>&1; then
    log "VERIFY PASSED"
else
    log "VERIFY FAILED"
    RESULT=0
fi

# ---------------------------------------------------------------------------
# 6. Emit metrics. Server destruction handled by the trap.
# ---------------------------------------------------------------------------

END=$(date +%s)
DURATION=$((END - START))

mkdir -p "$TEXTFILE_DIR"
{
    echo "# HELP gitlab_restore_test_success 1 if weekly restore test succeeded"
    echo "# TYPE gitlab_restore_test_success gauge"
    echo "gitlab_restore_test_success ${RESULT}"
    echo "# HELP gitlab_restore_test_timestamp Unix time of last restore test"
    echo "# TYPE gitlab_restore_test_timestamp gauge"
    echo "gitlab_restore_test_timestamp ${NOW}"
    echo "# HELP gitlab_restore_test_duration_seconds Wall-clock time of last restore test"
    echo "# TYPE gitlab_restore_test_duration_seconds gauge"
    echo "gitlab_restore_test_duration_seconds ${DURATION}"
} > "${METRIC_FILE}.tmp"
mv "${METRIC_FILE}.tmp" "$METRIC_FILE"

log "metrics written; result=$RESULT duration=${DURATION}s"

if [[ $RESULT -eq 0 ]]; then
    exit 1
fi
