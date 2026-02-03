"""Resource monitoring (CPU, memory, disk)."""

from __future__ import annotations

import re
import time
from typing import Any

import structlog
from prometheus_client import Gauge

from src.alerting.manager import AlertManager
from src.config import MonitoringSettings
from src.monitors.base import CHECK_DURATION, BaseMonitor, CheckResult, Status
from src.utils.ssh import SSHClient

logger = structlog.get_logger(__name__)

# Prometheus metrics
DISK_USAGE_PERCENT = Gauge(
    "gitlab_disk_usage_percent", "Disk usage percentage", ["mountpoint"]
)
MEMORY_USAGE_PERCENT = Gauge("gitlab_memory_usage_percent", "Memory usage percentage")
CPU_LOAD_AVG = Gauge("gitlab_cpu_load_average", "CPU load average", ["period"])
SWAP_USAGE_PERCENT = Gauge("gitlab_swap_usage_percent", "Swap usage percentage")


class ResourceMonitor(BaseMonitor):
    """Monitor GitLab server resources via SSH."""

    name = "resources"

    def __init__(
        self,
        ssh_client: SSHClient,
        alert_manager: AlertManager,
        thresholds: MonitoringSettings,
    ) -> None:
        super().__init__()
        self.ssh = ssh_client
        self.alerts = alert_manager
        self.thresholds = thresholds
        self._last_status: dict[str, Any] = {}

    async def check(self) -> CheckResult:
        """Check resource usage on GitLab server."""
        start_time = time.time()
        issues: list[str] = []
        details: dict[str, Any] = {}

        try:
            # Get disk usage
            disk = await self._check_disk()
            details["disk"] = disk
            for mountpoint, usage in disk.items():
                DISK_USAGE_PERCENT.labels(mountpoint=mountpoint).set(usage["percent"])
                if usage["percent"] >= self.thresholds.disk_critical_percent:
                    issues.append(f"CRITICAL: Disk {mountpoint} at {usage['percent']}%")
                elif usage["percent"] >= self.thresholds.disk_warning_percent:
                    issues.append(f"WARNING: Disk {mountpoint} at {usage['percent']}%")

            # Get memory usage
            memory = await self._check_memory()
            details["memory"] = memory
            MEMORY_USAGE_PERCENT.set(memory["used_percent"])
            SWAP_USAGE_PERCENT.set(memory.get("swap_percent", 0))

            if memory["used_percent"] >= self.thresholds.memory_critical_percent:
                issues.append(f"CRITICAL: Memory at {memory['used_percent']}%")
            elif memory["used_percent"] >= self.thresholds.memory_warning_percent:
                issues.append(f"WARNING: Memory at {memory['used_percent']}%")

            # Get CPU load
            cpu = await self._check_cpu()
            details["cpu"] = cpu
            for period, value in cpu.get("load_avg", {}).items():
                CPU_LOAD_AVG.labels(period=period).set(value)

            # Check load average (15 min)
            load_15 = cpu.get("load_avg", {}).get("15m", 0)
            cpu_count = cpu.get("cpu_count", 4)
            load_percent = (load_15 / cpu_count) * 100

            if load_percent >= self.thresholds.cpu_critical_percent:
                issues.append(f"CRITICAL: CPU load at {load_percent:.1f}%")
            elif load_percent >= self.thresholds.cpu_warning_percent:
                issues.append(f"WARNING: CPU load at {load_percent:.1f}%")

        except Exception as e:
            logger.error("Resource check failed", error=str(e))
            issues.append(f"Resource check error: {e}")
            details["error"] = str(e)

        # Calculate duration
        duration = time.time() - start_time
        CHECK_DURATION.labels(monitor=self.name).set(duration)

        # Determine status
        if any("CRITICAL" in i for i in issues):
            status = Status.CRITICAL
            severity = "critical"
        elif any("WARNING" in i for i in issues):
            status = Status.WARNING
            severity = "warning"
        else:
            status = Status.OK
            severity = None

        message = "; ".join(issues) if issues else "All resources within thresholds"

        # Send alert if needed
        if severity:
            await self.alerts.send_alert(
                severity=severity,
                title="GitLab Resource Alert",
                message=message,
                details=details,
            )

        result = CheckResult(status=status, message=message, details=details)
        self.record_result(result)
        self._last_status = details

        return result

    async def _check_disk(self) -> dict[str, Any]:
        """Check disk usage."""
        # Run df command via SSH
        df_cmd = "df -h /var/opt/gitlab /var/opt/gitlab/backups 2>/dev/null || df -h /"
        output = await self.ssh.run_command(df_cmd)

        disk_info = {}
        for line in output.strip().split("\n")[1:]:  # Skip header
            parts = line.split()
            if len(parts) >= 6:
                mountpoint = parts[5]
                # Parse percentage (remove %)
                percent_str = parts[4].rstrip("%")
                try:
                    percent = int(percent_str)
                except ValueError:
                    continue

                disk_info[mountpoint] = {
                    "size": parts[1],
                    "used": parts[2],
                    "available": parts[3],
                    "percent": percent,
                }

        return disk_info

    async def _check_memory(self) -> dict[str, Any]:
        """Check memory usage."""
        output = await self.ssh.run_command("free -m")

        memory_info: dict[str, Any] = {}
        for line in output.strip().split("\n"):
            if line.startswith("Mem:"):
                parts = line.split()
                total = int(parts[1])
                used = int(parts[2])
                available = int(parts[6]) if len(parts) > 6 else total - used

                memory_info["total_mb"] = total
                memory_info["used_mb"] = used
                memory_info["available_mb"] = available
                memory_info["used_percent"] = round((used / total) * 100, 1)

            elif line.startswith("Swap:"):
                parts = line.split()
                total = int(parts[1])
                used = int(parts[2])

                memory_info["swap_total_mb"] = total
                memory_info["swap_used_mb"] = used
                if total > 0:
                    memory_info["swap_percent"] = round((used / total) * 100, 1)
                else:
                    memory_info["swap_percent"] = 0

        return memory_info

    async def _check_cpu(self) -> dict[str, Any]:
        """Check CPU load."""
        # Get load average
        load_output = await self.ssh.run_command("uptime")
        cpu_count_output = await self.ssh.run_command("nproc")

        cpu_info = {
            "cpu_count": int(cpu_count_output.strip()),
            "load_avg": {},
        }

        # Parse load average from uptime output
        # Format: ... load average: 0.50, 0.60, 0.70
        match = re.search(r"load average:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)", load_output)
        if match:
            cpu_info["load_avg"] = {
                "1m": float(match.group(1)),
                "5m": float(match.group(2)),
                "15m": float(match.group(3)),
            }

        return cpu_info

    async def get_status(self) -> dict[str, Any]:
        """Get current resource status."""
        return {
            "last_check": self._last_result.timestamp.isoformat() if self._last_result else None,
            "status": self._last_result.status.value if self._last_result else "unknown",
            **self._last_status,
        }
