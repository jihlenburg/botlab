"""Tests for disaster recovery module."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.restore.recovery import RecoveryManager, RecoveryState, RecoveryStep
from src.restore.tester import RestoreTester, RestoreTestResult


class TestRecoveryState:
    """Tests for RecoveryState dataclass."""

    def test_initial_state(self):
        """Test initial recovery state."""
        state = RecoveryState()

        assert state.started_at is not None
        assert state.completed_at is None
        assert state.current_step is None
        assert state.completed_steps == []
        assert state.failed_step is None
        assert state.error is None
        assert state.new_server_id is None
        assert state.new_server_ip is None

    def test_is_complete(self):
        """Test is_complete property."""
        state = RecoveryState()
        assert state.is_complete is False

        state.completed_at = datetime.now()
        assert state.is_complete is True

    def test_duration_minutes(self):
        """Test duration calculation."""
        state = RecoveryState()

        # In progress - should return time since start
        duration = state.duration_minutes
        assert duration >= 0

        # Completed - should return fixed duration
        state.completed_at = datetime.now()
        duration = state.duration_minutes
        assert duration >= 0


class TestRecoveryStep:
    """Tests for RecoveryStep enum."""

    def test_step_values(self):
        """Test recovery step values."""
        assert RecoveryStep.PROVISION_SERVER.value == "provision_server"
        assert RecoveryStep.ATTACH_VOLUMES.value == "attach_volumes"
        assert RecoveryStep.INSTALL_GITLAB.value == "install_gitlab"
        assert RecoveryStep.RESTORE_CONFIG.value == "restore_config"
        assert RecoveryStep.RESTORE_BACKUP.value == "restore_backup"
        assert RecoveryStep.RECONFIGURE.value == "reconfigure"
        assert RecoveryStep.VERIFY.value == "verify"
        assert RecoveryStep.UPDATE_DNS.value == "update_dns"


class TestRecoveryManager:
    """Tests for RecoveryManager."""

    @pytest.fixture
    def recovery_manager(
        self,
        hetzner_settings,
        backup_settings,
        gitlab_settings,
        mock_alert_manager,
        mock_hcloud_client,
    ):
        """Create a RecoveryManager with mocked dependencies."""
        with patch("hcloud.Client", return_value=mock_hcloud_client):
            manager = RecoveryManager(
                hetzner_settings=hetzner_settings,
                backup_settings=backup_settings,
                gitlab_settings=gitlab_settings,
                alert_manager=mock_alert_manager,
            )
            manager.hcloud = mock_hcloud_client
            return manager

    def test_initialization(self, recovery_manager):
        """Test RecoveryManager initialization."""
        assert recovery_manager._current_recovery is None
        assert recovery_manager.hcloud is not None

    @pytest.mark.asyncio
    async def test_initiate_recovery_requires_approval(
        self, recovery_manager, mock_alert_manager
    ):
        """Test that recovery without auto_approve waits for approval."""
        state = await recovery_manager.initiate_recovery(
            reason="Test recovery",
            auto_approve=False,
        )

        # Should send alerts but not proceed
        assert state.current_step is None
        assert mock_alert_manager.send_alert.called

    @pytest.mark.asyncio
    async def test_initiate_recovery_already_in_progress(self, recovery_manager):
        """Test that starting recovery while one is in progress fails."""
        # Start a recovery
        recovery_manager._current_recovery = RecoveryState()

        with pytest.raises(RuntimeError, match="already in progress"):
            await recovery_manager.initiate_recovery(
                reason="Second recovery",
                auto_approve=True,
            )

    def test_get_recovery_status_none(self, recovery_manager):
        """Test getting status when no recovery is in progress."""
        status = recovery_manager.get_recovery_status()
        assert status is None

    def test_get_recovery_status_in_progress(self, recovery_manager):
        """Test getting status during recovery."""
        state = RecoveryState()
        state.current_step = RecoveryStep.INSTALL_GITLAB
        recovery_manager._current_recovery = state

        status = recovery_manager.get_recovery_status()
        assert status is not None
        assert status.current_step == RecoveryStep.INSTALL_GITLAB

    @pytest.mark.asyncio
    async def test_wait_for_action_success(self, recovery_manager, mock_hcloud_client):
        """Test waiting for Hetzner action to complete."""
        mock_action = MagicMock()
        mock_action.id = 1
        mock_action.status = "success"

        mock_hcloud_client.actions.get_by_id.return_value = mock_action

        # Should not raise
        await recovery_manager._wait_for_action(mock_action, timeout=10)

    @pytest.mark.asyncio
    async def test_wait_for_action_error(self, recovery_manager, mock_hcloud_client):
        """Test handling Hetzner action error."""
        mock_action = MagicMock()
        mock_action.id = 1
        mock_action.status = "error"
        mock_action.error = {"message": "Server creation failed"}

        mock_hcloud_client.actions.get_by_id.return_value = mock_action

        with pytest.raises(RuntimeError, match="action failed"):
            await recovery_manager._wait_for_action(mock_action, timeout=10)

    @pytest.mark.asyncio
    async def test_wait_for_action_timeout(self, recovery_manager, mock_hcloud_client):
        """Test action timeout."""
        mock_action = MagicMock()
        mock_action.id = 1
        mock_action.status = "running"

        mock_hcloud_client.actions.get_by_id.return_value = mock_action

        with pytest.raises(TimeoutError):
            await recovery_manager._wait_for_action(mock_action, timeout=1)


class TestRestoreTestResult:
    """Tests for RestoreTestResult dataclass."""

    def test_initial_result(self):
        """Test initial restore test result."""
        result = RestoreTestResult(
            success=False,
            start_time=datetime.now(),
        )

        assert result.success is False
        assert result.end_time is None
        assert result.server_id is None
        assert result.steps_completed == []
        assert result.errors == []
        assert result.verification_results == {}

    def test_duration_minutes(self):
        """Test duration calculation."""
        start = datetime.now()
        result = RestoreTestResult(success=True, start_time=start)

        # Without end_time
        assert result.duration_minutes == 0

        # With end_time
        result.end_time = datetime.now()
        assert result.duration_minutes >= 0


class TestRestoreTester:
    """Tests for RestoreTester."""

    @pytest.fixture
    def restore_tester(
        self,
        hetzner_settings,
        backup_settings,
        gitlab_settings,
        mock_alert_manager,
        mock_hcloud_client,
    ):
        """Create a RestoreTester with mocked dependencies."""
        with patch("hcloud.Client", return_value=mock_hcloud_client):
            tester = RestoreTester(
                hetzner_settings=hetzner_settings,
                backup_settings=backup_settings,
                gitlab_settings=gitlab_settings,
                alert_manager=mock_alert_manager,
            )
            tester.hcloud = mock_hcloud_client
            return tester

    def test_initialization(self, restore_tester):
        """Test RestoreTester initialization."""
        assert restore_tester.hcloud is not None
        assert restore_tester.alerts is not None

    @pytest.mark.asyncio
    async def test_provision_test_server(self, restore_tester, mock_hcloud_client):
        """Test provisioning a test server."""
        # Mock SSH waiting
        with patch.object(restore_tester, "_wait_for_action", new_callable=AsyncMock):
            with patch.object(restore_tester, "_wait_for_ssh", new_callable=AsyncMock):
                server = await restore_tester._provision_test_server()

        assert server is not None
        mock_hcloud_client.servers.create.assert_called_once()

        # Verify labels
        call_kwargs = mock_hcloud_client.servers.create.call_args.kwargs
        assert call_kwargs["labels"]["purpose"] == "restore-test"
        assert call_kwargs["labels"]["temporary"] == "true"

    @pytest.mark.asyncio
    async def test_verify_restore_all_passing(self, restore_tester, mock_ssh_client):
        """Test verification when all checks pass."""
        mock_ssh_client.run_command.side_effect = [
            # gitlab-ctl status
            "run: puma: (pid 1234) 100s\nrun: sidekiq: (pid 1235) 100s\n",
            # gitlab-rake check
            "Checking GitLab Shell ... Finished\nChecking Sidekiq ... Finished\n",
            # gitlab-psql
            "1\n",
        ]

        with patch.object(restore_tester, "_get_ssh_client", return_value=mock_ssh_client):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.get.return_value = MagicMock(status_code=200)
                mock_client_class.return_value = mock_client

                results = await restore_tester._verify_restore("10.0.0.1")

        assert results["services_running"] is True
        assert results["health_check"] is True

    @pytest.mark.asyncio
    async def test_verify_restore_with_failures(self, restore_tester, mock_ssh_client):
        """Test verification when some checks fail."""
        mock_ssh_client.run_command.side_effect = [
            # gitlab-ctl status - with down services
            "run: puma: (pid 1234) 100s\ndown: sidekiq: 0s, want down\n",
            # gitlab-rake check - with failures
            "Checking GitLab Shell ... Failure\n",
            # gitlab-psql
            "ERROR: connection refused\n",
        ]

        with patch.object(restore_tester, "_get_ssh_client", return_value=mock_ssh_client):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.get.return_value = MagicMock(status_code=503)
                mock_client_class.return_value = mock_client

                results = await restore_tester._verify_restore("10.0.0.1")

        assert results["health_check"] is False

    @pytest.mark.asyncio
    async def test_send_report(self, restore_tester, mock_alert_manager):
        """Test sending restore test report."""
        result = RestoreTestResult(
            success=True,
            start_time=datetime.now(),
            end_time=datetime.now(),
            steps_completed=["server_provisioned", "gitlab_installed"],
            verification_results={"health_check": True},
        )

        await restore_tester._send_report(result)

        mock_alert_manager.send_alert.assert_called_once()
        call_kwargs = mock_alert_manager.send_alert.call_args.kwargs
        assert call_kwargs["severity"] == "info"
        assert "PASSED" in call_kwargs["message"]

    @pytest.mark.asyncio
    async def test_send_report_failure(self, restore_tester, mock_alert_manager):
        """Test sending report for failed test."""
        result = RestoreTestResult(
            success=False,
            start_time=datetime.now(),
            end_time=datetime.now(),
            errors=["Installation failed"],
            verification_results={"health_check": False},
        )

        await restore_tester._send_report(result)

        call_kwargs = mock_alert_manager.send_alert.call_args.kwargs
        assert call_kwargs["severity"] == "warning"
        assert "FAILED" in call_kwargs["message"]


class TestRecoveryIntegration:
    """Integration-style tests for recovery workflow."""

    @pytest.mark.asyncio
    async def test_full_recovery_workflow_mocked(
        self,
        hetzner_settings,
        backup_settings,
        gitlab_settings,
        mock_alert_manager,
        mock_hcloud_client,
        mock_ssh_client,
    ):
        """Test a complete recovery workflow with all steps mocked."""
        with patch("hcloud.Client", return_value=mock_hcloud_client):
            manager = RecoveryManager(
                hetzner_settings=hetzner_settings,
                backup_settings=backup_settings,
                gitlab_settings=gitlab_settings,
                alert_manager=mock_alert_manager,
            )
            manager.hcloud = mock_hcloud_client

            # Mock all the internal methods
            manager._provision_recovery_server = AsyncMock(
                return_value=MagicMock(
                    id=12345,
                    public_net=MagicMock(ipv4=MagicMock(ip="10.0.0.1")),
                )
            )
            manager._attach_volumes = AsyncMock()
            manager._install_gitlab = AsyncMock()
            manager._restore_config = AsyncMock()
            manager._restore_backup = AsyncMock()
            manager._reconfigure_gitlab = AsyncMock()
            manager._verify_recovery = AsyncMock()

            state = await manager.initiate_recovery(
                reason="Test full workflow",
                auto_approve=True,
            )

            # Verify all steps completed
            assert state.is_complete
            assert RecoveryStep.PROVISION_SERVER in state.completed_steps
            assert RecoveryStep.VERIFY in state.completed_steps
            assert state.new_server_ip == "10.0.0.1"
            assert state.error is None

    @pytest.mark.asyncio
    async def test_recovery_failure_handling(
        self,
        hetzner_settings,
        backup_settings,
        gitlab_settings,
        mock_alert_manager,
        mock_hcloud_client,
    ):
        """Test recovery handling when a step fails."""
        with patch("hcloud.Client", return_value=mock_hcloud_client):
            manager = RecoveryManager(
                hetzner_settings=hetzner_settings,
                backup_settings=backup_settings,
                gitlab_settings=gitlab_settings,
                alert_manager=mock_alert_manager,
            )
            manager.hcloud = mock_hcloud_client

            # Mock provisioning to succeed but install to fail
            manager._provision_recovery_server = AsyncMock(
                return_value=MagicMock(
                    id=12345,
                    public_net=MagicMock(ipv4=MagicMock(ip="10.0.0.1")),
                )
            )
            manager._attach_volumes = AsyncMock()
            manager._install_gitlab = AsyncMock(
                side_effect=RuntimeError("Installation failed")
            )

            state = await manager.initiate_recovery(
                reason="Test failure handling",
                auto_approve=True,
            )

            # Verify failure was recorded
            assert state.is_complete
            assert state.failed_step == RecoveryStep.INSTALL_GITLAB
            assert state.error == "Installation failed"

            # Critical alert should have been sent
            assert mock_alert_manager.send_alert.called
            last_call = mock_alert_manager.send_alert.call_args
            assert last_call.kwargs["severity"] == "critical"
            assert "FAILED" in last_call.kwargs["title"]
