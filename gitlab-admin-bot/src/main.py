"""GitLab Admin Bot - Main entry point."""

from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
import uvicorn
from fastapi import FastAPI
from prometheus_client import make_asgi_app

from src.config import get_settings
from src.scheduler import Scheduler
from src.monitors.health import HealthMonitor
from src.monitors.resources import ResourceMonitor
from src.monitors.backup import BackupMonitor
from src.alerting.manager import AlertManager
from src.ai.analyst import AIAnalyst
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
        self.scheduler.add_job(
            self.health_monitor.check,
            "interval",
            seconds=settings.health_check_interval_seconds,
            id="health_check",
            name="GitLab Health Check",
        )

        # Resource monitoring
        self.scheduler.add_job(
            self.resource_monitor.check,
            "interval",
            seconds=settings.resource_check_interval_seconds,
            id="resource_check",
            name="Resource Monitor",
        )

        # Backup monitoring
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
                    else:
                        # Alert admins about recommended action
                        await self.alert_manager.send_alert(
                            severity="info",
                            title="AI Recommendation",
                            message=f"{action.description}\n\nReason: {action.reason}",
                        )

        except Exception as e:
            logger.error("AI analysis failed", error=str(e))

    async def _execute_action(self, action) -> None:
        """Execute a recommended maintenance action."""
        logger.info("Executing recommended action", action=action.name)
        # Implementation depends on action type
        pass

    async def _daily_maintenance(self) -> None:
        """Daily maintenance tasks."""
        logger.info("Running daily maintenance")
        # Generate daily report
        # Sync backups to Storage Box
        # Clean old logs

    async def _weekly_maintenance(self) -> None:
        """Weekly maintenance tasks."""
        logger.info("Running weekly maintenance")
        # Container registry GC
        # Database vacuum
        # Backup restore test

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
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/status")
async def status():
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
async def trigger_analysis():
    """Manually trigger AI analysis."""
    if not bot or not bot.ai_analyst:
        return {"error": "AI analyst not available"}

    await bot._run_ai_analysis()
    return {"status": "analysis_triggered"}


def main() -> None:
    """Main entry point."""
    settings = get_settings()

    # Handle shutdown signals
    def handle_signal(signum, frame):
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
