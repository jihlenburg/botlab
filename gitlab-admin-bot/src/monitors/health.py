"""GitLab health monitoring."""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog
from prometheus_client import Gauge

from src.monitors.base import BaseMonitor, CheckResult, Status, CHECK_DURATION
from src.alerting.manager import AlertManager
from src.utils.gitlab_api import GitLabClient

logger = structlog.get_logger(__name__)

# Prometheus metrics
GITLAB_UP = Gauge("gitlab_up", "GitLab is accessible")
GITLAB_RESPONSE_TIME = Gauge("gitlab_response_time_seconds", "GitLab response time")


class HealthMonitor(BaseMonitor):
    """Monitor GitLab health endpoints."""

    name = "health"

    def __init__(
        self,
        gitlab_client: GitLabClient,
        alert_manager: AlertManager,
    ) -> None:
        super().__init__()
        self.gitlab = gitlab_client
        self.alerts = alert_manager
        self._health_url = f"{gitlab_client.url}/-/health"
        self._readiness_url = f"{gitlab_client.url}/-/readiness"
        self._liveness_url = f"{gitlab_client.url}/-/liveness"
        self._last_status: dict[str, Any] = {}

    async def check(self) -> CheckResult:
        """Check GitLab health endpoints."""
        start_time = time.time()
        issues = []
        details = {}

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
                # Health check
                health_ok = await self._check_endpoint(client, self._health_url, "health")
                details["health"] = health_ok

                # Readiness check
                readiness_ok = await self._check_endpoint(
                    client, self._readiness_url, "readiness"
                )
                details["readiness"] = readiness_ok

                # Liveness check
                liveness_ok = await self._check_endpoint(
                    client, self._liveness_url, "liveness"
                )
                details["liveness"] = liveness_ok

                if not health_ok:
                    issues.append("Health check failed")
                if not readiness_ok:
                    issues.append("Readiness check failed")
                if not liveness_ok:
                    issues.append("Liveness check failed")

        except httpx.TimeoutException:
            issues.append("Health check timed out")
            details["error"] = "timeout"
        except httpx.HTTPError as e:
            issues.append(f"HTTP error: {e}")
            details["error"] = str(e)
        except Exception as e:
            issues.append(f"Unexpected error: {e}")
            details["error"] = str(e)

        # Calculate response time
        duration = time.time() - start_time
        CHECK_DURATION.labels(monitor=self.name).set(duration)
        GITLAB_RESPONSE_TIME.set(duration)
        details["response_time_seconds"] = duration

        # Determine status
        if issues:
            status = Status.CRITICAL
            message = "; ".join(issues)
            GITLAB_UP.set(0)

            # Send alert
            await self.alerts.send_alert(
                severity="critical",
                title="GitLab Health Check Failed",
                message=message,
                details=details,
            )
        else:
            status = Status.OK
            message = f"All health checks passed ({duration:.2f}s)"
            GITLAB_UP.set(1)

        result = CheckResult(status=status, message=message, details=details)
        self.record_result(result)
        self._last_status = details

        return result

    async def _check_endpoint(
        self,
        client: httpx.AsyncClient,
        url: str,
        name: str,
    ) -> bool:
        """Check a single health endpoint."""
        try:
            response = await client.get(url)
            ok = response.status_code == 200

            if not ok:
                logger.warning(
                    "Health endpoint returned non-200",
                    endpoint=name,
                    status_code=response.status_code,
                    body=response.text[:200],
                )

            return ok
        except Exception as e:
            logger.error("Health endpoint check failed", endpoint=name, error=str(e))
            return False

    async def get_status(self) -> dict[str, Any]:
        """Get current health status."""
        return {
            "last_check": self._last_result.timestamp.isoformat() if self._last_result else None,
            "status": self._last_result.status.value if self._last_result else "unknown",
            "endpoints": self._last_status,
            "consecutive_failures": self._consecutive_failures,
        }
