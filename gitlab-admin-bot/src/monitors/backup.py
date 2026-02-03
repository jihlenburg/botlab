"""Backup monitoring."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import structlog
from prometheus_client import Gauge

from src.alerting.manager import AlertManager
from src.config import BackupSettings
from src.monitors.base import CHECK_DURATION, BaseMonitor, CheckResult, Status
from src.utils.ssh import SSHClient

logger = structlog.get_logger(__name__)

# Prometheus metrics
BACKUP_AGE_HOURS = Gauge("gitlab_backup_age_hours", "Age of most recent backup in hours")
BACKUP_SIZE_GB = Gauge("gitlab_backup_size_gb", "Size of most recent backup in GB")
BACKUP_SUCCESS = Gauge("gitlab_backup_success", "Last backup was successful")
BACKUP_INTEGRITY = Gauge(
    "gitlab_backup_integrity", "Borg repository integrity (1=ok, 0=fail, -1=not checked)"
)


class BackupMonitor(BaseMonitor):
    """Monitor GitLab backup status."""

    name = "backup"

    def __init__(
        self,
        ssh_client: SSHClient,
        alert_manager: AlertManager,
        settings: BackupSettings,
    ) -> None:
        super().__init__()
        self.ssh = ssh_client
        self.alerts = alert_manager
        self.settings = settings
        self._last_status: dict[str, Any] = {}

    async def check(self) -> CheckResult:
        """Check backup status."""
        start_time = time.time()
        issues: list[str] = []
        details: dict[str, Any] = {}

        try:
            # Check local backup files
            local_backup = await self._check_local_backup()
            details["local"] = local_backup

            if local_backup.get("age_hours", 999) > self.settings.max_backup_age_hours:
                issues.append(
                    f"Local backup is {local_backup['age_hours']:.1f} hours old "
                    f"(threshold: {self.settings.max_backup_age_hours}h)"
                )

            # Update Prometheus metrics
            BACKUP_AGE_HOURS.set(local_backup.get("age_hours", -1))
            BACKUP_SIZE_GB.set(local_backup.get("size_gb", 0))

            # Check Borg repository (if configured)
            if self.settings.borg_repo:
                borg_status = await self._check_borg_backup()
                details["borg"] = borg_status

                if borg_status.get("error"):
                    issues.append(f"Borg check failed: {borg_status['error']}")
                elif "age_hours" in borg_status:
                    borg_age = borg_status["age_hours"]
                    if borg_age > self.settings.max_backup_age_hours * 2:
                        issues.append(f"Borg backup is {borg_age:.1f} hours old")

            # Check backup log for recent errors
            log_status = await self._check_backup_log()
            details["log"] = log_status

            if log_status.get("recent_errors"):
                issues.append(f"Backup log errors: {log_status['recent_errors']}")

        except Exception as e:
            logger.error("Backup check failed", error=str(e))
            issues.append(f"Backup check error: {e}")
            details["error"] = str(e)

        # Calculate duration
        duration = time.time() - start_time
        CHECK_DURATION.labels(monitor=self.name).set(duration)

        # Determine status
        if issues:
            status = Status.CRITICAL
            message = "; ".join(issues)
            BACKUP_SUCCESS.set(0)

            await self.alerts.send_alert(
                severity="critical",
                title="GitLab Backup Alert",
                message=message,
                details=details,
            )
        else:
            status = Status.OK
            message = f"Backups healthy (local: {local_backup.get('age_hours', '?'):.1f}h old)"
            BACKUP_SUCCESS.set(1)

        result = CheckResult(status=status, message=message, details=details)
        self.record_result(result)
        self._last_status = details

        return result

    async def _check_local_backup(self) -> dict[str, Any]:
        """Check local backup files."""
        backup_path = self.settings.local_backup_path

        # Find most recent backup file
        cmd = f"ls -lt {backup_path}/*_gitlab_backup.tar 2>/dev/null | head -1"
        output = await self.ssh.run_command(cmd)

        if not output.strip():
            return {"exists": False, "error": "No backup files found"}

        # Parse ls output
        # Format: -rw------- 1 root root 1234567890 Jan  1 12:00 filename
        parts = output.strip().split()
        if len(parts) < 9:
            return {"exists": False, "error": f"Cannot parse: {output}"}

        filename = parts[-1]
        size_bytes = int(parts[4])
        size_gb = size_bytes / (1024**3)

        # Get file modification time
        cmd = f"stat -c %Y {filename}"
        mtime_output = await self.ssh.run_command(cmd)
        mtime = int(mtime_output.strip())
        mtime_dt = datetime.fromtimestamp(mtime)
        age = datetime.now() - mtime_dt
        age_hours = age.total_seconds() / 3600

        return {
            "exists": True,
            "filename": filename,
            "size_gb": round(size_gb, 2),
            "timestamp": mtime_dt.isoformat(),
            "age_hours": round(age_hours, 2),
        }

    async def _check_borg_backup(self) -> dict[str, Any]:
        """Check Borg backup repository."""
        try:
            # List most recent backup
            cmd = (
                "source /etc/gitlab-backup.conf && "
                "borg list --last 1 --format '{archive} {time}' $BORG_REPO 2>&1"
            )
            output = await self.ssh.run_command(cmd)

            if "error" in output.lower() or "warning" in output.lower():
                return {"error": output.strip()}

            # Parse output
            parts = output.strip().split()
            if len(parts) >= 2:
                archive_name = parts[0]
                # Time format varies, try to parse
                time_str = " ".join(parts[1:])

                return {
                    "archive": archive_name,
                    "timestamp": time_str,
                    "accessible": True,
                }

            return {"accessible": True, "raw": output.strip()}

        except Exception as e:
            return {"error": str(e)}

    async def _check_backup_log(self) -> dict[str, Any]:
        """Check backup log for recent errors."""
        cmd = "tail -100 /var/log/gitlab-backup.log 2>/dev/null | grep -i 'error\\|fail' | tail -5"
        output = await self.ssh.run_command(cmd)

        errors = output.strip().split("\n") if output.strip() else []

        return {
            "recent_errors": errors if errors and errors[0] else None,
            "error_count": len([e for e in errors if e]),
        }

    async def get_status(self) -> dict[str, Any]:
        """Get current backup status."""
        return {
            "last_check": self._last_result.timestamp.isoformat() if self._last_result else None,
            "status": self._last_result.status.value if self._last_result else "unknown",
            **self._last_status,
        }

    async def verify_integrity(self) -> dict[str, Any]:
        """Verify Borg repository integrity.

        Runs ``borg check --repository-only`` which validates the repository
        structure without reading every archive.  This is slow (~minutes) so
        it should be called weekly or on-demand, **not** on every hourly check.
        """
        if not self.settings.borg_repo:
            BACKUP_INTEGRITY.set(-1)
            return {"skipped": True, "reason": "No Borg repo configured"}

        logger.info("Starting Borg integrity verification")

        try:
            # borg check produces no output on success; any output indicates a problem.
            # We merge stderr into stdout (2>&1) and use the exit code via a wrapper:
            # exit code 0 → "BORG_CHECK_OK", non-zero → error output.
            cmd = (
                "source /etc/gitlab-backup.conf && "
                "borg check --repository-only $BORG_REPO 2>&1 && echo BORG_CHECK_OK"
            )
            output = await self.ssh.run_command(cmd, timeout=1800)

            passed = "BORG_CHECK_OK" in output

            BACKUP_INTEGRITY.set(1 if passed else 0)

            if not passed:
                await self.alerts.send_alert(
                    severity="critical",
                    title="Borg Repository Integrity Check Failed",
                    message=f"borg check reported issues: {output[-500:]}",
                    details={"output": output[-2000:]},
                )

            logger.info("Borg integrity check completed", passed=passed)
            return {"passed": passed, "output": output[-1000:]}

        except Exception as e:
            BACKUP_INTEGRITY.set(0)
            logger.error("Borg integrity check failed", error=str(e))
            await self.alerts.send_alert(
                severity="critical",
                title="Borg Integrity Check Error",
                message=f"Failed to run borg check: {e}",
            )
            return {"passed": False, "error": str(e)}

    async def trigger_backup(self) -> dict[str, Any]:
        """Trigger an immediate backup."""
        logger.info("Triggering immediate backup")

        try:
            cmd = "gitlab-backup create STRATEGY=copy SKIP=artifacts,lfs"
            output = await self.ssh.run_command(cmd, timeout=3600)

            return {
                "success": "error" not in output.lower(),
                "output": output[-1000:],  # Last 1000 chars
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
