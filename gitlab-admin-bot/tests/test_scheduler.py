"""Tests for scheduler module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.scheduler import Scheduler


class TestScheduler:
    """Tests for Scheduler wrapper."""

    @pytest.fixture
    def scheduler(self):
        """Create a Scheduler instance with mocked APScheduler."""
        with patch("src.scheduler.AsyncIOScheduler") as mock_cls:
            mock_internal = MagicMock()
            mock_cls.return_value = mock_internal
            sched = Scheduler()
            sched._mock_internal = mock_internal
            return sched

    def test_initialization(self, scheduler):
        """Test scheduler initializes with empty job registry."""
        assert scheduler.get_jobs() == {}

    def test_add_interval_job(self, scheduler):
        """Test adding an interval-triggered job."""
        func = AsyncMock()

        scheduler.add_job(
            func, "interval", id="test_job", name="Test Job", seconds=30
        )

        scheduler._mock_internal.add_job.assert_called_once()
        assert scheduler.get_jobs() == {"test_job": "Test Job"}

    def test_add_cron_job(self, scheduler):
        """Test adding a cron-triggered job."""
        func = AsyncMock()

        scheduler.add_job(
            func, "cron", id="daily_job", name="Daily Job", hour=3, minute=0
        )

        scheduler._mock_internal.add_job.assert_called_once()
        assert "daily_job" in scheduler.get_jobs()

    def test_add_job_invalid_trigger(self, scheduler):
        """Test adding a job with invalid trigger type raises ValueError."""
        func = AsyncMock()

        with pytest.raises(ValueError, match="Unknown trigger type"):
            scheduler.add_job(func, "invalid_trigger", id="bad", name="Bad Job")

    def test_remove_job(self, scheduler):
        """Test removing a job."""
        func = AsyncMock()
        scheduler.add_job(func, "interval", id="rm_job", name="Remove Me", seconds=60)

        scheduler.remove_job("rm_job")

        scheduler._mock_internal.remove_job.assert_called_once_with("rm_job")
        assert "rm_job" not in scheduler.get_jobs()

    def test_get_jobs_returns_copy(self, scheduler):
        """Test that get_jobs returns a copy, not the internal dict."""
        func = AsyncMock()
        scheduler.add_job(func, "interval", id="j1", name="Job 1", seconds=10)

        jobs = scheduler.get_jobs()
        jobs["j2"] = "Job 2"

        assert "j2" not in scheduler.get_jobs()

    def test_start(self, scheduler):
        """Test starting the scheduler."""
        scheduler.start()
        scheduler._mock_internal.start.assert_called_once()

    def test_shutdown(self, scheduler):
        """Test shutting down the scheduler."""
        scheduler.shutdown()
        scheduler._mock_internal.shutdown.assert_called_once_with(wait=True)

    def test_shutdown_no_wait(self, scheduler):
        """Test shutting down without waiting."""
        scheduler.shutdown(wait=False)
        scheduler._mock_internal.shutdown.assert_called_once_with(wait=False)

    def test_pause_job(self, scheduler):
        """Test pausing a job."""
        scheduler.pause_job("test_id")
        scheduler._mock_internal.pause_job.assert_called_once_with("test_id")

    def test_resume_job(self, scheduler):
        """Test resuming a paused job."""
        scheduler.resume_job("test_id")
        scheduler._mock_internal.resume_job.assert_called_once_with("test_id")

    def test_multiple_jobs(self, scheduler):
        """Test adding multiple jobs and tracking them."""
        func = AsyncMock()

        scheduler.add_job(func, "interval", id="j1", name="Job 1", seconds=10)
        scheduler.add_job(func, "interval", id="j2", name="Job 2", seconds=20)
        scheduler.add_job(func, "cron", id="j3", name="Job 3", hour=5)

        jobs = scheduler.get_jobs()
        assert len(jobs) == 3
        assert jobs["j1"] == "Job 1"
        assert jobs["j2"] == "Job 2"
        assert jobs["j3"] == "Job 3"
