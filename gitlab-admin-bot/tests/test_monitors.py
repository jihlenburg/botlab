"""Tests for monitoring modules."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.monitors.base import CheckResult, Status
from src.monitors.health import HealthMonitor
from src.monitors.resources import ResourceMonitor
from src.monitors.backup import BackupMonitor
from src.alerting.manager import AlertManager
from src.config import BackupSettings, MonitoringSettings


class TestHealthMonitor:
    """Tests for HealthMonitor."""

    @pytest.fixture
    def mock_gitlab_client(self):
        """Create a mocked GitLab client."""
        client = MagicMock()
        client.url = "https://gitlab.test.local"
        return client

    @pytest.fixture
    def health_monitor(self, mock_gitlab_client, mock_alert_manager):
        """Create a HealthMonitor with mocked dependencies."""
        return HealthMonitor(
            gitlab_client=mock_gitlab_client,
            alert_manager=mock_alert_manager,
        )

    @pytest.mark.asyncio
    async def test_check_all_healthy(self, health_monitor, mock_httpx_client):
        """Test health check when all endpoints are healthy."""
        responses = {
            "/-/health": mock_httpx_client().default_response,
            "/-/readiness": mock_httpx_client().default_response,
            "/-/liveness": mock_httpx_client().default_response,
        }

        with patch("httpx.AsyncClient", lambda **kwargs: mock_httpx_client(responses)):
            result = await health_monitor.check()

        assert result.status == Status.OK
        assert "passed" in result.message.lower()
        assert result.details["health"] is True
        assert result.details["readiness"] is True
        assert result.details["liveness"] is True

    @pytest.mark.asyncio
    async def test_check_health_failed(self, health_monitor, mock_httpx_client, conftest):
        """Test health check when health endpoint fails."""
        from tests.conftest import MockHttpxResponse

        responses = {
            "/-/health": MockHttpxResponse(503, "Service Unavailable"),
            "/-/readiness": MockHttpxResponse(200, "OK"),
            "/-/liveness": MockHttpxResponse(200, "OK"),
        }

        with patch("httpx.AsyncClient", lambda **kwargs: mock_httpx_client(responses)):
            result = await health_monitor.check()

        assert result.status == Status.CRITICAL
        assert "health check failed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_timeout(self, health_monitor):
        """Test health check when request times out."""
        import httpx

        async def mock_client_with_timeout(*args, **kwargs):
            class TimeoutClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

                async def get(self, url, **kwargs):
                    raise httpx.TimeoutException("Connection timed out")

            return TimeoutClient()

        with patch("httpx.AsyncClient", mock_client_with_timeout):
            result = await health_monitor.check()

        assert result.status == Status.CRITICAL
        assert "timed out" in result.message.lower()

    @pytest.mark.asyncio
    async def test_get_status(self, health_monitor, mock_httpx_client):
        """Test getting current status."""
        with patch("httpx.AsyncClient", lambda **kwargs: mock_httpx_client()):
            await health_monitor.check()
            status = await health_monitor.get_status()

        assert "last_check" in status
        assert "status" in status
        assert status["status"] == "ok"


class TestResourceMonitor:
    """Tests for ResourceMonitor."""

    @pytest.fixture
    def resource_monitor(self, mock_ssh_client, mock_alert_manager, monitoring_settings):
        """Create a ResourceMonitor with mocked dependencies."""
        return ResourceMonitor(
            ssh_client=mock_ssh_client,
            alert_manager=mock_alert_manager,
            thresholds=monitoring_settings,
        )

    @pytest.mark.asyncio
    async def test_check_resources_ok(self, resource_monitor, mock_ssh_client):
        """Test resource check when all resources are within thresholds."""
        # Mock command outputs
        mock_ssh_client.run_command.side_effect = [
            # df output
            "Filesystem     Size  Used Avail Use% Mounted on\n"
            "/dev/sda1      100G   45G   55G  45% /\n"
            "/dev/sdb1      200G   80G  120G  40% /var/opt/gitlab\n",
            # free output
            "              total        used        free      shared  buff/cache   available\n"
            "Mem:          16384        8192        4096         256        4096        8192\n"
            "Swap:          4096         512        3584\n",
            # uptime output
            "12:00:00 up 10 days, 5:00, 2 users, load average: 0.50, 0.60, 0.70\n",
            # nproc output
            "4\n",
        ]

        result = await resource_monitor.check()

        assert result.status == Status.OK
        assert "within thresholds" in result.message.lower()
        assert result.details["disk"]["/"]["percent"] == 45
        assert result.details["memory"]["used_percent"] == 50.0

    @pytest.mark.asyncio
    async def test_check_disk_warning(self, resource_monitor, mock_ssh_client):
        """Test resource check when disk usage is at warning level."""
        mock_ssh_client.run_command.side_effect = [
            # df output - 85% usage (warning)
            "Filesystem     Size  Used Avail Use% Mounted on\n"
            "/dev/sda1      100G   85G   15G  85% /\n",
            # free output
            "              total        used        free      shared  buff/cache   available\n"
            "Mem:          16384        8192        4096         256        4096        8192\n"
            "Swap:          4096         512        3584\n",
            # uptime output
            "12:00:00 up 10 days, 5:00, 2 users, load average: 0.50, 0.60, 0.70\n",
            # nproc output
            "4\n",
        ]

        result = await resource_monitor.check()

        assert result.status == Status.WARNING
        assert "warning" in result.message.lower()
        assert "disk" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_disk_critical(self, resource_monitor, mock_ssh_client):
        """Test resource check when disk usage is critical."""
        mock_ssh_client.run_command.side_effect = [
            # df output - 95% usage (critical)
            "Filesystem     Size  Used Avail Use% Mounted on\n"
            "/dev/sda1      100G   95G    5G  95% /\n",
            # free output
            "              total        used        free      shared  buff/cache   available\n"
            "Mem:          16384        8192        4096         256        4096        8192\n"
            "Swap:          4096         512        3584\n",
            # uptime output
            "12:00:00 up 10 days, 5:00, 2 users, load average: 0.50, 0.60, 0.70\n",
            # nproc output
            "4\n",
        ]

        result = await resource_monitor.check()

        assert result.status == Status.CRITICAL
        assert "critical" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_memory_critical(self, resource_monitor, mock_ssh_client):
        """Test resource check when memory usage is critical."""
        mock_ssh_client.run_command.side_effect = [
            # df output - normal
            "Filesystem     Size  Used Avail Use% Mounted on\n"
            "/dev/sda1      100G   45G   55G  45% /\n",
            # free output - 98% memory usage
            "              total        used        free      shared  buff/cache   available\n"
            "Mem:          16384       16040         100         200          44         344\n"
            "Swap:          4096        3000        1096\n",
            # uptime output
            "12:00:00 up 10 days, 5:00, 2 users, load average: 0.50, 0.60, 0.70\n",
            # nproc output
            "4\n",
        ]

        result = await resource_monitor.check()

        assert result.status == Status.CRITICAL
        assert "memory" in result.message.lower()


class TestBackupMonitor:
    """Tests for BackupMonitor."""

    @pytest.fixture
    def backup_monitor(self, mock_ssh_client, mock_alert_manager, backup_settings):
        """Create a BackupMonitor with mocked dependencies."""
        return BackupMonitor(
            ssh_client=mock_ssh_client,
            alert_manager=mock_alert_manager,
            settings=backup_settings,
        )

    @pytest.mark.asyncio
    async def test_check_backup_healthy(self, backup_monitor, mock_ssh_client):
        """Test backup check when backups are healthy."""
        import time

        current_time = int(time.time())
        recent_time = current_time - 3600  # 1 hour ago

        mock_ssh_client.run_command.side_effect = [
            # ls output for local backup
            f"-rw------- 1 root root 5368709120 Jan  1 12:00 /var/opt/gitlab/backups/test_gitlab_backup.tar\n",
            # stat output for mtime
            f"{recent_time}\n",
            # borg list output
            "gitlab-2024-01-01-12-00 2024-01-01 12:00:00\n",
            # backup log
            "\n",  # No errors
        ]

        result = await backup_monitor.check()

        assert result.status == Status.OK
        assert "healthy" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_backup_too_old(self, backup_monitor, mock_ssh_client):
        """Test backup check when backup is too old."""
        import time

        current_time = int(time.time())
        old_time = current_time - (6 * 3600)  # 6 hours ago

        mock_ssh_client.run_command.side_effect = [
            # ls output for local backup
            f"-rw------- 1 root root 5368709120 Jan  1 06:00 /var/opt/gitlab/backups/test_gitlab_backup.tar\n",
            # stat output for mtime (6 hours old)
            f"{old_time}\n",
            # borg list output
            "gitlab-2024-01-01-06-00 2024-01-01 06:00:00\n",
            # backup log
            "\n",
        ]

        result = await backup_monitor.check()

        assert result.status == Status.CRITICAL
        assert "old" in result.message.lower() or "hours" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_no_backup_found(self, backup_monitor, mock_ssh_client):
        """Test backup check when no backup file exists."""
        mock_ssh_client.run_command.side_effect = [
            # ls output - no files
            "\n",
            # borg list output
            "\n",
            # backup log
            "\n",
        ]

        result = await backup_monitor.check()

        assert result.status == Status.CRITICAL
        assert "no backup" in result.message.lower() or "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_trigger_backup(self, backup_monitor, mock_ssh_client):
        """Test triggering an immediate backup."""
        mock_ssh_client.run_command.return_value = "Backup created successfully"

        result = await backup_monitor.trigger_backup()

        assert result["success"] is True
        mock_ssh_client.run_command.assert_called_once()


class TestBaseMonitor:
    """Tests for BaseMonitor functionality."""

    def test_check_result_creation(self):
        """Test CheckResult dataclass."""
        result = CheckResult(
            status=Status.OK,
            message="Test message",
            details={"key": "value"},
        )

        assert result.status == Status.OK
        assert result.message == "Test message"
        assert result.details["key"] == "value"
        assert result.timestamp is not None

    def test_status_enum_values(self):
        """Test Status enum values."""
        assert Status.OK.value == "ok"
        assert Status.WARNING.value == "warning"
        assert Status.CRITICAL.value == "critical"
        assert Status.UNKNOWN.value == "unknown"
