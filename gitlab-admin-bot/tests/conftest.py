"""Shared pytest fixtures and configuration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from src.config import (
    AlertingSettings,
    BackupSettings,
    ClaudeSettings,
    GitLabSettings,
    HetznerSettings,
    MonitoringSettings,
    Settings,
)
from src.alerting.manager import AlertManager
from src.monitors.base import CheckResult, Status
from src.utils.ssh import SSHClient


@pytest.fixture
def gitlab_settings() -> GitLabSettings:
    """Create test GitLab settings."""
    return GitLabSettings(
        url="https://gitlab.test.local",
        private_token=SecretStr("test-token-12345"),
        ssh_host="10.0.1.10",
        ssh_user="gitlab-admin",
        ssh_key_path=Path("/tmp/test_key"),
    )


@pytest.fixture
def hetzner_settings() -> HetznerSettings:
    """Create test Hetzner settings."""
    return HetznerSettings(
        api_token=SecretStr("test-hetzner-token"),
        location="fsn1",
    )


@pytest.fixture
def backup_settings() -> BackupSettings:
    """Create test backup settings."""
    return BackupSettings(
        borg_repo="ssh://backup@storage.test.local/./borg",
        borg_passphrase=SecretStr("test-borg-passphrase"),
        local_backup_path=Path("/var/opt/gitlab/backups"),
        max_backup_age_hours=4,
    )


@pytest.fixture
def alerting_settings() -> AlertingSettings:
    """Create test alerting settings."""
    return AlertingSettings(
        email_enabled=True,
        email_smtp_host="smtp.test.local",
        email_smtp_port=587,
        email_smtp_user="test@test.local",
        email_smtp_password=SecretStr("test-smtp-password"),
        email_from="admin-bot@test.local",
        email_recipients=["admin@test.local"],
        webhook_enabled=False,
        webhook_url="",
        cooldown_minutes=60,
    )


@pytest.fixture
def claude_settings() -> ClaudeSettings:
    """Create test Claude settings."""
    return ClaudeSettings(
        enabled=True,
        api_key=SecretStr("test-anthropic-key"),
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        analysis_interval_minutes=30,
    )


@pytest.fixture
def monitoring_settings() -> MonitoringSettings:
    """Create test monitoring settings."""
    return MonitoringSettings(
        disk_warning_percent=80,
        disk_critical_percent=90,
        memory_warning_percent=80,
        memory_critical_percent=95,
        cpu_warning_percent=70,
        cpu_critical_percent=90,
        health_check_interval_seconds=30,
        resource_check_interval_seconds=60,
        backup_check_interval_minutes=15,
    )


@pytest.fixture
def settings(
    gitlab_settings: GitLabSettings,
    hetzner_settings: HetznerSettings,
    backup_settings: BackupSettings,
    alerting_settings: AlertingSettings,
    claude_settings: ClaudeSettings,
    monitoring_settings: MonitoringSettings,
) -> Settings:
    """Create full test settings."""
    return Settings(
        app_name="GitLab Admin Bot Test",
        debug=True,
        log_level="DEBUG",
        api_host="127.0.0.1",
        api_port=8080,
        data_dir=Path("/tmp/test-data"),
        db_path=Path("/tmp/test-data/admin_bot.db"),
        gitlab=gitlab_settings,
        hetzner=hetzner_settings,
        backup=backup_settings,
        alerting=alerting_settings,
        claude=claude_settings,
        monitoring=monitoring_settings,
    )


@pytest.fixture
def mock_alert_manager(alerting_settings: AlertingSettings) -> AlertManager:
    """Create an AlertManager with mocked send methods."""
    manager = AlertManager(alerting_settings)
    manager._send_email = AsyncMock()
    manager._send_webhook = AsyncMock()
    return manager


@pytest.fixture
def mock_ssh_client(gitlab_settings: GitLabSettings) -> MagicMock:
    """Create a mocked SSH client."""
    client = MagicMock(spec=SSHClient)
    client.run_command = AsyncMock(return_value="")
    client.check_file_exists = AsyncMock(return_value=True)
    client.get_file_info = AsyncMock(return_value={"exists": True, "size": 1000})
    client.close = MagicMock()
    return client


@pytest.fixture
def sample_health_status() -> dict[str, Any]:
    """Sample health check status."""
    return {
        "health": True,
        "readiness": True,
        "liveness": True,
        "response_time_seconds": 0.15,
    }


@pytest.fixture
def sample_resource_status() -> dict[str, Any]:
    """Sample resource status."""
    return {
        "disk": {
            "/": {"size": "100G", "used": "45G", "available": "55G", "percent": 45},
            "/var/opt/gitlab": {"size": "200G", "used": "80G", "available": "120G", "percent": 40},
        },
        "memory": {
            "total_mb": 16384,
            "used_mb": 8192,
            "available_mb": 8192,
            "used_percent": 50.0,
            "swap_total_mb": 4096,
            "swap_used_mb": 512,
            "swap_percent": 12.5,
        },
        "cpu": {
            "cpu_count": 4,
            "load_avg": {"1m": 0.5, "5m": 0.6, "15m": 0.7},
        },
    }


@pytest.fixture
def sample_backup_status() -> dict[str, Any]:
    """Sample backup status."""
    return {
        "local": {
            "exists": True,
            "filename": "/var/opt/gitlab/backups/1704067200_2024_01_01_16.7.0_gitlab_backup.tar",
            "size_gb": 5.2,
            "timestamp": "2024-01-01T12:00:00",
            "age_hours": 1.5,
        },
        "borg": {
            "archive": "gitlab-2024-01-01-12-00",
            "timestamp": "2024-01-01 12:00:00",
            "accessible": True,
        },
        "log": {
            "recent_errors": None,
            "error_count": 0,
        },
    }


@pytest.fixture
def sample_check_result_ok() -> CheckResult:
    """Sample OK check result."""
    return CheckResult(
        status=Status.OK,
        message="All checks passed",
        details={"test": True},
        timestamp=datetime.now(),
    )


@pytest.fixture
def sample_check_result_critical() -> CheckResult:
    """Sample CRITICAL check result."""
    return CheckResult(
        status=Status.CRITICAL,
        message="Health check failed",
        details={"error": "Connection refused"},
        timestamp=datetime.now(),
    )


class MockHttpxResponse:
    """Mock httpx response for testing."""

    def __init__(self, status_code: int = 200, text: str = "OK", json_data: dict | None = None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data or {}

    def json(self) -> dict:
        return self._json_data


@pytest.fixture
def mock_httpx_client():
    """Create a mocked httpx client context manager."""

    class MockAsyncClient:
        def __init__(self, responses: dict[str, MockHttpxResponse] | None = None):
            self.responses = responses or {}
            self.default_response = MockHttpxResponse(200, "OK")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url: str, **kwargs) -> MockHttpxResponse:
            for pattern, response in self.responses.items():
                if pattern in url:
                    return response
            return self.default_response

        async def post(self, url: str, **kwargs) -> MockHttpxResponse:
            for pattern, response in self.responses.items():
                if pattern in url:
                    return response
            return self.default_response

    return MockAsyncClient


@pytest.fixture
def mock_hcloud_client():
    """Create a mocked Hetzner Cloud client."""
    client = MagicMock()

    # Mock server creation
    mock_server = MagicMock()
    mock_server.id = 12345
    mock_server.name = "gitlab-test"
    mock_server.public_net.ipv4.ip = "10.0.0.1"

    mock_action = MagicMock()
    mock_action.id = 1
    mock_action.status = "success"

    mock_response = MagicMock()
    mock_response.server = mock_server
    mock_response.action = mock_action

    client.servers.create.return_value = mock_response
    client.servers.delete.return_value = None
    client.servers.get_all.return_value = [mock_server]

    client.actions.get_by_id.return_value = mock_action

    client.ssh_keys.get_all.return_value = []

    client.volumes.get_all.return_value = []

    return client


@pytest.fixture
def mock_anthropic_response():
    """Create a mock Anthropic API response."""

    class MockContent:
        def __init__(self, text: str):
            self.text = text

    class MockMessage:
        def __init__(self, text: str):
            self.content = [MockContent(text)]

    def create_response(text: str = None):
        if text is None:
            text = """{
                "summary": "System is healthy",
                "actions_needed": false,
                "urgency": "info",
                "recommendations": ["Continue monitoring"],
                "actions": []
            }"""
        return MockMessage(text)

    return create_response
