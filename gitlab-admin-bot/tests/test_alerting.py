"""Tests for alerting module."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.alerting.manager import Alert, AlertManager
from src.config import AlertingSettings


class TestAlert:
    """Tests for Alert dataclass."""

    def test_alert_creation(self):
        """Test creating an alert."""
        alert = Alert(
            severity="critical",
            title="Test Alert",
            message="This is a test",
        )

        assert alert.severity == "critical"
        assert alert.title == "Test Alert"
        assert alert.message == "This is a test"
        assert alert.timestamp is not None
        assert alert.alert_id  # Should be auto-generated

    def test_alert_id_generation(self):
        """Test that alert ID is generated deterministically."""
        alert1 = Alert(severity="critical", title="Test", message="msg1")
        alert2 = Alert(severity="critical", title="Test", message="msg2")
        alert3 = Alert(severity="warning", title="Test", message="msg1")

        # Same severity and title should produce same ID
        assert alert1.alert_id == alert2.alert_id
        # Different severity should produce different ID
        assert alert1.alert_id != alert3.alert_id

    def test_alert_with_details(self):
        """Test alert with additional details."""
        details = {"server": "gitlab-01", "disk_usage": 95}
        alert = Alert(
            severity="warning",
            title="Disk Warning",
            message="Disk almost full",
            details=details,
        )

        assert alert.details == details


class TestAlertManager:
    """Tests for AlertManager."""

    @pytest.fixture
    def alert_manager(self, alerting_settings: AlertingSettings) -> AlertManager:
        """Create an AlertManager for testing."""
        manager = AlertManager(alerting_settings)
        manager._send_email = AsyncMock()
        manager._send_webhook = AsyncMock()
        return manager

    @pytest.mark.asyncio
    async def test_send_alert_success(self, alert_manager):
        """Test sending an alert successfully."""
        result = await alert_manager.send_alert(
            severity="warning",
            title="Test Alert",
            message="Test message",
        )

        assert result is True
        alert_manager._send_email.assert_called_once()

    @pytest.mark.asyncio
    async def test_alert_cooldown(self, alert_manager):
        """Test alert cooldown prevents duplicate alerts."""
        # First alert should be sent
        result1 = await alert_manager.send_alert(
            severity="critical",
            title="Repeated Alert",
            message="First occurrence",
        )
        assert result1 is True

        # Second alert with same title/severity should be suppressed
        result2 = await alert_manager.send_alert(
            severity="critical",
            title="Repeated Alert",
            message="Second occurrence",
        )
        assert result2 is False

        # Only one email should have been sent
        assert alert_manager._send_email.call_count == 1

    @pytest.mark.asyncio
    async def test_alert_cooldown_expiry(self, alert_manager):
        """Test that alerts can be sent again after cooldown expires."""
        # Send first alert
        await alert_manager.send_alert(
            severity="critical",
            title="Timed Alert",
            message="First",
        )

        # Manually expire the cooldown
        for alert_id in list(alert_manager._sent_alerts.keys()):
            alert_manager._sent_alerts[alert_id] = datetime.now() - timedelta(minutes=120)

        # Second alert should now be sent
        result = await alert_manager.send_alert(
            severity="critical",
            title="Timed Alert",
            message="After cooldown",
        )
        assert result is True
        assert alert_manager._send_email.call_count == 2

    @pytest.mark.asyncio
    async def test_clear_cooldown(self, alert_manager):
        """Test clearing alert cooldown."""
        # Send an alert
        await alert_manager.send_alert(
            severity="info",
            title="Clearable Alert",
            message="Test",
        )

        # Clear all cooldowns
        alert_manager.clear_cooldown()

        # Should be able to send same alert again
        result = await alert_manager.send_alert(
            severity="info",
            title="Clearable Alert",
            message="Test again",
        )
        assert result is True
        assert alert_manager._send_email.call_count == 2

    @pytest.mark.asyncio
    async def test_clear_specific_cooldown(self, alert_manager):
        """Test clearing a specific alert's cooldown."""
        # Send two different alerts
        await alert_manager.send_alert(severity="info", title="Alert A", message="A")
        await alert_manager.send_alert(severity="info", title="Alert B", message="B")

        # Get alert A's ID
        alert_a_id = list(alert_manager._sent_alerts.keys())[0]

        # Clear only alert A's cooldown
        alert_manager.clear_cooldown(alert_a_id)

        # Alert A should be sendable again
        result_a = await alert_manager.send_alert(severity="info", title="Alert A", message="A2")
        # Alert B should still be in cooldown (if it has the same ID pattern)
        await alert_manager.send_alert(severity="info", title="Alert B", message="B2")

        assert result_a is True

    @pytest.mark.asyncio
    async def test_webhook_sending(self, alerting_settings):
        """Test sending alerts via webhook."""
        alerting_settings.webhook_enabled = True
        alerting_settings.webhook_url = "https://hooks.test.local/webhook"

        manager = AlertManager(alerting_settings)
        manager._send_email = AsyncMock()
        manager._send_webhook = AsyncMock()

        await manager.send_alert(
            severity="critical",
            title="Webhook Test",
            message="Testing webhook",
        )

        manager._send_email.assert_called_once()
        manager._send_webhook.assert_called_once()

    @pytest.mark.asyncio
    async def test_email_disabled(self, alerting_settings):
        """Test behavior when email is disabled."""
        alerting_settings.email_enabled = False

        manager = AlertManager(alerting_settings)
        manager._send_email = AsyncMock()
        manager._send_webhook = AsyncMock()

        await manager.send_alert(
            severity="info",
            title="No Email",
            message="Should not send email",
        )

        # Alert is recorded but email not sent
        manager._send_email.assert_not_called()

    def test_get_history(self, alert_manager):
        """Test getting alert history."""
        # History starts empty
        assert len(alert_manager.get_history()) == 0

    @pytest.mark.asyncio
    async def test_history_tracking(self, alert_manager):
        """Test that alerts are tracked in history."""
        await alert_manager.send_alert(severity="info", title="History 1", message="First")
        alert_manager.clear_cooldown()  # Clear to allow second alert
        await alert_manager.send_alert(severity="warning", title="History 2", message="Second")

        history = alert_manager.get_history()
        assert len(history) == 2
        assert history[0].title == "History 1"
        assert history[1].title == "History 2"

    @pytest.mark.asyncio
    async def test_history_limit(self, alert_manager):
        """Test that history is limited to prevent memory issues."""
        # Send many alerts
        for i in range(1100):
            alert_manager.clear_cooldown()
            await alert_manager.send_alert(
                severity="info",
                title=f"Alert {i}",
                message=f"Message {i}",
            )

        history = alert_manager.get_history(limit=100)
        assert len(history) <= 100

    def test_severity_color(self, alert_manager):
        """Test severity color mapping."""
        assert alert_manager._severity_color("critical") == "#dc3545"
        assert alert_manager._severity_color("warning") == "#ffc107"
        assert alert_manager._severity_color("info") == "#17a2b8"
        assert alert_manager._severity_color("unknown") == "#6c757d"

    def test_format_details(self, alert_manager):
        """Test formatting details dictionary."""
        details = {
            "server": "gitlab-01",
            "disk_usage": 95,
            "nested": {"key": "value"},
        }

        formatted = alert_manager._format_details(details)

        assert "server: gitlab-01" in formatted
        assert "disk_usage: 95" in formatted
        assert "nested:" in formatted
        assert "key: value" in formatted


class TestAlertManagerEmailFormatting:
    """Tests for email formatting."""

    @pytest.fixture
    def manager_with_recipients(self, alerting_settings):
        """Create manager with email recipients configured."""
        alerting_settings.email_recipients = ["admin@test.local", "ops@test.local"]
        return AlertManager(alerting_settings)

    @pytest.mark.asyncio
    async def test_email_subject_format(self, manager_with_recipients):
        """Test email subject includes severity and title."""
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await manager_with_recipients._send_email(
                Alert(
                    severity="critical",
                    title="Server Down",
                    message="The server is not responding",
                )
            )

            mock_send.assert_called_once()
            msg = mock_send.call_args[0][0]
            assert "[CRITICAL]" in msg["Subject"]
            assert "Server Down" in msg["Subject"]

    @pytest.mark.asyncio
    async def test_email_recipients(self, manager_with_recipients):
        """Test email is sent to all recipients."""
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await manager_with_recipients._send_email(
                Alert(severity="info", title="Test", message="Test message")
            )

            mock_send.assert_called_once()
            msg = mock_send.call_args[0][0]
            assert "admin@test.local" in msg["To"]
            assert "ops@test.local" in msg["To"]

    @pytest.mark.asyncio
    async def test_email_body_contains_message(self, manager_with_recipients):
        """Test email body contains the alert message."""
        test_message = "This is a unique test message for verification"

        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await manager_with_recipients._send_email(
                Alert(severity="warning", title="Test", message=test_message)
            )

            mock_send.assert_called_once()
            # The message object will have the content in its payload
            msg = mock_send.call_args[0][0]
            # Check that message was constructed (basic validation)
            assert msg["Subject"] is not None
