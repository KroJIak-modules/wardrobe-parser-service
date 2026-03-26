"""
Parser job service for job orchestration.
"""

import uuid
from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models import ParserJob, JobStatus, ParserJobSourceRun, SourceRunStatus
from app.repositories import ParserJobRepository, ParserSourceRepository
from app.services.fingerprint import FingerprintService


class ParserJobService:
    """Service for parser job orchestration."""

    def __init__(self, session: Session):
        self.session = session
        self.job_repo = ParserJobRepository(session)
        self.source_repo = ParserSourceRepository(session)

    def create_sync_job(
        self, triggered_by: str = "scheduled"
    ) -> ParserJob:
        """
        Create new sync job.

        Args:
            triggered_by: "scheduled" or "manual"

        Returns:
            ParserJob instance
        """
        job_id = str(uuid.uuid4())
        job = self.job_repo.create_job(
            job_id=job_id,
            triggered_by=triggered_by,
        )
        self.session.commit()
        return job

    def start_job(self, job_id: str) -> Optional[ParserJob]:
        """Mark job as started."""
        job = self.job_repo.get_by_id(job_id)
        if job:
            self.job_repo.mark_started(job)
            self.session.commit()
        return job

    def complete_job(
        self,
        job_id: str,
        total_products: int,
        new_products: int = 0,
        updated_products: int = 0,
    ) -> Optional[ParserJob]:
        """Mark job as successfully completed."""
        job = self.job_repo.get_by_id(job_id)
        if job:
            self.job_repo.mark_completed(
                job,
                total_products=total_products,
                new_products=new_products,
                updated_products=updated_products,
            )
            self.session.commit()
        return job

    def fail_job(self, job_id: str) -> Optional[ParserJob]:
        """Mark job as failed."""
        job = self.job_repo.get_by_id(job_id)
        if job:
            self.job_repo.mark_failed(job)
            self.session.commit()
        return job

    def add_error(
        self,
        job_id: str,
        count: int = 1,
        http_429_count: int = 0,
        http_5xx_count: int = 0,
    ) -> Optional[ParserJob]:
        """Add error counts to job."""
        job = self.job_repo.get_by_id(job_id)
        if job:
            self.job_repo.increment_error_count(
                job,
                count=count,
                http_429_count=http_429_count,
                http_5xx_count=http_5xx_count,
            )
            self.session.commit()
        return job

    def get_job(self, job_id: str) -> Optional[ParserJob]:
        """Get job by ID."""
        return self.job_repo.get_by_id(job_id)

    def get_latest_job(self) -> Optional[ParserJob]:
        """Get most recent job."""
        return self.job_repo.get_latest_job()

    def get_latest_completed_job(self) -> Optional[ParserJob]:
        """Get latest completed job."""
        jobs = self.job_repo.get_latest_completed(limit=1)
        return jobs[0] if jobs else None

    def get_next_scheduled_sync(self) -> Optional[datetime]:
        """
        Calculate next scheduled sync time.

        Default: every 5 hours from now.
        """
        last_job = self.get_latest_completed_job()
        if last_job and last_job.completed_at:
            # Simple: 5 hours after completion
            next_time = last_job.completed_at.replace(tzinfo=timezone.utc)
            # In production, this would be calculated from APScheduler config
            return next_time
        return None

    def get_in_progress_jobs(self) -> List[ParserJob]:
        """Get all currently running jobs."""
        return self.job_repo.get_in_progress()

    def is_sync_in_progress(self) -> bool:
        """Check if any sync job is currently running."""
        return len(self.get_in_progress_jobs()) > 0

    def create_source_run(
        self,
        job_id: str,
        source_id: int,
    ) -> Optional[ParserJobSourceRun]:
        """Create source run record for job."""
        job = self.job_repo.get_by_id(job_id)
        if not job:
            return None

        source_run = ParserJobSourceRun(
            job_id=job_id,
            source_id=source_id,
            status=SourceRunStatus.PENDING,
            products_discovered=0,
            products_fetched=0,
            products_failed=0,
        )
        self.session.add(source_run)
        self.session.flush()
        return source_run

    def update_source_run(
        self,
        source_run_id: int,
        status: str = None,
        products_discovered: int = None,
        products_fetched: int = None,
        products_failed: int = None,
        error_message: str = None,
        discovery_mode: str = None,
    ) -> Optional[ParserJobSourceRun]:
        """Update source run record."""
        source_run = self.session.query(ParserJobSourceRun).filter(
            ParserJobSourceRun.id == source_run_id
        ).first()

        if not source_run:
            return None

        if status is not None:
            source_run.status = status
        if products_discovered is not None:
            source_run.products_discovered = products_discovered
        if products_fetched is not None:
            source_run.products_fetched = products_fetched
        if products_failed is not None:
            source_run.products_failed = products_failed
        if error_message is not None:
            source_run.error_message = error_message
        if discovery_mode is not None:
            source_run.discovery_mode = discovery_mode

        if status in [SourceRunStatus.SUCCESS, SourceRunStatus.PARTIAL, SourceRunStatus.FAILED]:
            source_run.completed_at = datetime.now(timezone.utc)

        self.session.flush()
        return source_run

    def mark_source_run_started(self, source_run_id: int) -> Optional[ParserJobSourceRun]:
        """Mark source run as started."""
        source_run = self.session.query(ParserJobSourceRun).filter(
            ParserJobSourceRun.id == source_run_id
        ).first()

        if source_run:
            source_run.status = SourceRunStatus.IN_PROGRESS
            source_run.started_at = datetime.now(timezone.utc)
            self.session.flush()

        return source_run

    def get_job_summary(self, job_id: str) -> dict:
        """Get job with full summary including source runs."""
        job = self.job_repo.get_with_source_runs(job_id)
        if not job:
            return {}

        return {
            "id": job.id,
            "status": job.status,
            "triggered_by": job.triggered_by,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "total_products": job.total_products,
            "new_products": job.new_products,
            "updated_products": job.updated_products,
            "new_images": job.new_images,
            "error_count": job.error_count,
            "http_429_count": job.http_429_count,
            "http_5xx_count": job.http_5xx_count,
            "source_runs": [
                {
                    "id": run.id,
                    "source_id": run.source_id,
                    "status": run.status,
                    "products_discovered": run.products_discovered,
                    "products_fetched": run.products_fetched,
                    "products_failed": run.products_failed,
                    "discovery_mode": run.discovery_mode,
                }
                for run in job.source_runs
            ],
        }
