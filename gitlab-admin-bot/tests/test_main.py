"""Tests for main FastAPI application."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.main import (
    health_check,
    status,
    trigger_analysis,
    trigger_backup,
    trigger_maintenance,
)


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_healthy(self):
        """Test health endpoint returns expected response."""
        result = await health_check()
        assert result == {"status": "healthy", "version": "1.0.0"}


class TestStatusEndpoint:
    """Tests for /status endpoint."""

    @pytest.mark.asyncio
    async def test_status_not_initialized(self):
        """Test status when bot is not initialized."""
        with patch("src.main.bot", None):
            result = await status()
            assert result == {"status": "not_initialized"}

    @pytest.mark.asyncio
    async def test_status_running(self):
        """Test status when bot is running with all monitors."""
        mock_bot = MagicMock()
        mock_bot.health_monitor.get_status = AsyncMock(return_value={"status": "ok"})
        mock_bot.resource_monitor.get_status = AsyncMock(
            return_value={"disk": {"percent": 45}}
        )
        mock_bot.backup_monitor.get_status = AsyncMock(
            return_value={"age_hours": 1.5}
        )

        with patch("src.main.bot", mock_bot):
            result = await status()

        assert result["status"] == "running"
        assert result["health"]["status"] == "ok"
        assert result["resources"]["disk"]["percent"] == 45
        assert result["backup"]["age_hours"] == 1.5

    @pytest.mark.asyncio
    async def test_status_missing_monitors(self):
        """Test status when some monitors are None."""
        mock_bot = MagicMock()
        mock_bot.health_monitor = None
        mock_bot.resource_monitor = None
        mock_bot.backup_monitor = None

        with patch("src.main.bot", mock_bot):
            result = await status()

        assert result["status"] == "running"
        assert result["health"] == {}
        assert result["resources"] == {}
        assert result["backup"] == {}


class TestAnalyzeEndpoint:
    """Tests for /analyze endpoint."""

    @pytest.mark.asyncio
    async def test_analyze_no_bot(self):
        """Test analyze when bot is not available."""
        with patch("src.main.bot", None):
            result = await trigger_analysis()
            assert result == {"error": "AI analyst not available"}

    @pytest.mark.asyncio
    async def test_analyze_no_analyst(self):
        """Test analyze when AI analyst is not configured."""
        mock_bot = MagicMock()
        mock_bot.ai_analyst = None

        with patch("src.main.bot", mock_bot):
            result = await trigger_analysis()
            assert result == {"error": "AI analyst not available"}

    @pytest.mark.asyncio
    async def test_analyze_triggers_analysis(self):
        """Test that analyze triggers AI analysis."""
        mock_bot = MagicMock()
        mock_bot.ai_analyst = MagicMock()
        mock_bot._run_ai_analysis = AsyncMock()

        with patch("src.main.bot", mock_bot):
            result = await trigger_analysis()

        assert result == {"status": "analysis_triggered"}
        mock_bot._run_ai_analysis.assert_called_once()


class TestBackupEndpoint:
    """Tests for /backup endpoint."""

    @pytest.mark.asyncio
    async def test_backup_no_bot(self):
        """Test backup when bot is not available."""
        with patch("src.main.bot", None):
            result = await trigger_backup()
            assert result == {"error": "SSH client not available"}

    @pytest.mark.asyncio
    async def test_backup_success(self):
        """Test successful backup trigger."""
        mock_bot = MagicMock()
        mock_bot.ssh_client.run_command = AsyncMock(return_value="Backup created")

        with patch("src.main.bot", mock_bot):
            result = await trigger_backup()

        assert result["status"] == "backup_triggered"
        assert "Backup created" in result["output"]

    @pytest.mark.asyncio
    async def test_backup_failure(self):
        """Test backup trigger failure."""
        mock_bot = MagicMock()
        mock_bot.ssh_client.run_command = AsyncMock(
            side_effect=RuntimeError("Connection failed")
        )

        with patch("src.main.bot", mock_bot):
            result = await trigger_backup()

        assert "error" in result
        assert "Connection failed" in result["error"]


class TestMaintenanceEndpoint:
    """Tests for /maintenance/{task} endpoint."""

    @pytest.mark.asyncio
    async def test_maintenance_no_bot(self):
        """Test maintenance when bot is not available."""
        with patch("src.main.bot", None):
            result = await trigger_maintenance("rotate_logs")
            assert result == {"error": "Maintenance runner not available"}

    @pytest.mark.asyncio
    async def test_maintenance_unknown_task(self):
        """Test maintenance with unknown task name."""
        mock_bot = MagicMock()
        mock_bot.maintenance = MagicMock()

        with patch("src.main.bot", mock_bot):
            result = await trigger_maintenance("nonexistent_task")

        assert "error" in result
        assert "Unknown task" in result["error"]
        assert "available_tasks" in result

    @pytest.mark.asyncio
    async def test_maintenance_cleanup_artifacts(self):
        """Test triggering artifact cleanup."""
        mock_bot = MagicMock()
        mock_bot.maintenance.cleanup_old_artifacts = AsyncMock(
            return_value={"success": True, "output": "cleaned"}
        )

        with patch("src.main.bot", mock_bot):
            result = await trigger_maintenance("cleanup_artifacts")

        assert result["status"] == "completed"
        assert result["task"] == "cleanup_artifacts"

    @pytest.mark.asyncio
    async def test_maintenance_task_failure(self):
        """Test maintenance task that raises an exception."""
        mock_bot = MagicMock()
        mock_bot.maintenance.rotate_logs = AsyncMock(
            side_effect=RuntimeError("Log rotation failed")
        )

        with patch("src.main.bot", mock_bot):
            result = await trigger_maintenance("rotate_logs")

        assert result["status"] == "failed"
        assert "Log rotation failed" in result["error"]


class TestSchedulerJobsEndpoint:
    """Tests for /scheduler/jobs endpoint."""

    @pytest.mark.asyncio
    async def test_jobs_no_bot(self):
        """Test jobs listing when bot is not available."""
        from src.main import list_scheduled_jobs

        with patch("src.main.bot", None):
            result = await list_scheduled_jobs()
            assert result == {"error": "Scheduler not available"}

    @pytest.mark.asyncio
    async def test_jobs_listing(self):
        """Test jobs listing with scheduled jobs."""
        from src.main import list_scheduled_jobs

        mock_bot = MagicMock()
        mock_bot.scheduler.get_jobs.return_value = {
            "health_check": "GitLab Health Check",
            "backup_check": "Backup Monitor",
        }

        with patch("src.main.bot", mock_bot):
            result = await list_scheduled_jobs()

        assert len(result["jobs"]) == 2
        assert {"id": "health_check", "name": "GitLab Health Check"} in result["jobs"]


class TestAdminBot:
    """Tests for AdminBot class."""

    @pytest.mark.asyncio
    async def test_daily_maintenance_no_runner(self):
        """Test daily maintenance when runner is not initialized."""
        from src.main import AdminBot

        bot = AdminBot.__new__(AdminBot)
        bot.maintenance = None
        bot.alert_manager = None
        # Should not raise
        await bot._daily_maintenance()

    @pytest.mark.asyncio
    async def test_weekly_maintenance_no_runner(self):
        """Test weekly maintenance when runner is not initialized."""
        from src.main import AdminBot

        bot = AdminBot.__new__(AdminBot)
        bot.maintenance = None
        bot.alert_manager = None
        await bot._weekly_maintenance()

    @pytest.mark.asyncio
    async def test_daily_maintenance_error_sends_alert(self):
        """Test that daily maintenance errors trigger alerts."""
        from src.main import AdminBot

        bot = AdminBot.__new__(AdminBot)
        bot.maintenance = MagicMock()
        bot.maintenance.generate_daily_report = AsyncMock(
            side_effect=RuntimeError("Report failed")
        )
        bot.alert_manager = MagicMock()
        bot.alert_manager.send_alert = AsyncMock()

        await bot._daily_maintenance()

        bot.alert_manager.send_alert.assert_called_once()
        call_kwargs = bot.alert_manager.send_alert.call_args.kwargs
        assert call_kwargs["severity"] == "warning"
        assert "Daily Maintenance Failed" in call_kwargs["title"]
