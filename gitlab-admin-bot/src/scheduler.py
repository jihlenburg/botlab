"""APScheduler setup for Admin Bot."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = structlog.get_logger(__name__)


class Scheduler:
    """Wrapper around APScheduler for job management."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,  # Combine missed runs into one
                "max_instances": 1,  # Only one instance of each job
                "misfire_grace_time": 60,  # Allow 60s grace period
            }
        )
        self._jobs: dict[str, str] = {}

    def add_job(
        self,
        func: Callable[..., Any],
        trigger_type: str,
        id: str,
        name: str,
        **trigger_kwargs: Any,
    ) -> None:
        """Add a job to the scheduler."""
        if trigger_type == "interval":
            trigger = IntervalTrigger(**trigger_kwargs)
        elif trigger_type == "cron":
            trigger = CronTrigger(**trigger_kwargs)
        else:
            raise ValueError(f"Unknown trigger type: {trigger_type}")

        self._scheduler.add_job(
            func,
            trigger=trigger,
            id=id,
            name=name,
            replace_existing=True,
        )
        self._jobs[id] = name
        logger.debug("Job added", job_id=id, job_name=name, trigger=trigger_type)

    def remove_job(self, job_id: str) -> None:
        """Remove a job from the scheduler."""
        self._scheduler.remove_job(job_id)
        self._jobs.pop(job_id, None)
        logger.debug("Job removed", job_id=job_id)

    def start(self) -> None:
        """Start the scheduler."""
        self._scheduler.start()
        logger.info("Scheduler started", job_count=len(self._jobs))

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the scheduler."""
        self._scheduler.shutdown(wait=wait)
        logger.info("Scheduler shutdown")

    def get_jobs(self) -> dict[str, str]:
        """Get all scheduled jobs."""
        return self._jobs.copy()

    def pause_job(self, job_id: str) -> None:
        """Pause a job."""
        self._scheduler.pause_job(job_id)
        logger.info("Job paused", job_id=job_id)

    def resume_job(self, job_id: str) -> None:
        """Resume a paused job."""
        self._scheduler.resume_job(job_id)
        logger.info("Job resumed", job_id=job_id)
