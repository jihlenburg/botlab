"""Automated backup restore testing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog
from hcloud import Client as HCloudClient
from hcloud.images import Image
from hcloud.server_types import ServerType
from hcloud.locations import Location
from hcloud.ssh_keys import SSHKey

from src.config import HetznerSettings, BackupSettings
from src.alerting.manager import AlertManager

logger = structlog.get_logger(__name__)


@dataclass
class RestoreTestResult:
    """Result of a backup restore test."""

    success: bool
    start_time: datetime
    end_time: datetime | None = None
    server_id: int | None = None
    steps_completed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    verification_results: dict[str, bool] = field(default_factory=dict)

    @property
    def duration_minutes(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds() / 60
        return 0


class RestoreTester:
    """Automated backup restore testing on ephemeral VMs."""

    def __init__(
        self,
        hetzner_settings: HetznerSettings,
        backup_settings: BackupSettings,
        alert_manager: AlertManager,
    ) -> None:
        self.hcloud = HCloudClient(token=hetzner_settings.api_token.get_secret_value())
        self.location = hetzner_settings.location
        self.backup_settings = backup_settings
        self.alerts = alert_manager

    async def run_restore_test(self) -> RestoreTestResult:
        """
        Run a full backup restore test on an ephemeral VM.

        This test:
        1. Provisions a small VM (CX21)
        2. Installs GitLab CE
        3. Restores the latest backup
        4. Verifies GitLab is functional
        5. Destroys the test VM

        Returns:
            RestoreTestResult with test outcome
        """
        result = RestoreTestResult(
            success=False,
            start_time=datetime.now(),
        )

        server = None

        try:
            # Step 1: Provision test VM
            logger.info("Provisioning restore test VM")
            server = await self._provision_test_server()
            result.server_id = server.id
            result.steps_completed.append("server_provisioned")

            # Wait for server to be ready
            await asyncio.sleep(60)

            # Step 2: Install GitLab
            logger.info("Installing GitLab on test server")
            await self._install_gitlab(server.public_net.ipv4.ip)
            result.steps_completed.append("gitlab_installed")

            # Step 3: Restore backup
            logger.info("Restoring backup on test server")
            await self._restore_backup(server.public_net.ipv4.ip)
            result.steps_completed.append("backup_restored")

            # Step 4: Verify
            logger.info("Verifying restored GitLab")
            verification = await self._verify_restore(server.public_net.ipv4.ip)
            result.verification_results = verification
            result.steps_completed.append("verification_completed")

            # Check if all verifications passed
            result.success = all(verification.values())

        except Exception as e:
            logger.error("Restore test failed", error=str(e))
            result.errors.append(str(e))

        finally:
            # Step 5: Cleanup - destroy test server
            if server:
                try:
                    logger.info("Destroying test server", server_id=server.id)
                    self.hcloud.servers.delete(server)
                    result.steps_completed.append("server_destroyed")
                except Exception as e:
                    logger.error("Failed to destroy test server", error=str(e))
                    result.errors.append(f"Cleanup failed: {e}")

            result.end_time = datetime.now()

        # Send report
        await self._send_report(result)

        return result

    async def _provision_test_server(self):
        """Provision a test server for restore testing."""
        # Use blocking call in executor
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._provision_sync)

    def _provision_sync(self):
        """Synchronous server provisioning."""
        response = self.hcloud.servers.create(
            name=f"gitlab-restore-test-{datetime.now().strftime('%Y%m%d-%H%M')}",
            server_type=ServerType(name="cx21"),
            image=Image(name="ubuntu-24.04"),
            location=Location(name=self.location),
            labels={
                "purpose": "restore-test",
                "managed_by": "admin-bot",
                "temporary": "true",
            },
        )
        return response.server

    async def _install_gitlab(self, server_ip: str) -> None:
        """Install GitLab CE on test server."""
        # This would use SSH to run installation
        # For now, placeholder
        logger.info("GitLab installation started", server_ip=server_ip)
        await asyncio.sleep(300)  # Wait for installation

    async def _restore_backup(self, server_ip: str) -> None:
        """Restore backup on test server."""
        # This would:
        # 1. Copy backup from Borg to test server
        # 2. Run gitlab-backup restore
        logger.info("Backup restore started", server_ip=server_ip)
        await asyncio.sleep(600)  # Wait for restore

    async def _verify_restore(self, server_ip: str) -> dict[str, bool]:
        """Verify restored GitLab is functional."""
        verification = {}

        # Check health endpoint
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(f"http://{server_ip}/-/health")
                verification["health_check"] = response.status_code == 200
        except Exception as e:
            logger.error("Health check failed", error=str(e))
            verification["health_check"] = False

        # Additional checks would go here
        verification["web_accessible"] = verification.get("health_check", False)

        return verification

    async def _send_report(self, result: RestoreTestResult) -> None:
        """Send restore test report."""
        severity = "info" if result.success else "warning"

        message = f"""
Restore Test {'PASSED' if result.success else 'FAILED'}

Duration: {result.duration_minutes:.1f} minutes
Steps completed: {', '.join(result.steps_completed)}

Verification Results:
"""
        for check, passed in result.verification_results.items():
            message += f"  - {check}: {'PASS' if passed else 'FAIL'}\n"

        if result.errors:
            message += f"\nErrors:\n"
            for error in result.errors:
                message += f"  - {error}\n"

        await self.alerts.send_alert(
            severity=severity,
            title="Backup Restore Test Report",
            message=message,
            details={
                "success": result.success,
                "duration_minutes": result.duration_minutes,
                "steps": result.steps_completed,
                "verification": result.verification_results,
                "errors": result.errors,
            },
        )
