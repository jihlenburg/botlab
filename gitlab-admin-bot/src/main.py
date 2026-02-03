"""GitLab Admin Bot - Main entry point."""

from __future__ import annotations

import signal
import sys
import types
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI
from prometheus_client import make_asgi_app

from src.ai.analyst import AIAnalyst, RecommendedAction
from src.alerting.manager import AlertManager
from src.config import get_settings
from src.maintenance.tasks import MaintenanceRunner
from src.monitors.backup import BackupMonitor
from src.monitors.health import HealthMonitor
from src.monitors.resources import ResourceMonitor
from src.scheduler import Scheduler
from src.utils.gitlab_api import GitLabClient
from src.utils.ssh import SSHClient

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class AdminBot:
    """Main Admin Bot application."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.scheduler: Scheduler | None = None
        self.alert_manager: AlertManager | None = None
        self.gitlab_client: GitLabClient | None = None
        self.ssh_client: SSHClient | None = None
        self.ai_analyst: AIAnalyst | None = None

        # Monitors
        self.health_monitor: HealthMonitor | None = None
        self.resource_monitor: ResourceMonitor | None = None
        self.backup_monitor: BackupMonitor | None = None

        # Maintenance
        self.maintenance: MaintenanceRunner | None = None

    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("Initializing Admin Bot", version="1.0.0")

        # Initialize clients
        self.gitlab_client = GitLabClient(self.settings.gitlab)
        self.ssh_client = SSHClient(self.settings.gitlab)

        # Initialize alert manager
        self.alert_manager = AlertManager(self.settings.alerting)

        # Initialize AI analyst (Claude API)
        if self.settings.claude.enabled:
            self.ai_analyst = AIAnalyst(self.settings.claude)
            logger.info("AI Analyst enabled", model=self.settings.claude.model)

        # Initialize maintenance runner
        self.maintenance = MaintenanceRunner(
            ssh_client=self.ssh_client,
            alert_manager=self.alert_manager,
        )

        # Initialize monitors
        self.health_monitor = HealthMonitor(
            gitlab_client=self.gitlab_client,
            alert_manager=self.alert_manager,
        )
        self.resource_monitor = ResourceMonitor(
            ssh_client=self.ssh_client,
            alert_manager=self.alert_manager,
            thresholds=self.settings.monitoring,
        )
        self.backup_monitor = BackupMonitor(
            ssh_client=self.ssh_client,
            alert_manager=self.alert_manager,
            settings=self.settings.backup,
        )

        # Initialize scheduler
        self.scheduler = Scheduler()
        self._schedule_jobs()

        logger.info("Admin Bot initialized successfully")

    def _schedule_jobs(self) -> None:
        """Schedule all monitoring and maintenance jobs."""
        if not self.scheduler:
            return

        settings = self.settings.monitoring

        # Health checks
        if self.health_monitor:
            self.scheduler.add_job(
                self.health_monitor.check,
                "interval",
                seconds=settings.health_check_interval_seconds,
                id="health_check",
                name="GitLab Health Check",
            )

        # Resource monitoring
        if self.resource_monitor:
            self.scheduler.add_job(
                self.resource_monitor.check,
                "interval",
                seconds=settings.resource_check_interval_seconds,
                id="resource_check",
                name="Resource Monitor",
            )

        # Backup monitoring
        if self.backup_monitor:
            self.scheduler.add_job(
                self.backup_monitor.check,
                "interval",
                minutes=settings.backup_check_interval_minutes,
                id="backup_check",
                name="Backup Monitor",
            )

        # AI analysis (if enabled)
        if self.ai_analyst:
            self.scheduler.add_job(
                self._run_ai_analysis,
                "interval",
                minutes=self.settings.claude.analysis_interval_minutes,
                id="ai_analysis",
                name="AI Admin Analysis",
            )

        # Daily maintenance tasks (03:00 UTC)
        self.scheduler.add_job(
            self._daily_maintenance,
            "cron",
            hour=3,
            minute=0,
            id="daily_maintenance",
            name="Daily Maintenance",
        )

        # Weekly tasks (Sunday 03:00 UTC)
        self.scheduler.add_job(
            self._weekly_maintenance,
            "cron",
            day_of_week="sun",
            hour=3,
            minute=0,
            id="weekly_maintenance",
            name="Weekly Maintenance",
        )

    async def _run_ai_analysis(self) -> None:
        """Run AI-powered analysis of system state."""
        if not self.ai_analyst:
            return

        try:
            if not self.health_monitor or not self.resource_monitor or not self.backup_monitor:
                logger.warning("Monitors not initialized, skipping AI analysis")
                return

            # Gather system state
            health_status = await self.health_monitor.get_status()
            resource_status = await self.resource_monitor.get_status()
            backup_status = await self.backup_monitor.get_status()

            # Ask Claude to analyze and recommend actions
            analysis = await self.ai_analyst.analyze_system_state(
                health=health_status,
                resources=resource_status,
                backup=backup_status,
            )

            if analysis.actions_needed:
                logger.info(
                    "AI analysis recommends actions",
                    recommendations=analysis.recommendations,
                    urgency=analysis.urgency,
                )

                # Execute recommended actions if auto-remediation is enabled
                for action in analysis.recommended_actions:
                    if action.auto_execute:
                        await self._execute_action(action)
                    elif self.alert_manager:
                        # Alert admins about recommended action
                        await self.alert_manager.send_alert(
                            severity="info",
                            title="AI Recommendation",
                            message=f"{action.description}\n\nReason: {action.reason}",
                        )

        except Exception as e:
            logger.error("AI analysis failed", error=str(e))

    async def _execute_action(self, action: RecommendedAction) -> None:
        """Execute a recommended maintenance action."""
        logger.info("Executing recommended action", action=action.name)
        # Implementation depends on action type
        pass

    async def _daily_maintenance(self) -> None:
        """Daily maintenance tasks."""
        logger.info("Running daily maintenance")

        if not self.maintenance:
            logger.warning("Maintenance runner not initialized")
            return

        try:
            # Generate daily status report
            await self.maintenance.generate_daily_report()
            logger.info("Daily report generated", success=True)

            # Rotate logs
            result = await self.maintenance.rotate_logs()
            logger.info("Log rotation completed", success=result.get("success"))

            # Clean old artifacts
            result = await self.maintenance.cleanup_old_artifacts(days=30)
            logger.info("Artifact cleanup completed", success=result.get("success"))

        except Exception as e:
            logger.error("Daily maintenance failed", error=str(e))
            if self.alert_manager:
                await self.alert_manager.send_alert(
                    severity="warning",
                    title="Daily Maintenance Failed",
                    message=f"Daily maintenance encountered an error: {e}",
                )

    async def _weekly_maintenance(self) -> None:
        """Weekly maintenance tasks."""
        logger.info("Running weekly maintenance")

        if not self.maintenance:
            logger.warning("Maintenance runner not initialized")
            return

        try:
            # Container registry garbage collection
            result = await self.maintenance.cleanup_registry()
            logger.info("Registry GC completed", success=result.get("success"))

            # Database vacuum analyze
            result = await self.maintenance.database_vacuum()
            logger.info("Database vacuum completed", success=result.get("success"))

            # GitLab integrity check
            result = await self.maintenance.check_gitlab_integrity()
            logger.info("Integrity check completed", success=result.get("success"))

            # TODO: Backup restore test (requires RestoreTester integration)
            # This is a longer operation that provisions a test VM
            # Consider running it monthly or on-demand

        except Exception as e:
            logger.error("Weekly maintenance failed", error=str(e))
            if self.alert_manager:
                await self.alert_manager.send_alert(
                    severity="warning",
                    title="Weekly Maintenance Failed",
                    message=f"Weekly maintenance encountered an error: {e}",
                )

    async def start(self) -> None:
        """Start the scheduler and all monitoring."""
        if self.scheduler:
            self.scheduler.start()
            logger.info("Scheduler started")

    async def stop(self) -> None:
        """Stop all components gracefully."""
        logger.info("Stopping Admin Bot")

        if self.scheduler:
            self.scheduler.shutdown()

        if self.ssh_client:
            self.ssh_client.close()

        logger.info("Admin Bot stopped")


# Global bot instance
bot: AdminBot | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan context manager."""
    global bot
    bot = AdminBot()
    await bot.initialize()
    await bot.start()
    yield
    await bot.stop()


# Create FastAPI app
app = FastAPI(
    title="GitLab Admin Bot",
    description="AI-powered GitLab administration bot",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/status")
async def status() -> dict[str, Any]:
    """Get current system status."""
    if not bot:
        return {"status": "not_initialized"}

    health = await bot.health_monitor.get_status() if bot.health_monitor else {}
    resources = await bot.resource_monitor.get_status() if bot.resource_monitor else {}
    backup = await bot.backup_monitor.get_status() if bot.backup_monitor else {}

    return {
        "status": "running",
        "health": health,
        "resources": resources,
        "backup": backup,
    }


@app.post("/analyze")
async def trigger_analysis() -> dict[str, str]:
    """Manually trigger AI analysis."""
    if not bot or not bot.ai_analyst:
        return {"error": "AI analyst not available"}

    await bot._run_ai_analysis()
    return {"status": "analysis_triggered"}


@app.post("/backup")
async def trigger_backup() -> dict[str, str]:
    """Manually trigger a GitLab backup."""
    if not bot or not bot.ssh_client:
        return {"error": "SSH client not available"}

    try:
        output = await bot.ssh_client.run_command(
            "gitlab-backup create STRATEGY=copy SKIP=artifacts,lfs",
            timeout=1800,
        )
        return {"status": "backup_triggered", "output": output[-500:]}
    except Exception as e:
        return {"error": str(e)}


@app.get("/scheduler/jobs")
async def list_scheduled_jobs() -> dict[str, Any]:
    """List all scheduled jobs and their status."""
    if not bot or not bot.scheduler:
        return {"error": "Scheduler not available"}

    jobs_info = bot.scheduler.get_jobs()
    return {"jobs": [{"id": k, "name": v} for k, v in jobs_info.items()]}


@app.post("/maintenance/{task}")
async def trigger_maintenance(task: str) -> dict[str, Any]:
    """Manually trigger a maintenance task.

    Available tasks: cleanup_artifacts, cleanup_registry, rotate_logs,
                     database_vacuum, integrity_check, daily_report
    """
    if not bot or not bot.maintenance:
        return {"error": "Maintenance runner not available"}

    task_map: dict[str, Any] = {
        "cleanup_artifacts": bot.maintenance.cleanup_old_artifacts,
        "cleanup_registry": bot.maintenance.cleanup_registry,
        "rotate_logs": bot.maintenance.rotate_logs,
        "database_vacuum": bot.maintenance.database_vacuum,
        "integrity_check": bot.maintenance.check_gitlab_integrity,
        "daily_report": bot.maintenance.generate_daily_report,
    }

    if task not in task_map:
        return {
            "error": f"Unknown task: {task}",
            "available_tasks": list(task_map.keys()),
        }

    try:
        result = await task_map[task]()
        return {"status": "completed", "task": task, "result": result}
    except Exception as e:
        return {"status": "failed", "task": task, "error": str(e)}


def main() -> None:
    """Main entry point."""
    settings = get_settings()

    # Handle shutdown signals
    def handle_signal(signum: int, frame: types.FrameType | None) -> None:
        logger.info("Received shutdown signal", signal=signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Run the server
    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
