"""
ParserJob repository for job orchestration.
"""

from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import desc
from sqlalchemy.orm import selectinload

from app.models import ParserJob, JobStatus, ParserJobSourceRun
from app.repositories.base import BaseRepository


class ParserJobRepository(BaseRepository[ParserJob]):
    """Repository for ParserJob entity."""

    def __init__(self, session: Session):
        super().__init__(session, ParserJob)

    def create_job(
        self,
        job_id: str,
        triggered_by: str,
    ) -> ParserJob:
        """Create a new sync job."""
        job = self.create(
            id=job_id,
            status=JobStatus.PENDING,
            triggered_by=triggered_by,
            error_count=0,
            http_429_count=0,
            http_5xx_count=0,
        )
        self.flush()
        return job

    def get_by_id(self, job_id: str) -> Optional[ParserJob]:
        """Get job by string UUID."""
        return self.get_by_id_string(job_id)

    def get_latest_completed(self, limit: int = 1) -> List[ParserJob]:
        """Get latest completed jobs."""
        return (
            self.query()
            .filter(ParserJob.status == JobStatus.COMPLETED)
            .filter(ParserJob.deleted_at.is_(None))
            .order_by(desc(ParserJob.completed_at))
            .limit(limit)
            .all()
        )

    def get_latest_job(self) -> Optional[ParserJob]:
        """Get most recent job regardless of status."""
        return (
            self.query()
            .filter(ParserJob.deleted_at.is_(None))
            .order_by(desc(ParserJob.created_at))
            .first()
        )

    def get_in_progress(self) -> List[ParserJob]:
        """Get all in-progress jobs."""
        return (
            self.query()
            .filter(ParserJob.status == JobStatus.IN_PROGRESS)
            .filter(ParserJob.deleted_at.is_(None))
            .all()
        )

    def get_pending(self) -> List[ParserJob]:
        """Get all pending jobs."""
        return (
            self.query()
            .filter(ParserJob.status == JobStatus.PENDING)
            .filter(ParserJob.deleted_at.is_(None))
            .all()
        )

    def mark_started(self, job: ParserJob) -> ParserJob:
        """Mark job as started."""
        return self.update(
            job,
            status=JobStatus.IN_PROGRESS,
            started_at=datetime.now(timezone.utc),
        )

    def mark_completed(
        self,
        job: ParserJob,
        total_products: int,
        new_products: int = 0,
        updated_products: int = 0,
    ) -> ParserJob:
        """Mark job as successfully completed."""
        return self.update(
            job,
            status=JobStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
            total_products=total_products,
            new_products=new_products,
            updated_products=updated_products,
        )

    def mark_failed(self, job: ParserJob, error_message: str = None) -> ParserJob:
        """Mark job as failed."""
        update_data = {
            "status": JobStatus.FAILED,
            "completed_at": datetime.now(timezone.utc),
        }
        return self.update(job, **update_data)

    def increment_error_count(
        self,
        job: ParserJob,
        count: int = 1,
        http_429_count: int = 0,
        http_5xx_count: int = 0,
    ) -> ParserJob:
        """Increment error counters."""
        job.error_count = (job.error_count or 0) + count
        job.http_429_count = (job.http_429_count or 0) + http_429_count
        job.http_5xx_count = (job.http_5xx_count or 0) + http_5xx_count
        return job

    def get_with_source_runs(self, job_id: str) -> Optional[ParserJob]:
        """Get job with all source runs eagerly loaded."""
        return (
            self.query()
            .options(selectinload(ParserJob.source_runs))
            .filter(ParserJob.id == job_id)
            .filter(ParserJob.deleted_at.is_(None))
            .first()
        )
