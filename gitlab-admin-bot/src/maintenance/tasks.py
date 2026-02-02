"""Automated maintenance tasks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from src.alerting.manager import AlertManager
from src.utils.ssh import SSHClient

logger = structlog.get_logger(__name__)


class MaintenanceRunner:
    """Runs automated maintenance tasks."""

    def __init__(
        self,
        ssh_client: SSHClient,
        alert_manager: AlertManager,
    ) -> None:
        self.ssh = ssh_client
        self.alerts = alert_manager

    async def cleanup_old_artifacts(self, days: int = 30) -> dict[str, Any]:
        """Clean up CI artifacts older than specified days."""
        logger.info("Cleaning old artifacts", older_than_days=days)

        # GitLab CE: artifacts cleanup is configured in gitlab.rb
        # This triggers an immediate check
        cmd = "gitlab-rake gitlab:cleanup:orphan_job_artifact_files"

        try:
            output = await self.ssh.run_command(cmd, timeout=600)
            return {"success": True, "output": output[-1000:]}
        except Exception as e:
            logger.error("Artifact cleanup failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def cleanup_registry(self) -> dict[str, Any]:
        """Run container registry garbage collection."""
        logger.info("Running registry garbage collection")

        cmd = "gitlab-ctl registry-garbage-collect"

        try:
            output = await self.ssh.run_command(cmd, timeout=1800)
            return {"success": True, "output": output[-1000:]}
        except Exception as e:
            logger.error("Registry GC failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def rotate_logs(self) -> dict[str, Any]:
        """Rotate GitLab logs."""
        logger.info("Rotating logs")

        cmd = "logrotate -f /etc/logrotate.d/gitlab"

        try:
            output = await self.ssh.run_command(cmd, timeout=120)
            return {"success": True, "output": output}
        except Exception as e:
            logger.error("Log rotation failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def database_vacuum(self) -> dict[str, Any]:
        """Run PostgreSQL vacuum analyze."""
        logger.info("Running database vacuum")

        cmd = "gitlab-psql -c 'VACUUM ANALYZE;'"

        try:
            output = await self.ssh.run_command(cmd, timeout=1800)
            return {"success": True, "output": output}
        except Exception as e:
            logger.error("Database vacuum failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def check_gitlab_integrity(self) -> dict[str, Any]:
        """Run GitLab integrity check."""
        logger.info("Running GitLab integrity check")

        cmd = "gitlab-rake gitlab:check SANITIZE=true"

        try:
            output = await self.ssh.run_command(cmd, timeout=600)

            # Check for failures in output
            has_failures = "Failure" in output or "Error" in output
            if has_failures:
                await self.alerts.send_alert(
                    severity="warning",
                    title="GitLab Integrity Check Issues",
                    message="GitLab check found some issues. Review the output.",
                    details={"output": output[-2000:]},
                )

            return {
                "success": not has_failures,
                "output": output[-2000:],
            }
        except Exception as e:
            logger.error("Integrity check failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def generate_daily_report(self) -> dict[str, Any]:
        """Generate daily status report."""
        logger.info("Generating daily report")

        report = {
            "timestamp": datetime.now().isoformat(),
            "report_type": "daily",
        }

        # Get disk usage
        try:
            disk_output = await self.ssh.run_command(
                "df -h /var/opt/gitlab /var/opt/gitlab/backups 2>/dev/null || df -h /"
            )
            report["disk_usage"] = disk_output.strip()
        except Exception as e:
            report["disk_error"] = str(e)

        # Get GitLab status
        try:
            status_output = await self.ssh.run_command("gitlab-ctl status")
            report["gitlab_status"] = status_output.strip()
        except Exception as e:
            report["status_error"] = str(e)

        # Get backup info
        try:
            backup_output = await self.ssh.run_command(
                "ls -lh /var/opt/gitlab/backups/*_gitlab_backup.tar 2>/dev/null | tail -3"
            )
            report["recent_backups"] = backup_output.strip()
        except Exception as e:
            report["backup_error"] = str(e)

        # Send report as info alert
        await self.alerts.send_alert(
            severity="info",
            title="Daily GitLab Status Report",
            message=f"Daily report generated at {report['timestamp']}",
            details=report,
        )

        return report
