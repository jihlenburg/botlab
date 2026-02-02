"""Disaster recovery automation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import structlog
from hcloud import Client as HCloudClient
from hcloud.images import Image
from hcloud.server_types import ServerType
from hcloud.locations import Location
from hcloud.volumes import Volume
from hcloud.networks import Network
from hcloud.actions import Action

from src.config import HetznerSettings, BackupSettings, GitLabSettings
from src.alerting.manager import AlertManager
from src.utils.ssh import SSHClient

logger = structlog.get_logger(__name__)


class RecoveryStep(str, Enum):
    """Recovery procedure steps."""

    PROVISION_SERVER = "provision_server"
    ATTACH_VOLUMES = "attach_volumes"
    INSTALL_GITLAB = "install_gitlab"
    RESTORE_CONFIG = "restore_config"
    RESTORE_BACKUP = "restore_backup"
    RECONFIGURE = "reconfigure"
    VERIFY = "verify"
    UPDATE_DNS = "update_dns"


@dataclass
class RecoveryState:
    """State of a recovery operation."""

    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    current_step: RecoveryStep | None = None
    completed_steps: list[RecoveryStep] = field(default_factory=list)
    failed_step: RecoveryStep | None = None
    error: str | None = None
    new_server_id: int | None = None
    new_server_ip: str | None = None

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None

    @property
    def duration_minutes(self) -> float:
        end = self.completed_at or datetime.now()
        return (end - self.started_at).total_seconds() / 60


class RecoveryManager:
    """
    Manages disaster recovery procedures.

    This provides semi-automated recovery for GitLab when the primary server fails.
    Human approval is required at key steps for safety.
    """

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
        self._current_recovery: RecoveryState | None = None
        self._ssh_client: SSHClient | None = None

    async def initiate_recovery(
        self,
        reason: str,
        auto_approve: bool = False,
    ) -> RecoveryState:
        """
        Initiate disaster recovery procedure.

        Args:
            reason: Reason for initiating recovery
            auto_approve: If True, proceed without human approval (use with caution)

        Returns:
            RecoveryState tracking the recovery progress
        """
        if self._current_recovery and not self._current_recovery.is_complete:
            raise RuntimeError("Recovery already in progress")

        state = RecoveryState()
        self._current_recovery = state

        logger.warning(
            "DISASTER RECOVERY INITIATED",
            reason=reason,
            auto_approve=auto_approve,
        )

        # Alert admins
        await self.alerts.send_alert(
            severity="critical",
            title="Disaster Recovery Initiated",
            message=f"Recovery procedure started.\nReason: {reason}",
        )

        if not auto_approve:
            # In production, this would wait for human approval
            logger.info("Waiting for human approval to proceed...")
            await self.alerts.send_alert(
                severity="critical",
                title="Action Required: Approve Recovery",
                message="Please approve the disaster recovery procedure to continue.",
            )
            # Would wait for approval via API endpoint
            return state

        try:
            # Step 1: Provision new server
            state.current_step = RecoveryStep.PROVISION_SERVER
            server = await self._provision_recovery_server()
            state.new_server_id = server.id
            state.new_server_ip = server.public_net.ipv4.ip
            state.completed_steps.append(RecoveryStep.PROVISION_SERVER)

            # Step 2: Attach volumes (if available)
            state.current_step = RecoveryStep.ATTACH_VOLUMES
            await self._attach_volumes(server)
            state.completed_steps.append(RecoveryStep.ATTACH_VOLUMES)

            # Step 3: Install GitLab
            state.current_step = RecoveryStep.INSTALL_GITLAB
            await self._install_gitlab(state.new_server_ip)
            state.completed_steps.append(RecoveryStep.INSTALL_GITLAB)

            # Step 4: Restore config
            state.current_step = RecoveryStep.RESTORE_CONFIG
            await self._restore_config(state.new_server_ip)
            state.completed_steps.append(RecoveryStep.RESTORE_CONFIG)

            # Step 5: Restore backup
            state.current_step = RecoveryStep.RESTORE_BACKUP
            await self._restore_backup(state.new_server_ip)
            state.completed_steps.append(RecoveryStep.RESTORE_BACKUP)

            # Step 6: Reconfigure
            state.current_step = RecoveryStep.RECONFIGURE
            await self._reconfigure_gitlab(state.new_server_ip)
            state.completed_steps.append(RecoveryStep.RECONFIGURE)

            # Step 7: Verify
            state.current_step = RecoveryStep.VERIFY
            await self._verify_recovery(state.new_server_ip)
            state.completed_steps.append(RecoveryStep.VERIFY)

            # Step 8: DNS update (manual)
            state.current_step = RecoveryStep.UPDATE_DNS
            await self.alerts.send_alert(
                severity="warning",
                title="Action Required: Update DNS",
                message=f"Update DNS to point to new server IP: {state.new_server_ip}",
            )
            state.completed_steps.append(RecoveryStep.UPDATE_DNS)

            state.completed_at = datetime.now()

            # Success alert
            await self.alerts.send_alert(
                severity="info",
                title="Disaster Recovery Complete",
                message=f"""
Recovery completed successfully in {state.duration_minutes:.1f} minutes.

New server IP: {state.new_server_ip}
New server ID: {state.new_server_id}

Please verify and update DNS records.
""",
            )

        except Exception as e:
            state.failed_step = state.current_step
            state.error = str(e)
            state.completed_at = datetime.now()

            logger.error(
                "Recovery failed",
                step=state.current_step,
                error=str(e),
            )

            await self.alerts.send_alert(
                severity="critical",
                title="Disaster Recovery FAILED",
                message=f"Recovery failed at step: {state.current_step}\nError: {e}",
            )

        return state

    async def _provision_recovery_server(self):
        """Provision a new GitLab server."""
        logger.info("Provisioning recovery server", location=self.location)
        loop = asyncio.get_event_loop()

        def create_server():
            # Get SSH keys for access
            ssh_keys = self.hcloud.ssh_keys.get_all()

            response = self.hcloud.servers.create(
                name=f"gitlab-recovery-{datetime.now().strftime('%Y%m%d-%H%M')}",
                server_type=ServerType(name="cpx31"),  # Match original spec: 4 vCPU, 16GB RAM
                image=Image(name="ubuntu-24.04"),
                location=Location(name=self.location),
                ssh_keys=ssh_keys,
                labels={
                    "purpose": "gitlab-recovery",
                    "managed_by": "admin-bot",
                    "created": datetime.now().isoformat(),
                },
            )
            return response

        response = await loop.run_in_executor(None, create_server)
        server = response.server

        # Wait for the server action to complete
        await self._wait_for_action(response.action)

        # Wait for SSH to be ready
        logger.info("Waiting for server to be ready", server_id=server.id)
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
                logger.debug("Action completed", action_id=action.id)
                return
            elif current_action.status == "error":
                raise RuntimeError(f"Hetzner action failed: {current_action.error}")

            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                raise TimeoutError(f"Action timed out after {timeout}s")

            await asyncio.sleep(5)

    async def _wait_for_ssh(self, server_ip: str, timeout: int = 300) -> None:
        """Wait for SSH to become available on the server."""
        import socket

        start_time = datetime.now()

        while True:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex((server_ip, 22))
                sock.close()

                if result == 0:
                    logger.debug("SSH is ready", server_ip=server_ip)
                    # Give sshd a moment to fully initialize
                    await asyncio.sleep(5)
                    return

            except socket.error:
                pass

            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                raise TimeoutError(f"SSH not available after {timeout}s")

            await asyncio.sleep(10)

    async def _attach_volumes(self, server) -> None:
        """Attach existing volumes to new server."""
        logger.info("Checking for existing volumes", server_id=server.id)
        loop = asyncio.get_event_loop()

        def get_volumes():
            return self.hcloud.volumes.get_all(
                label_selector="purpose=gitlab-data"
            )

        volumes = await loop.run_in_executor(None, get_volumes)

        if not volumes:
            logger.info("No existing volumes found, will use fresh installation")
            return

        for volume in volumes:
            logger.info(
                "Found volume",
                volume_id=volume.id,
                volume_name=volume.name,
                current_server=volume.server.id if volume.server else None,
            )

            # Detach from old server if attached
            if volume.server:
                logger.warning(
                    "Volume attached to another server - detaching",
                    volume_id=volume.id,
                    old_server_id=volume.server.id,
                )

                def detach():
                    return self.hcloud.volumes.detach(volume)

                action = await loop.run_in_executor(None, detach)
                await self._wait_for_action(action)

            # Attach to recovery server
            logger.info("Attaching volume to recovery server", volume_id=volume.id)

            def attach():
                return self.hcloud.volumes.attach(volume, server)

            action = await loop.run_in_executor(None, attach)
            await self._wait_for_action(action)

        logger.info("Volume attachment complete")

    def _get_ssh_client(self, server_ip: str) -> SSHClient:
        """Get an SSH client for the recovery server."""
        # Create a temporary GitLabSettings for SSH access
        temp_settings = GitLabSettings(
            url=f"http://{server_ip}",
            private_token=self.gitlab_settings.private_token,
            ssh_host=server_ip,
            ssh_user="root",  # Initial access as root
            ssh_key_path=self.gitlab_settings.ssh_key_path,
        )
        return SSHClient(temp_settings)

    async def _install_gitlab(self, server_ip: str) -> None:
        """Install GitLab CE on new server."""
        logger.info("Installing GitLab CE", server_ip=server_ip)

        ssh = self._get_ssh_client(server_ip)

        try:
            # Update system
            logger.info("Updating system packages")
            await ssh.run_command("apt-get update && apt-get upgrade -y", timeout=300)

            # Install dependencies
            logger.info("Installing dependencies")
            await ssh.run_command(
                "apt-get install -y curl openssh-server ca-certificates tzdata perl",
                timeout=300,
            )

            # Install postfix for email (non-interactive)
            await ssh.run_command(
                "DEBIAN_FRONTEND=noninteractive apt-get install -y postfix",
                timeout=120,
            )

            # Add GitLab repository
            logger.info("Adding GitLab repository")
            await ssh.run_command(
                "curl -sS https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh | bash",
                timeout=120,
            )

            # Install GitLab CE
            logger.info("Installing GitLab CE (this may take a while)")
            await ssh.run_command(
                "EXTERNAL_URL='http://gitlab.temp.local' apt-get install -y gitlab-ce",
                timeout=1800,  # 30 minutes max
            )

            # Stop services until configuration is restored
            logger.info("Stopping GitLab services for restore")
            await ssh.run_command("gitlab-ctl stop", timeout=60)

            logger.info("GitLab CE installation complete")

        finally:
            ssh.close()

    async def _restore_config(self, server_ip: str) -> None:
        """Restore GitLab configuration from backup."""
        logger.info("Restoring configuration", server_ip=server_ip)

        ssh = self._get_ssh_client(server_ip)

        try:
            # Create temp directory for extraction
            await ssh.run_command("mkdir -p /tmp/gitlab-restore", timeout=30)

            # Get latest archive name from Borg
            logger.info("Finding latest backup archive")
            archive_cmd = f"""
source /etc/gitlab-backup.conf 2>/dev/null || export BORG_REPO='{self.backup_settings.borg_repo}'
export BORG_PASSPHRASE='{self.backup_settings.borg_passphrase.get_secret_value()}'
borg list --last 1 --format '{{archive}}' "$BORG_REPO"
"""
            archive_name = (await ssh.run_command(archive_cmd, timeout=60)).strip()
            if not archive_name:
                raise RuntimeError("No backup archives found in Borg repository")

            logger.info("Extracting backup archive", archive=archive_name)

            # Extract only config files first
            extract_cmd = f"""
cd /tmp/gitlab-restore
source /etc/gitlab-backup.conf 2>/dev/null || export BORG_REPO='{self.backup_settings.borg_repo}'
export BORG_PASSPHRASE='{self.backup_settings.borg_passphrase.get_secret_value()}'
borg extract "$BORG_REPO::{archive_name}" etc/gitlab/
"""
            await ssh.run_command(extract_cmd, timeout=600)

            # Restore configuration files
            logger.info("Copying configuration files")
            await ssh.run_command(
                "cp /tmp/gitlab-restore/etc/gitlab/gitlab.rb /etc/gitlab/gitlab.rb",
                timeout=30,
            )
            await ssh.run_command(
                "cp /tmp/gitlab-restore/etc/gitlab/gitlab-secrets.json /etc/gitlab/gitlab-secrets.json",
                timeout=30,
            )
            await ssh.run_command("chmod 600 /etc/gitlab/gitlab.rb /etc/gitlab/gitlab-secrets.json", timeout=30)

            logger.info("Configuration restored")

        finally:
            ssh.close()

    async def _restore_backup(self, server_ip: str) -> None:
        """Restore GitLab backup."""
        logger.info("Restoring GitLab backup", server_ip=server_ip)

        ssh = self._get_ssh_client(server_ip)

        try:
            # Get latest archive
            archive_cmd = f"""
source /etc/gitlab-backup.conf 2>/dev/null || export BORG_REPO='{self.backup_settings.borg_repo}'
export BORG_PASSPHRASE='{self.backup_settings.borg_passphrase.get_secret_value()}'
borg list --last 1 --format '{{archive}}' "$BORG_REPO"
"""
            archive_name = (await ssh.run_command(archive_cmd, timeout=60)).strip()

            # Extract backup file
            logger.info("Extracting backup tarball from archive")
            extract_cmd = f"""
cd /tmp/gitlab-restore
source /etc/gitlab-backup.conf 2>/dev/null || export BORG_REPO='{self.backup_settings.borg_repo}'
export BORG_PASSPHRASE='{self.backup_settings.borg_passphrase.get_secret_value()}'
borg extract "$BORG_REPO::{archive_name}" --pattern '*.tar'
"""
            await ssh.run_command(extract_cmd, timeout=1200)

            # Find and copy backup file to GitLab backups directory
            logger.info("Copying backup to GitLab backups directory")
            await ssh.run_command(
                "mkdir -p /var/opt/gitlab/backups && "
                "find /tmp/gitlab-restore -name '*_gitlab_backup.tar' -exec cp {{}} /var/opt/gitlab/backups/ \\;",
                timeout=300,
            )

            # Get backup timestamp
            timestamp_cmd = "ls -1 /var/opt/gitlab/backups/*_gitlab_backup.tar | head -1 | xargs basename | sed 's/_gitlab_backup.tar//'"
            backup_timestamp = (await ssh.run_command(timestamp_cmd, timeout=30)).strip()

            if not backup_timestamp:
                raise RuntimeError("Could not determine backup timestamp")

            logger.info("Backup timestamp identified", timestamp=backup_timestamp)

            # Stop services that need to be stopped for restore
            await ssh.run_command("gitlab-ctl stop puma", timeout=60)
            await ssh.run_command("gitlab-ctl stop sidekiq", timeout=60)

            # Run the restore
            logger.info("Running GitLab backup restore (this may take a while)")
            restore_cmd = f"gitlab-backup restore BACKUP={backup_timestamp} force=yes"
            await ssh.run_command(restore_cmd, timeout=3600)  # 1 hour max

            logger.info("Backup restore complete")

        finally:
            ssh.close()

    async def _reconfigure_gitlab(self, server_ip: str) -> None:
        """Reconfigure GitLab after restore."""
        logger.info("Reconfiguring GitLab", server_ip=server_ip)

        ssh = self._get_ssh_client(server_ip)

        try:
            # Run reconfigure
            await ssh.run_command("gitlab-ctl reconfigure", timeout=600)

            # Restart all services
            logger.info("Restarting GitLab services")
            await ssh.run_command("gitlab-ctl restart", timeout=300)

            # Wait for services to come up
            logger.info("Waiting for services to start")
            await asyncio.sleep(60)

            logger.info("GitLab reconfiguration complete")

        finally:
            ssh.close()

    async def _verify_recovery(self, server_ip: str) -> None:
        """Verify recovered GitLab is working."""
        logger.info("Verifying recovery", server_ip=server_ip)

        ssh = self._get_ssh_client(server_ip)
        verification_errors = []

        try:
            # Check GitLab status
            logger.info("Checking GitLab service status")
            status_output = await ssh.run_command("gitlab-ctl status", timeout=60)
            if "down:" in status_output.lower():
                verification_errors.append("Some GitLab services are down")
                logger.warning("Service status check", output=status_output)

            # Run GitLab check
            logger.info("Running GitLab integrity check")
            check_output = await ssh.run_command(
                "gitlab-rake gitlab:check SANITIZE=true",
                timeout=600,
            )
            if "Failure" in check_output or "Error" in check_output:
                verification_errors.append("GitLab check reported issues")
                logger.warning("GitLab check output", output=check_output[-2000:])

            # Test health endpoint
            logger.info("Testing health endpoint")
            import httpx

            async with httpx.AsyncClient(timeout=30) as client:
                try:
                    response = await client.get(f"http://{server_ip}/-/health")
                    if response.status_code != 200:
                        verification_errors.append(f"Health check returned {response.status_code}")
                except Exception as e:
                    verification_errors.append(f"Health check failed: {e}")

            # Test readiness endpoint
            try:
                response = await client.get(f"http://{server_ip}/-/readiness")
                if response.status_code != 200:
                    verification_errors.append(f"Readiness check returned {response.status_code}")
            except Exception as e:
                verification_errors.append(f"Readiness check failed: {e}")

            if verification_errors:
                error_summary = "; ".join(verification_errors)
                logger.error("Recovery verification found issues", errors=error_summary)
                await self.alerts.send_alert(
                    severity="warning",
                    title="Recovery Verification Warnings",
                    message=f"Recovery completed but verification found issues:\n{error_summary}",
                )
            else:
                logger.info("Recovery verification passed all checks")

        finally:
            ssh.close()

    def get_recovery_status(self) -> RecoveryState | None:
        """Get current recovery status."""
        return self._current_recovery
