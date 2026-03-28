"""
Parser job service for job orchestration.
"""

import uuid
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session

from app.models import (
    ParserJob,
)
from app.parsers.engines.registry import get_parser_engine
from app.repositories import (
    ParserJobRepository,
    ParserSourceRepository,
    ParserProductRepository,
    ParserImageAssetRepository,
)
from app.services.parser_sync.source_run_service import ParserSourceRunService
from app.services.parser_sync.job_summary import build_job_summary_payload
from app.services.parser_sync.job_state_service import ParserJobStateService
from app.services.parser_sync.product_sync_service import ParserProductSyncService
from app.services.parser_sync.job_execution import (
    JobExecutionTotals,
    get_or_create_source,
    resolve_enabled_sources,
)
from app.services.parser_sync.source_sync_executor import ParserSourceSyncExecutor


class ParserJobService:
    """Service for parser job orchestration."""

    def __init__(self, session: Session):
        self.session = session
        self.job_repo = ParserJobRepository(session)
        self.source_repo = ParserSourceRepository(session)
        self.product_repo = ParserProductRepository(session)
        self.image_repo = ParserImageAssetRepository(session)
        self.source_run_service = ParserSourceRunService(session=session, job_repo=self.job_repo)
        self.product_sync_service = ParserProductSyncService(
            product_repo=self.product_repo,
            image_repo=self.image_repo,
        )
        self.job_state_service = ParserJobStateService(job_repo=self.job_repo)
        self.source_sync_executor = ParserSourceSyncExecutor(
            session=self.session,
            source_run_service=self.source_run_service,
            product_sync_service=self.product_sync_service,
            discover_source=self._discover_source,
        )

    def _discover_source(self, parser_type: str, base_url: str):
        engine = get_parser_engine(parser_type)
        return engine.discover(base_url)

    def run_sync_job(self, triggered_by: str = "manual") -> ParserJob:
        """Create and execute sync job against enabled configured sources."""
        job_id = str(uuid.uuid4())
        job = self.job_repo.create_job(job_id=job_id, triggered_by=triggered_by)
        self.job_repo.mark_started(job)
        self.session.commit()

        totals = JobExecutionTotals()
        sources = resolve_enabled_sources()

        if not sources:
            self.job_repo.mark_completed(job, total_products=0, new_products=0, updated_products=0)
            self.session.commit()
            return job

        for source_item in sources:
            source = get_or_create_source(
                source_repo=self.source_repo,
                name=source_item.name,
                url=source_item.base_url,
                parser_type=source_item.parser_type,
                enabled=source_item.enabled,
            )
            self.session.flush()

            if not source.enabled:
                continue

            stats = self.source_sync_executor.sync_source(
                job_id=job.id,
                source_id=source.id,
                base_url=source_item.base_url,
                parser_type=source_item.parser_type,
            )
            totals.add(stats)

        self.job_repo.increment_error_count(
            job,
            count=totals.errors,
            http_429_count=totals.http_429,
            http_5xx_count=totals.http_5xx,
        )
        self.job_repo.mark_completed(
            job,
            total_products=totals.fetched,
            new_products=totals.created,
            updated_products=totals.updated,
        )
        self.session.commit()

        return job

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
        return self.run_sync_job(triggered_by=triggered_by)

    def get_job(self, job_id: str) -> Optional[ParserJob]:
        """Get job by ID."""
        return self.job_state_service.get_job(job_id)

    def get_latest_job(self) -> Optional[ParserJob]:
        """Get most recent job."""
        return self.job_state_service.get_latest_job()

    def get_next_scheduled_sync(self) -> Optional[datetime]:
        """
        Calculate next scheduled sync time.

        Configurable via PARSER_SYNC_PERIOD_MINUTES.
        """
        return self.job_state_service.get_next_scheduled_sync()

    def get_in_progress_jobs(self) -> List[ParserJob]:
        """Get all currently running jobs."""
        return self.job_state_service.get_in_progress_jobs()

    def is_sync_in_progress(self) -> bool:
        """Check if any sync job is currently running."""
        return self.job_state_service.is_sync_in_progress()

    def get_job_summary(self, job_id: str) -> dict:
        """Get job with full summary including source runs."""
        job = self.job_repo.get_with_source_runs(job_id)
        if not job:
            return {}

        return build_job_summary_payload(job)
