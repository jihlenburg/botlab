#!/bin/bash
# =============================================================================
# scripts/borg-check.sh
# =============================================================================
#
# Weekly Borg repository integrity check.
#
# Runs `borg check --repository-only` against the Storage Box repo and writes
# a Prometheus textfile metric for monitoring:
#
#   gitlab_backup_integrity            1 if last check passed, 0 if failed
#   gitlab_backup_integrity_timestamp  unix time of last check
#
# Alertmanager rules in monitoring/alerts.yml consume these:
#   BorgIntegrityFail   — fires on gitlab_backup_integrity == 0
#   BorgCheckStale      — fires if the metric is absent for > 8 days
#
# Scheduling: via systemd timer at systemd/gitlab-borg-check.{service,timer}.
# Recommended cadence: weekly.
#
# Why repository-only: `borg check` with no flags also runs `--verify-data`,
# which streams every chunk of every archive across SSH. For a multi-GB
# repository that takes hours and saturates the link. `--repository-only`
# checks the repo structure and segment integrity without reading archive
# data — catches the kinds of corruption we care about (the tier that
# would defeat a restore) at single-digit minutes of runtime.
#
# Run periodically with `--verify-data` (annually?) for deeper assurance.

set -euo pipefail

CONF_FILE="/etc/gitlab-backup.conf"
TEXTFILE_DIR="${TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
METRIC_FILE="${TEXTFILE_DIR}/gitlab_borg_check.prom"
LOG_FILE="/var/log/gitlab-backup.log"

if [[ ! -f "$CONF_FILE" ]]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ERROR borg-check: $CONF_FILE not found" >>"$LOG_FILE"
    exit 1
fi
# shellcheck disable=SC1090
source "$CONF_FILE"

if [[ -z "${BORG_REPO:-}" ]]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ERROR borg-check: BORG_REPO not set in $CONF_FILE" >>"$LOG_FILE"
    exit 1
fi

# BORG_PASSPHRASE: read from Layer-2 systemd-creds (preferred), else from
# the sourced config file (legacy / pre-Layer-2). See DESIGN.md Appendix C.4.
if [[ -n "${CREDENTIALS_DIRECTORY:-}" && -f "${CREDENTIALS_DIRECTORY}/borg_passphrase" ]]; then
    BORG_PASSPHRASE=$(cat "${CREDENTIALS_DIRECTORY}/borg_passphrase")
    export BORG_PASSPHRASE
fi

NOW=$(date +%s)
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "${START_TS} borg-check: starting --repository-only" >>"$LOG_FILE"

RESULT=1
if borg check --repository-only "$BORG_REPO" >>"$LOG_FILE" 2>&1; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) borg-check: PASSED" >>"$LOG_FILE"
else
    EXIT_CODE=$?
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) borg-check: FAILED (exit $EXIT_CODE)" >>"$LOG_FILE"
    RESULT=0
fi

# Write Prometheus textfile metric atomically
mkdir -p "$TEXTFILE_DIR"
{
    echo "# HELP gitlab_backup_integrity 1 if last Borg integrity check passed"
    echo "# TYPE gitlab_backup_integrity gauge"
    echo "gitlab_backup_integrity ${RESULT}"
    echo "# HELP gitlab_backup_integrity_timestamp Unix time of last Borg integrity check"
    echo "# TYPE gitlab_backup_integrity_timestamp gauge"
    echo "gitlab_backup_integrity_timestamp ${NOW}"
} > "${METRIC_FILE}.tmp"
mv "${METRIC_FILE}.tmp" "$METRIC_FILE"

# Exit non-zero on integrity failure so systemd's OnFailure= can chain
if [[ $RESULT -eq 0 ]]; then
    exit 1
fi
