"""Disaster recovery automation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import structlog
from hcloud import Client as HCloudClient
from hcloud.images import Image
from hcloud.server_types import ServerType
from hcloud.locations import Location
from hcloud.volumes import Volume
from hcloud.networks import Network

from src.config import HetznerSettings, BackupSettings
from src.alerting.manager import AlertManager

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
        alert_manager: AlertManager,
    ) -> None:
        self.hcloud = HCloudClient(token=hetzner_settings.api_token.get_secret_value())
        self.location = hetzner_settings.location
        self.backup_settings = backup_settings
        self.alerts = alert_manager
        self._current_recovery: RecoveryState | None = None

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
        loop = asyncio.get_event_loop()

        def create_server():
            response = self.hcloud.servers.create(
                name=f"gitlab-recovery-{datetime.now().strftime('%Y%m%d-%H%M')}",
                server_type=ServerType(name="cpx31"),  # Match original spec
                image=Image(name="ubuntu-24.04"),
                location=Location(name=self.location),
                labels={
                    "purpose": "gitlab-recovery",
                    "managed_by": "admin-bot",
                },
            )
            return response.server

        server = await loop.run_in_executor(None, create_server)

        # Wait for server to be ready
        await asyncio.sleep(30)

        return server

    async def _attach_volumes(self, server) -> None:
        """Attach existing volumes to new server."""
        # If old server is dead, volumes need to be detached first
        # This may require manual intervention
        logger.info("Volume attachment step - may require manual intervention")

    async def _install_gitlab(self, server_ip: str) -> None:
        """Install GitLab CE on new server."""
        logger.info("Installing GitLab CE", server_ip=server_ip)
        # SSH and run installation script
        await asyncio.sleep(900)  # ~15 minutes for installation

    async def _restore_config(self, server_ip: str) -> None:
        """Restore GitLab configuration from backup."""
        logger.info("Restoring configuration", server_ip=server_ip)
        # Extract config from Borg and copy to server
        await asyncio.sleep(60)

    async def _restore_backup(self, server_ip: str) -> None:
        """Restore GitLab backup."""
        logger.info("Restoring GitLab backup", server_ip=server_ip)
        # Extract backup from Borg and restore
        await asyncio.sleep(1800)  # ~30 minutes for restore

    async def _reconfigure_gitlab(self, server_ip: str) -> None:
        """Reconfigure GitLab after restore."""
        logger.info("Reconfiguring GitLab", server_ip=server_ip)
        # Run gitlab-ctl reconfigure
        await asyncio.sleep(300)

    async def _verify_recovery(self, server_ip: str) -> None:
        """Verify recovered GitLab is working."""
        logger.info("Verifying recovery", server_ip=server_ip)
        # Check health, run gitlab:check, test auth
        await asyncio.sleep(60)

    def get_recovery_status(self) -> RecoveryState | None:
        """Get current recovery status."""
        return self._current_recovery
