"""Tests for maintenance tasks module."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.maintenance.tasks import MaintenanceRunner


class TestMaintenanceRunner:
    """Tests for MaintenanceRunner."""

    @pytest.fixture
    def runner(self, mock_ssh_client, mock_alert_manager):
        """Create a MaintenanceRunner with mocked dependencies."""
        return MaintenanceRunner(
            ssh_client=mock_ssh_client,
            alert_manager=mock_alert_manager,
        )

    @pytest.mark.asyncio
    async def test_cleanup_old_artifacts_success(self, runner, mock_ssh_client):
        """Test successful artifact cleanup."""
        mock_ssh_client.run_command = AsyncMock(return_value="Cleaned 42 files")

        result = await runner.cleanup_old_artifacts(days=30)

        assert result["success"] is True
        assert "Cleaned 42 files" in result["output"]
        mock_ssh_client.run_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_old_artifacts_failure(self, runner, mock_ssh_client):
        """Test artifact cleanup when command fails."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=RuntimeError("Permission denied")
        )

        result = await runner.cleanup_old_artifacts()

        assert result["success"] is False
        assert "Permission denied" in result["error"]

    @pytest.mark.asyncio
    async def test_cleanup_registry_success(self, runner, mock_ssh_client):
        """Test successful registry garbage collection."""
        mock_ssh_client.run_command = AsyncMock(return_value="GC completed")

        result = await runner.cleanup_registry()

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_cleanup_registry_failure(self, runner, mock_ssh_client):
        """Test registry GC failure."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=RuntimeError("Registry not available")
        )

        result = await runner.cleanup_registry()

        assert result["success"] is False
        assert "Registry not available" in result["error"]

    @pytest.mark.asyncio
    async def test_rotate_logs_success(self, runner, mock_ssh_client):
        """Test successful log rotation."""
        mock_ssh_client.run_command = AsyncMock(return_value="")

        result = await runner.rotate_logs()

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_rotate_logs_failure(self, runner, mock_ssh_client):
        """Test log rotation failure."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=RuntimeError("logrotate not found")
        )

        result = await runner.rotate_logs()

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_database_vacuum_success(self, runner, mock_ssh_client):
        """Test successful database vacuum."""
        mock_ssh_client.run_command = AsyncMock(return_value="VACUUM ANALYZE")

        result = await runner.database_vacuum()

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_database_vacuum_failure(self, runner, mock_ssh_client):
        """Test database vacuum failure."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=RuntimeError("Connection refused")
        )

        result = await runner.database_vacuum()

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_check_gitlab_integrity_clean(self, runner, mock_ssh_client):
        """Test integrity check with no issues."""
        mock_ssh_client.run_command = AsyncMock(
            return_value="Checking GitLab Shell ... Finished\nChecking Sidekiq ... Finished\n"
        )

        result = await runner.check_gitlab_integrity()

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_check_gitlab_integrity_with_failures(
        self, runner, mock_ssh_client, mock_alert_manager
    ):
        """Test integrity check that finds issues."""
        mock_ssh_client.run_command = AsyncMock(
            return_value="Checking GitLab Shell ... Failure\nChecking Sidekiq ... Finished\n"
        )

        result = await runner.check_gitlab_integrity()

        assert result["success"] is False
        mock_alert_manager.send_alert.assert_called_once()
        call_kwargs = mock_alert_manager.send_alert.call_args.kwargs
        assert call_kwargs["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_check_gitlab_integrity_error(self, runner, mock_ssh_client):
        """Test integrity check when command fails entirely."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=RuntimeError("SSH timeout")
        )

        result = await runner.check_gitlab_integrity()

        assert result["success"] is False
        assert "SSH timeout" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_daily_report(self, runner, mock_ssh_client, mock_alert_manager):
        """Test daily report generation."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                "Filesystem  Size  Used Avail Use% Mounted on\n/dev/sda1 100G 45G 55G 45% /",
                "run: puma: (pid 1234) 100s",
                "1704067200_gitlab_backup.tar",
            ]
        )

        result = await runner.generate_daily_report()

        assert "timestamp" in result
        assert "disk_usage" in result
        assert "gitlab_status" in result
        assert "recent_backups" in result
        mock_alert_manager.send_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_daily_report_partial_failure(
        self, runner, mock_ssh_client, mock_alert_manager
    ):
        """Test daily report when some commands fail."""
        mock_ssh_client.run_command = AsyncMock(
            side_effect=[
                RuntimeError("df failed"),
                "run: puma: (pid 1234) 100s",
                RuntimeError("backup list failed"),
            ]
        )

        result = await runner.generate_daily_report()

        assert "disk_error" in result
        assert "gitlab_status" in result
        assert "backup_error" in result
        # Report is still sent
        mock_alert_manager.send_alert.assert_called_once()
