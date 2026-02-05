"""Extended tests for main module to increase coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import AdminBot, app


class TestAdminBotExtended:
    """Extended tests for AdminBot class."""

    @pytest.fixture
    def mock_settings(self, settings):
        """Provide settings through get_settings."""
        with patch("src.main.get_settings", return_value=settings):
            yield settings

    @pytest.fixture
    def admin_bot(self, mock_settings):
        """Create AdminBot with mocked settings."""
        return AdminBot()

    @pytest.mark.asyncio
    async def test_initialize(self, admin_bot, mock_settings):
        """Test AdminBot initialization."""
        with (
            patch("src.main.GitLabClient") as mock_gitlab,
            patch("src.main.SSHClient") as mock_ssh,
            patch("src.main.AlertManager") as mock_alert,
            patch("src.main.AIAnalyst") as mock_ai,
            patch("src.main.HealthMonitor"),
            patch("src.main.ResourceMonitor"),
            patch("src.main.BackupMonitor"),
            patch("src.main.MaintenanceRunner"),
            patch("src.main.Scheduler") as mock_scheduler,
        ):
            await admin_bot.initialize()

            mock_gitlab.assert_called_once()
            mock_ssh.assert_called_once()
            mock_alert.assert_called_once()
            mock_ai.assert_called_once()
            mock_scheduler.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_ai_disabled(self, mock_settings):
        """Test initialization with AI disabled."""
        mock_settings.claude.enabled = False

        with patch("src.main.get_settings", return_value=mock_settings):
            bot = AdminBot()

            with (
                patch("src.main.GitLabClient"),
                patch("src.main.SSHClient"),
                patch("src.main.AlertManager"),
                patch("src.main.AIAnalyst") as mock_ai,
                patch("src.main.HealthMonitor"),
                patch("src.main.ResourceMonitor"),
                patch("src.main.BackupMonitor"),
                patch("src.main.MaintenanceRunner"),
                patch("src.main.Scheduler"),
            ):
                await bot.initialize()

                mock_ai.assert_not_called()

    @pytest.mark.asyncio
    async def test_start(self, admin_bot):
        """Test starting the bot."""
        admin_bot.scheduler = MagicMock()

        await admin_bot.start()

        admin_bot.scheduler.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_no_scheduler(self, admin_bot):
        """Test start when scheduler is None."""
        admin_bot.scheduler = None

        # Should not raise
        await admin_bot.start()

    @pytest.mark.asyncio
    async def test_stop(self, admin_bot):
        """Test stopping the bot."""
        admin_bot.scheduler = MagicMock()
        admin_bot.ssh_client = MagicMock()

        await admin_bot.stop()

        admin_bot.scheduler.shutdown.assert_called_once()
        admin_bot.ssh_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_no_components(self, admin_bot):
        """Test stop when components are None."""
        admin_bot.scheduler = None
        admin_bot.ssh_client = None

        # Should not raise
        await admin_bot.stop()

    def test_schedule_jobs(self, admin_bot):
        """Test job scheduling."""
        admin_bot.scheduler = MagicMock()
        admin_bot.health_monitor = MagicMock()
        admin_bot.resource_monitor = MagicMock()
        admin_bot.backup_monitor = MagicMock()
        admin_bot.ai_analyst = MagicMock()

        admin_bot._schedule_jobs()

        assert admin_bot.scheduler.add_job.call_count >= 4

    def test_schedule_jobs_no_scheduler(self, admin_bot):
        """Test schedule_jobs when scheduler is None."""
        admin_bot.scheduler = None

        # Should not raise
        admin_bot._schedule_jobs()

    @pytest.mark.asyncio
    async def test_run_ai_analysis(self, admin_bot):
        """Test AI analysis run."""
        admin_bot.ai_analyst = AsyncMock()
        admin_bot.health_monitor = MagicMock()
        admin_bot.resource_monitor = MagicMock()
        admin_bot.backup_monitor = MagicMock()

        admin_bot.health_monitor.get_status = AsyncMock(return_value={"healthy": True})
        admin_bot.resource_monitor.get_status = AsyncMock(return_value={"disk": 50})
        admin_bot.backup_monitor.get_status = AsyncMock(return_value={"age": 1})

        mock_analysis = MagicMock()
        mock_analysis.actions_needed = False
        admin_bot.ai_analyst.analyze_system_state = AsyncMock(return_value=mock_analysis)

        await admin_bot._run_ai_analysis()

        admin_bot.ai_analyst.analyze_system_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_ai_analysis_no_analyst(self, admin_bot):
        """Test AI analysis when analyst is None."""
        admin_bot.ai_analyst = None

        # Should not raise
        await admin_bot._run_ai_analysis()

    @pytest.mark.asyncio
    async def test_run_ai_analysis_no_monitors(self, admin_bot):
        """Test AI analysis when monitors are not initialized."""
        admin_bot.ai_analyst = MagicMock()
        admin_bot.health_monitor = None

        await admin_bot._run_ai_analysis()

        # Should skip analysis
        admin_bot.ai_analyst.analyze_system_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_ai_analysis_with_actions(self, admin_bot, mock_alert_manager):
        """Test AI analysis with recommended actions."""
        from src.ai.analyst import RecommendedAction, Urgency

        admin_bot.ai_analyst = AsyncMock()
        admin_bot.alert_manager = mock_alert_manager
        admin_bot.health_monitor = MagicMock()
        admin_bot.resource_monitor = MagicMock()
        admin_bot.backup_monitor = MagicMock()

        admin_bot.health_monitor.get_status = AsyncMock(return_value={})
        admin_bot.resource_monitor.get_status = AsyncMock(return_value={})
        admin_bot.backup_monitor.get_status = AsyncMock(return_value={})

        mock_action = RecommendedAction(
            name="cleanup",
            description="Clean up artifacts",
            reason="Disk space low",
            urgency=Urgency.MEDIUM,
            auto_execute=False,
        )
        mock_analysis = MagicMock()
        mock_analysis.actions_needed = True
        mock_analysis.recommendations = ["Clean up disk"]
        mock_analysis.urgency = "medium"
        mock_analysis.recommended_actions = [mock_action]
        admin_bot.ai_analyst.analyze_system_state = AsyncMock(return_value=mock_analysis)

        await admin_bot._run_ai_analysis()

        mock_alert_manager.send_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_ai_analysis_with_auto_execute_action(self, admin_bot):
        """Test AI analysis with auto-execute action."""
        from src.ai.analyst import RecommendedAction, Urgency

        admin_bot.ai_analyst = AsyncMock()
        admin_bot.health_monitor = MagicMock()
        admin_bot.resource_monitor = MagicMock()
        admin_bot.backup_monitor = MagicMock()
        admin_bot.alert_manager = None

        admin_bot.health_monitor.get_status = AsyncMock(return_value={})
        admin_bot.resource_monitor.get_status = AsyncMock(return_value={})
        admin_bot.backup_monitor.get_status = AsyncMock(return_value={})

        mock_action = RecommendedAction(
            name="auto_cleanup",
            description="Auto cleanup",
            reason="Needed",
            urgency=Urgency.LOW,
            auto_execute=True,
        )
        mock_analysis = MagicMock()
        mock_analysis.actions_needed = True
        mock_analysis.recommended_actions = [mock_action]
        admin_bot.ai_analyst.analyze_system_state = AsyncMock(return_value=mock_analysis)

        with patch.object(admin_bot, "_execute_action", new_callable=AsyncMock) as mock_exec:
            await admin_bot._run_ai_analysis()
            mock_exec.assert_called_once_with(mock_action)

    @pytest.mark.asyncio
    async def test_run_ai_analysis_error(self, admin_bot):
        """Test AI analysis error handling."""
        admin_bot.ai_analyst = AsyncMock()
        admin_bot.health_monitor = MagicMock()
        admin_bot.resource_monitor = MagicMock()
        admin_bot.backup_monitor = MagicMock()

        admin_bot.health_monitor.get_status = AsyncMock(
            side_effect=Exception("Health check failed")
        )

        # Should not raise, just log
        await admin_bot._run_ai_analysis()

    @pytest.mark.asyncio
    async def test_execute_action(self, admin_bot):
        """Test action execution."""
        from src.ai.analyst import RecommendedAction, Urgency

        action = RecommendedAction(
            name="test_action",
            description="Test",
            reason="Testing",
            urgency=Urgency.LOW,
        )

        # Current implementation is a pass, just verify it doesn't raise
        await admin_bot._execute_action(action)

    @pytest.mark.asyncio
    async def test_daily_maintenance(self, admin_bot):
        """Test daily maintenance routine."""
        admin_bot.maintenance = MagicMock()
        admin_bot.maintenance.generate_daily_report = AsyncMock(return_value={})
        admin_bot.maintenance.rotate_logs = AsyncMock(return_value={"success": True})
        admin_bot.maintenance.cleanup_old_artifacts = AsyncMock(
            return_value={"success": True}
        )

        await admin_bot._daily_maintenance()

        admin_bot.maintenance.generate_daily_report.assert_called_once()
        admin_bot.maintenance.rotate_logs.assert_called_once()
        admin_bot.maintenance.cleanup_old_artifacts.assert_called_once()

    @pytest.mark.asyncio
    async def test_daily_maintenance_no_runner(self, admin_bot):
        """Test daily maintenance when runner is None."""
        admin_bot.maintenance = None

        # Should not raise
        await admin_bot._daily_maintenance()

    @pytest.mark.asyncio
    async def test_daily_maintenance_error(self, admin_bot, mock_alert_manager):
        """Test daily maintenance error handling."""
        admin_bot.maintenance = MagicMock()
        admin_bot.alert_manager = mock_alert_manager
        admin_bot.maintenance.generate_daily_report = AsyncMock(
            side_effect=RuntimeError("Report failed")
        )

        await admin_bot._daily_maintenance()

        mock_alert_manager.send_alert.assert_called_once()
        call_kwargs = mock_alert_manager.send_alert.call_args.kwargs
        assert call_kwargs["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_weekly_maintenance(self, admin_bot):
        """Test weekly maintenance routine."""
        admin_bot.maintenance = MagicMock()
        admin_bot.maintenance.cleanup_registry = AsyncMock(return_value={"success": True})
        admin_bot.maintenance.database_vacuum = AsyncMock(return_value={"success": True})
        admin_bot.maintenance.check_gitlab_integrity = AsyncMock(
            return_value={"success": True}
        )

        await admin_bot._weekly_maintenance()

        admin_bot.maintenance.cleanup_registry.assert_called_once()
        admin_bot.maintenance.database_vacuum.assert_called_once()
        admin_bot.maintenance.check_gitlab_integrity.assert_called_once()

    @pytest.mark.asyncio
    async def test_weekly_maintenance_no_runner(self, admin_bot):
        """Test weekly maintenance when runner is None."""
        admin_bot.maintenance = None

        # Should not raise
        await admin_bot._weekly_maintenance()

    @pytest.mark.asyncio
    async def test_weekly_maintenance_error(self, admin_bot, mock_alert_manager):
        """Test weekly maintenance error handling."""
        admin_bot.maintenance = MagicMock()
        admin_bot.alert_manager = mock_alert_manager
        admin_bot.maintenance.cleanup_registry = AsyncMock(
            side_effect=RuntimeError("GC failed")
        )

        await admin_bot._weekly_maintenance()

        mock_alert_manager.send_alert.assert_called_once()


class TestFastAPIEndpointsExtended:
    """Extended tests for FastAPI endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app, raise_server_exceptions=False)

    @pytest.fixture
    def mock_bot(self):
        """Create and set mock bot."""
        import src.main

        mock = MagicMock()
        mock.health_monitor = MagicMock()
        mock.resource_monitor = MagicMock()
        mock.backup_monitor = MagicMock()
        mock.ai_analyst = MagicMock()
        mock.ssh_client = MagicMock()
        mock.scheduler = MagicMock()
        mock.maintenance = MagicMock()

        mock.health_monitor.get_status = AsyncMock(return_value={"healthy": True})
        mock.resource_monitor.get_status = AsyncMock(return_value={"disk": 50})
        mock.backup_monitor.get_status = AsyncMock(return_value={"age": 1})
        mock._run_ai_analysis = AsyncMock()
        mock.ssh_client.run_command = AsyncMock(return_value="Backup started")
        mock.scheduler.get_jobs = MagicMock(return_value={"job1": "Health Check"})

        original_bot = src.main.bot
        src.main.bot = mock
        yield mock
        src.main.bot = original_bot

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"

    def test_status_not_initialized(self, client):
        """Test status when bot not initialized."""
        import src.main

        original_bot = src.main.bot
        src.main.bot = None
        try:
            response = client.get("/status")
            assert response.status_code == 200
            assert response.json()["status"] == "not_initialized"
        finally:
            src.main.bot = original_bot

    def test_status_running(self, client, mock_bot):
        """Test status when bot is running."""
        response = client.get("/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "health" in data
        assert "resources" in data
        assert "backup" in data

    def test_trigger_analysis_no_analyst(self, client, mock_bot):
        """Test trigger analysis when AI not available."""
        mock_bot.ai_analyst = None

        response = client.post("/analyze")
        assert response.status_code == 200
        assert "error" in response.json()

    def test_trigger_analysis_success(self, client, mock_bot):
        """Test successful analysis trigger."""
        response = client.post("/analyze")
        assert response.status_code == 200
        assert response.json()["status"] == "analysis_triggered"

    def test_trigger_backup_no_client(self, client, mock_bot):
        """Test backup trigger when SSH not available."""
        mock_bot.ssh_client = None

        response = client.post("/backup")
        assert response.status_code == 200
        assert "error" in response.json()

    def test_trigger_backup_success(self, client, mock_bot):
        """Test successful backup trigger."""
        response = client.post("/backup")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "backup_triggered"

    def test_trigger_backup_error(self, client, mock_bot):
        """Test backup trigger with error."""
        mock_bot.ssh_client.run_command = AsyncMock(
            side_effect=RuntimeError("SSH failed")
        )

        response = client.post("/backup")
        assert response.status_code == 200
        assert "error" in response.json()

    def test_list_scheduled_jobs_no_scheduler(self, client, mock_bot):
        """Test list jobs when scheduler not available."""
        mock_bot.scheduler = None

        response = client.get("/scheduler/jobs")
        assert response.status_code == 200
        assert "error" in response.json()

    def test_list_scheduled_jobs_success(self, client, mock_bot):
        """Test successful job listing."""
        response = client.get("/scheduler/jobs")
        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data

    def test_trigger_maintenance_no_runner(self, client, mock_bot):
        """Test maintenance trigger when runner not available."""
        mock_bot.maintenance = None

        response = client.post("/maintenance/cleanup_artifacts")
        assert response.status_code == 200
        assert "error" in response.json()

    def test_trigger_maintenance_unknown_task(self, client, mock_bot):
        """Test maintenance trigger with unknown task."""
        response = client.post("/maintenance/unknown_task")
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "available_tasks" in data

    def test_trigger_maintenance_success(self, client, mock_bot):
        """Test successful maintenance trigger."""
        mock_bot.maintenance.cleanup_old_artifacts = AsyncMock(
            return_value={"success": True}
        )

        response = client.post("/maintenance/cleanup_artifacts")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["task"] == "cleanup_artifacts"

    def test_trigger_maintenance_error(self, client, mock_bot):
        """Test maintenance trigger with error."""
        mock_bot.maintenance.cleanup_old_artifacts = AsyncMock(
            side_effect=RuntimeError("Cleanup failed")
        )

        response = client.post("/maintenance/cleanup_artifacts")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert "error" in data


class TestMainFunction:
    """Tests for main() entry point."""

    def test_main_function_exists(self):
        """Test that main function exists."""
        from src.main import main

        assert callable(main)

    def test_signal_handler(self):
        """Test signal handler setup."""
        from src.main import main

        with (
            patch("src.main.get_settings") as mock_settings,
            patch("src.main.uvicorn.run") as mock_run,
            patch("signal.signal") as mock_signal,
        ):
            mock_settings_obj = MagicMock()
            mock_settings_obj.api_host = "0.0.0.0"
            mock_settings_obj.api_port = 8080
            mock_settings_obj.log_level = "INFO"
            mock_settings.return_value = mock_settings_obj

            main()

            # Verify signal handlers were registered
            assert mock_signal.call_count >= 2
            mock_run.assert_called_once()
