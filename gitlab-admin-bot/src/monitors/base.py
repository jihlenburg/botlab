"""Base monitor class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

import structlog
from prometheus_client import Counter, Gauge

logger = structlog.get_logger(__name__)


class Status(StrEnum):
    """Monitor status levels."""

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class CheckResult:
    """Result of a monitor check."""

    status: Status
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


# Prometheus metrics
CHECK_COUNTER = Counter(
    "admin_bot_checks_total",
    "Total number of monitoring checks",
    ["monitor", "status"],
)

CHECK_DURATION = Gauge(
    "admin_bot_check_duration_seconds",
    "Duration of monitoring check",
    ["monitor"],
)


class BaseMonitor(ABC):
    """Base class for all monitors."""

    name: str = "base"

    def __init__(self) -> None:
        self._last_result: CheckResult | None = None
        self._consecutive_failures = 0

    @abstractmethod
    async def check(self) -> CheckResult:
        """Perform the monitoring check."""
        pass

    @abstractmethod
    async def get_status(self) -> dict[str, Any]:
        """Get current status as a dictionary."""
        pass

    def get_last_result(self) -> CheckResult | None:
        """Get the last check result."""
        return self._last_result

    def record_result(self, result: CheckResult) -> None:
        """Record a check result."""
        self._last_result = result

        # Update Prometheus metrics
        CHECK_COUNTER.labels(monitor=self.name, status=result.status.value).inc()

        # Track consecutive failures
        if result.status == Status.CRITICAL:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0

        logger.debug(
            "Check completed",
            monitor=self.name,
            status=result.status.value,
            message=result.message,
        )
