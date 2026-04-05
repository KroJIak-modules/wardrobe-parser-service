"""State-oriented operations for parser jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings
from app.models import ParserJob
from app.repositories import ParserJobRepository


class ParserJobStateService:
    """Encapsulates non-orchestration state transitions and lookups for parser jobs."""

    def __init__(self, job_repo: ParserJobRepository):
        self.job_repo = job_repo

    def get_job(self, job_id: str) -> Optional[ParserJob]:
        return self.job_repo.get_by_id(job_id)

    def get_latest_job(self) -> Optional[ParserJob]:
        self._cleanup_stale_in_progress_jobs()
        return self.job_repo.get_latest_job()

    def get_latest_completed_job(self) -> Optional[ParserJob]:
        jobs = self.job_repo.get_latest_completed(limit=1)
        return jobs[0] if jobs else None

    def get_next_scheduled_sync(self) -> Optional[datetime]:
        last_job = self.get_latest_completed_job()
        if last_job and last_job.completed_at:
            next_time = last_job.completed_at
            if next_time.tzinfo is None:
                next_time = next_time.replace(tzinfo=timezone.utc)
            return next_time + timedelta(minutes=settings.parser_sync_period_minutes)
        return None

    def get_in_progress_jobs(self) -> list[ParserJob]:
        self._cleanup_stale_in_progress_jobs()
        return self.job_repo.get_in_progress()

    def is_sync_in_progress(self) -> bool:
        return len(self.get_in_progress_jobs()) > 0

    def _cleanup_stale_in_progress_jobs(self) -> None:
        now_utc = datetime.now(timezone.utc)
        stale_delta = timedelta(minutes=settings.parser_job_stale_minutes)
        jobs = self.job_repo.get_in_progress()
        changed = False

        for job in jobs:
            started = job.started_at or job.created_at
            if not started:
                continue
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if now_utc - started >= stale_delta:
                self.job_repo.mark_failed(job)
                changed = True

        if changed:
            self.job_repo.session.commit()
