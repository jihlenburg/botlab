"""Alert management with routing and deduplication."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import aiosmtplib
import httpx
import structlog
from prometheus_client import Counter

from src.config import AlertingSettings

logger = structlog.get_logger(__name__)

# Prometheus metrics
ALERTS_SENT = Counter("admin_bot_alerts_sent_total", "Total alerts sent", ["severity", "channel"])
ALERTS_SUPPRESSED = Counter("admin_bot_alerts_suppressed_total", "Alerts suppressed by cooldown")


@dataclass
class Alert:
    """Alert data structure."""

    severity: str  # critical, warning, info
    title: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    alert_id: str = ""

    def __post_init__(self):
        if not self.alert_id:
            # Generate deterministic ID from title and severity
            content = f"{self.severity}:{self.title}"
            self.alert_id = hashlib.md5(content.encode()).hexdigest()[:12]


class AlertManager:
    """Manages alert routing, deduplication, and delivery."""

    def __init__(self, settings: AlertingSettings) -> None:
        self.settings = settings
        self._sent_alerts: dict[str, datetime] = {}  # alert_id -> last_sent
        self._alert_history: list[Alert] = []

    async def send_alert(
        self,
        severity: str,
        title: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """
        Send an alert through configured channels.

        Args:
            severity: Alert severity (critical, warning, info)
            title: Alert title
            message: Alert message
            details: Additional details

        Returns:
            True if alert was sent, False if suppressed
        """
        alert = Alert(
            severity=severity,
            title=title,
            message=message,
            details=details or {},
        )

        # Check cooldown
        if not self._should_send(alert):
            logger.debug(
                "Alert suppressed by cooldown",
                alert_id=alert.alert_id,
                title=title,
            )
            ALERTS_SUPPRESSED.inc()
            return False

        # Record alert
        self._sent_alerts[alert.alert_id] = datetime.now()
        self._alert_history.append(alert)
        if len(self._alert_history) > 1000:
            self._alert_history = self._alert_history[-1000:]

        logger.info(
            "Sending alert",
            severity=severity,
            title=title,
            alert_id=alert.alert_id,
        )

        # Send via configured channels
        success = False

        if self.settings.email_enabled:
            try:
                await self._send_email(alert)
                ALERTS_SENT.labels(severity=severity, channel="email").inc()
                success = True
            except Exception as e:
                logger.error("Email alert failed", error=str(e))

        if self.settings.webhook_enabled and self.settings.webhook_url:
            try:
                await self._send_webhook(alert)
                ALERTS_SENT.labels(severity=severity, channel="webhook").inc()
                success = True
            except Exception as e:
                logger.error("Webhook alert failed", error=str(e))

        return success

    def _should_send(self, alert: Alert) -> bool:
        """Check if alert should be sent based on cooldown."""
        if alert.alert_id not in self._sent_alerts:
            return True

        last_sent = self._sent_alerts[alert.alert_id]
        cooldown = timedelta(minutes=self.settings.cooldown_minutes)

        return datetime.now() - last_sent > cooldown

    async def _send_email(self, alert: Alert) -> None:
        """Send alert via email."""
        if not self.settings.email_recipients:
            logger.warning("No email recipients configured")
            return

        # Create email
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{alert.severity.upper()}] {alert.title}"
        msg["From"] = self.settings.email_from
        msg["To"] = ", ".join(self.settings.email_recipients)

        # Plain text body
        text_body = f"""
GitLab Admin Bot Alert
======================

Severity: {alert.severity.upper()}
Time: {alert.timestamp.isoformat()}

{alert.title}
{'-' * len(alert.title)}

{alert.message}

Details:
{self._format_details(alert.details)}

--
GitLab Admin Bot
"""

        # HTML body
        html_body = f"""
<html>
<body>
<h2 style="color: {self._severity_color(alert.severity)};">
    [{alert.severity.upper()}] {alert.title}
</h2>
<p><strong>Time:</strong> {alert.timestamp.isoformat()}</p>
<p>{alert.message}</p>

<h3>Details</h3>
<pre>{self._format_details(alert.details)}</pre>

<hr>
<p style="color: #666; font-size: 12px;">GitLab Admin Bot</p>
</body>
</html>
"""

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        # Send email
        await aiosmtplib.send(
            msg,
            hostname=self.settings.email_smtp_host,
            port=self.settings.email_smtp_port,
            username=self.settings.email_smtp_user,
            password=self.settings.email_smtp_password.get_secret_value(),
            start_tls=True,
        )

        logger.debug("Email alert sent", recipients=self.settings.email_recipients)

    async def _send_webhook(self, alert: Alert) -> None:
        """Send alert via webhook (Slack/Mattermost compatible)."""
        payload = {
            "text": f"*[{alert.severity.upper()}] {alert.title}*",
            "attachments": [
                {
                    "color": self._severity_color(alert.severity),
                    "title": alert.title,
                    "text": alert.message,
                    "fields": [
                        {"title": "Severity", "value": alert.severity, "short": True},
                        {"title": "Time", "value": alert.timestamp.isoformat(), "short": True},
                    ],
                    "footer": "GitLab Admin Bot",
                }
            ],
        }

        # Add details as fields
        for key, value in alert.details.items():
            if isinstance(value, (str, int, float, bool)):
                payload["attachments"][0]["fields"].append(
                    {"title": key, "value": str(value), "short": True}
                )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.settings.webhook_url,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()

        logger.debug("Webhook alert sent")

    def _format_details(self, details: dict[str, Any]) -> str:
        """Format details dictionary for display."""
        lines = []
        for key, value in details.items():
            if isinstance(value, dict):
                lines.append(f"{key}:")
                for k, v in value.items():
                    lines.append(f"  {k}: {v}")
            else:
                lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def _severity_color(self, severity: str) -> str:
        """Get color for severity level."""
        colors = {
            "critical": "#dc3545",  # Red
            "warning": "#ffc107",   # Yellow
            "info": "#17a2b8",      # Blue
        }
        return colors.get(severity, "#6c757d")  # Gray default

    def get_history(self, limit: int = 50) -> list[Alert]:
        """Get recent alert history."""
        return self._alert_history[-limit:]

    def clear_cooldown(self, alert_id: str | None = None) -> None:
        """Clear alert cooldown."""
        if alert_id:
            self._sent_alerts.pop(alert_id, None)
        else:
            self._sent_alerts.clear()
        logger.info("Alert cooldown cleared", alert_id=alert_id)
