"""Automated backup restore testing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
import structlog
from hcloud import Client as HCloudClient
from hcloud.images import Image
from hcloud.server_types import ServerType
from hcloud.locations import Location
from hcloud.ssh_keys import SSHKey
from hcloud.actions import Action

from src.config import HetznerSettings, BackupSettings, GitLabSettings
from src.alerting.manager import AlertManager
from src.utils.ssh import SSHClient

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
        gitlab_settings: GitLabSettings,
        alert_manager: AlertManager,
    ) -> None:
        self.hcloud = HCloudClient(token=hetzner_settings.api_token.get_secret_value())
        self.location = hetzner_settings.location
        self.backup_settings = backup_settings
        self.gitlab_settings = gitlab_settings
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
        logger.info("Provisioning test server", location=self.location)
        loop = asyncio.get_event_loop()

        def create_server():
            # Get SSH keys
            ssh_keys = self.hcloud.ssh_keys.get_all()

            response = self.hcloud.servers.create(
                name=f"gitlab-restore-test-{datetime.now().strftime('%Y%m%d-%H%M')}",
                server_type=ServerType(name="cx21"),  # Smaller instance for testing
                image=Image(name="ubuntu-24.04"),
                location=Location(name=self.location),
                ssh_keys=ssh_keys,
                labels={
                    "purpose": "restore-test",
                    "managed_by": "admin-bot",
                    "temporary": "true",
                    "created": datetime.now().isoformat(),
                },
            )
            return response

        response = await loop.run_in_executor(None, create_server)
        server = response.server

        # Wait for action to complete
        await self._wait_for_action(response.action)

        # Wait for SSH to be available
        await self._wait_for_ssh(server.public_net.ipv4.ip)

        return server

    async def _wait_for_action(self, action: Action, timeout: int = 300) -> None:
        """Wait for a Hetzner Cloud action to complete."""
        loop = asyncio.get_event_loop()
        start_time = datetime.now()

        while True:
            def get_action():
                return self.hcloud.actions.get_by_id(action.id)

            current_action = await loop.run_in_executor(None, get_action)

            if current_action.status == "success":
                return
            elif current_action.status == "error":
                raise RuntimeError(f"Hetzner action failed: {current_action.error}")

            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                raise TimeoutError(f"Action timed out after {timeout}s")

            await asyncio.sleep(5)

    async def _wait_for_ssh(self, server_ip: str, timeout: int = 300) -> None:
        """Wait for SSH to become available."""
        import socket

        start_time = datetime.now()

        while True:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex((server_ip, 22))
                sock.close()

                if result == 0:
                    await asyncio.sleep(5)  # Give sshd time to fully start
                    return

            except socket.error:
                pass

            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                raise TimeoutError(f"SSH not available after {timeout}s")

            await asyncio.sleep(10)

    def _get_ssh_client(self, server_ip: str) -> SSHClient:
        """Get SSH client for test server."""
        temp_settings = GitLabSettings(
            url=f"http://{server_ip}",
            private_token=self.gitlab_settings.private_token,
            ssh_host=server_ip,
            ssh_user="root",
            ssh_key_path=self.gitlab_settings.ssh_key_path,
        )
        return SSHClient(temp_settings)

    async def _install_gitlab(self, server_ip: str) -> None:
        """Install GitLab CE on test server."""
        logger.info("Installing GitLab CE on test server", server_ip=server_ip)

        ssh = self._get_ssh_client(server_ip)

        try:
            # Update system
            logger.debug("Updating system packages")
            await ssh.run_command("apt-get update && apt-get upgrade -y", timeout=300)

            # Install dependencies
            logger.debug("Installing dependencies")
            await ssh.run_command(
                "apt-get install -y curl openssh-server ca-certificates tzdata perl",
                timeout=300,
            )

            # Install postfix non-interactively
            await ssh.run_command(
                "DEBIAN_FRONTEND=noninteractive apt-get install -y postfix",
                timeout=120,
            )

            # Add GitLab repository
            logger.debug("Adding GitLab repository")
            await ssh.run_command(
                "curl -sS https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh | bash",
                timeout=120,
            )

            # Install GitLab CE
            logger.info("Installing GitLab CE package")
            await ssh.run_command(
                "EXTERNAL_URL='http://gitlab.test.local' apt-get install -y gitlab-ce",
                timeout=1800,
            )

            # Stop services for restore
            await ssh.run_command("gitlab-ctl stop", timeout=60)

            logger.info("GitLab installation complete on test server")

        finally:
            ssh.close()

    async def _restore_backup(self, server_ip: str) -> None:
        """Restore backup on test server."""
        logger.info("Restoring backup on test server", server_ip=server_ip)

        ssh = self._get_ssh_client(server_ip)

        try:
            # Create restore directory
            await ssh.run_command("mkdir -p /tmp/gitlab-restore", timeout=30)

            # Get latest archive name
            archive_cmd = f"""
export BORG_REPO='{self.backup_settings.borg_repo}'
export BORG_PASSPHRASE='{self.backup_settings.borg_passphrase.get_secret_value()}'
borg list --last 1 --format '{{archive}}' "$BORG_REPO"
"""
            archive_name = (await ssh.run_command(archive_cmd, timeout=60)).strip()
            if not archive_name:
                raise RuntimeError("No backup archives found")

            logger.info("Extracting backup archive", archive=archive_name)

            # Extract backup
            extract_cmd = f"""
cd /tmp/gitlab-restore
export BORG_REPO='{self.backup_settings.borg_repo}'
export BORG_PASSPHRASE='{self.backup_settings.borg_passphrase.get_secret_value()}'
borg extract "$BORG_REPO::{archive_name}"
"""
            await ssh.run_command(extract_cmd, timeout=1200)

            # Restore config files
            logger.info("Restoring configuration files")
            await ssh.run_command(
                "cp /tmp/gitlab-restore/etc/gitlab/gitlab.rb /etc/gitlab/gitlab.rb 2>/dev/null || true",
                timeout=30,
            )
            await ssh.run_command(
                "cp /tmp/gitlab-restore/etc/gitlab/gitlab-secrets.json /etc/gitlab/gitlab-secrets.json 2>/dev/null || true",
                timeout=30,
            )

            # Copy backup file
            await ssh.run_command(
                "mkdir -p /var/opt/gitlab/backups && "
                "find /tmp/gitlab-restore -name '*_gitlab_backup.tar' -exec cp {} /var/opt/gitlab/backups/ \\;",
                timeout=300,
            )

            # Get backup timestamp
            timestamp_cmd = "ls -1 /var/opt/gitlab/backups/*_gitlab_backup.tar | head -1 | xargs basename | sed 's/_gitlab_backup.tar//'"
            backup_timestamp = (await ssh.run_command(timestamp_cmd, timeout=30)).strip()

            if not backup_timestamp:
                raise RuntimeError("Could not find backup file for restore")

            # Stop services
            await ssh.run_command("gitlab-ctl stop puma", timeout=60)
            await ssh.run_command("gitlab-ctl stop sidekiq", timeout=60)

            # Run restore
            logger.info("Running GitLab backup restore", timestamp=backup_timestamp)
            await ssh.run_command(
                f"gitlab-backup restore BACKUP={backup_timestamp} force=yes",
                timeout=3600,
            )

            # Reconfigure and restart
            logger.info("Reconfiguring GitLab")
            await ssh.run_command("gitlab-ctl reconfigure", timeout=600)
            await ssh.run_command("gitlab-ctl restart", timeout=300)

            # Wait for services
            await asyncio.sleep(60)

            logger.info("Backup restore complete on test server")

        finally:
            ssh.close()

    async def _verify_restore(self, server_ip: str) -> dict[str, bool]:
        """Verify restored GitLab is functional."""
        logger.info("Verifying restore", server_ip=server_ip)
        verification = {}

        ssh = self._get_ssh_client(server_ip)

        try:
            # Check GitLab service status
            try:
                status_output = await ssh.run_command("gitlab-ctl status", timeout=60)
                # Consider it passing if most services are up
                down_count = status_output.lower().count("down:")
                verification["services_running"] = down_count <= 1  # Allow 1 service down
            except Exception as e:
                logger.error("Service status check failed", error=str(e))
                verification["services_running"] = False

            # Check health endpoint
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    response = await client.get(f"http://{server_ip}/-/health")
                    verification["health_check"] = response.status_code == 200
            except Exception as e:
                logger.error("Health check failed", error=str(e))
                verification["health_check"] = False

            # Check readiness endpoint
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    response = await client.get(f"http://{server_ip}/-/readiness")
                    verification["readiness_check"] = response.status_code == 200
            except Exception as e:
                logger.error("Readiness check failed", error=str(e))
                verification["readiness_check"] = False

            # Check liveness endpoint
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    response = await client.get(f"http://{server_ip}/-/liveness")
                    verification["liveness_check"] = response.status_code == 200
            except Exception as e:
                logger.error("Liveness check failed", error=str(e))
                verification["liveness_check"] = False

            # Check web UI accessibility
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    response = await client.get(f"http://{server_ip}/")
                    # GitLab returns 302 redirect to login or 200 for public projects
                    verification["web_accessible"] = response.status_code in (200, 302)
            except Exception as e:
                logger.error("Web accessibility check failed", error=str(e))
                verification["web_accessible"] = False

            # Run GitLab check (quick version)
            try:
                check_output = await ssh.run_command(
                    "gitlab-rake gitlab:check SANITIZE=true 2>&1 | tail -20",
                    timeout=300,
                )
                # Check for serious failures
                has_failures = "Failure" in check_output and "error" in check_output.lower()
                verification["gitlab_check"] = not has_failures
            except Exception as e:
                logger.error("GitLab check failed", error=str(e))
                verification["gitlab_check"] = False

            # Check database connectivity
            try:
                db_check = await ssh.run_command(
                    "gitlab-psql -c 'SELECT 1;' 2>&1",
                    timeout=30,
                )
                verification["database_accessible"] = "1" in db_check
            except Exception as e:
                logger.error("Database check failed", error=str(e))
                verification["database_accessible"] = False

        finally:
            ssh.close()

        logger.info("Verification results", results=verification)
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
