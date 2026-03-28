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

    def start_job(self, job_id: str) -> Optional[ParserJob]:
        job = self.job_repo.get_by_id(job_id)
        if job:
            self.job_repo.mark_started(job)
            self.job_repo.session.commit()
        return job

    def complete_job(
        self,
        job_id: str,
        total_products: int,
        new_products: int = 0,
        updated_products: int = 0,
    ) -> Optional[ParserJob]:
        job = self.job_repo.get_by_id(job_id)
        if job:
            self.job_repo.mark_completed(
                job,
                total_products=total_products,
                new_products=new_products,
                updated_products=updated_products,
            )
            self.job_repo.session.commit()
        return job

    def fail_job(self, job_id: str) -> Optional[ParserJob]:
        job = self.job_repo.get_by_id(job_id)
        if job:
            self.job_repo.mark_failed(job)
            self.job_repo.session.commit()
        return job

    def add_error(
        self,
        job_id: str,
        count: int = 1,
        http_429_count: int = 0,
        http_5xx_count: int = 0,
    ) -> Optional[ParserJob]:
        job = self.job_repo.get_by_id(job_id)
        if job:
            self.job_repo.increment_error_count(
                job,
                count=count,
                http_429_count=http_429_count,
                http_5xx_count=http_5xx_count,
            )
            self.job_repo.session.commit()
        return job

    def get_job(self, job_id: str) -> Optional[ParserJob]:
        return self.job_repo.get_by_id(job_id)

    def get_latest_job(self) -> Optional[ParserJob]:
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
        return self.job_repo.get_in_progress()

    def is_sync_in_progress(self) -> bool:
        return len(self.get_in_progress_jobs()) > 0
