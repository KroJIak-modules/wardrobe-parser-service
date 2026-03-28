"""
Parser job service for job orchestration.
"""

import uuid
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.config.source_registry import list_sources
from app.core.config import settings
from app.models import (
    ParserJob,
    ParserJobSourceRun,
)
from app.parsers.shopify_parser import ShopifyParser
from app.repositories import (
    ParserJobRepository,
    ParserSourceRepository,
    ParserProductRepository,
    ParserImageAssetRepository,
)
from app.services.parser_source_run_service import ParserSourceRunService
from app.services.parser_job_summary import build_job_summary_payload
from app.services.parser_product_sync_service import ParserProductSyncService
from app.services.parser_source_sync_executor import ParserSourceSyncExecutor


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
        self.source_sync_executor = ParserSourceSyncExecutor(
            session=self.session,
            source_run_service=self.source_run_service,
            product_sync_service=self.product_sync_service,
            discover_source=self._discover_source,
        )

    def _get_or_create_source(self, name: str, url: str, parser_type: str, enabled: bool):
        source = self.source_repo.get_by_url(url)
        if source:
            source.name = name
            source.parser_type = parser_type
            return source

        return self.source_repo.create_source(
            name=name,
            url=url,
            parser_type=parser_type,
            enabled=enabled,
        )

    def _discover_source(self, base_url: str):
        return ShopifyParser.discover(
            base_url,
            max_products=settings.parser_default_max_products,
            sample_products=settings.parser_default_sample_products,
            timeout_sec=settings.parser_default_timeout_sec,
            fetch_all_products=True,
            response_products_limit=settings.parser_default_max_products,
            error_details_limit=200,
            parallel_workers=settings.parser_default_parallel_workers,
            max_retries=settings.parser_default_max_retries,
            retry_backoff_sec=settings.parser_default_retry_backoff_sec,
            second_pass_enabled=settings.parser_default_second_pass_enabled,
            second_pass_timeout_sec=settings.parser_default_second_pass_timeout_sec,
        )

    def run_sync_job(self, triggered_by: str = "manual") -> ParserJob:
        """Create and execute sync job against enabled Shopify sources."""
        job_id = str(uuid.uuid4())
        job = self.job_repo.create_job(job_id=job_id, triggered_by=triggered_by)
        self.job_repo.mark_started(job)
        self.session.commit()

        total_created = 0
        total_updated = 0
        total_fetched = 0
        total_errors = 0
        total_429 = 0
        total_5xx = 0

        sources = list_sources(parser_type="shopify")
        if settings.parser_sync_max_sources > 0:
            sources = sources[: settings.parser_sync_max_sources]

        if not sources:
            self.job_repo.mark_completed(job, total_products=0, new_products=0, updated_products=0)
            self.session.commit()
            return job

        for source_item in sources:
            source = self._get_or_create_source(
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
            )
            total_created += stats.created
            total_updated += stats.updated
            total_fetched += stats.fetched
            total_errors += stats.errors
            total_429 += stats.http_429
            total_5xx += stats.http_5xx

        self.job_repo.increment_error_count(
            job,
            count=total_errors,
            http_429_count=total_429,
            http_5xx_count=total_5xx,
        )
        self.job_repo.mark_completed(
            job,
            total_products=total_fetched,
            new_products=total_created,
            updated_products=total_updated,
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

        Configurable via PARSER_SYNC_PERIOD_MINUTES.
        """
        last_job = self.get_latest_completed_job()
        if last_job and last_job.completed_at:
            next_time = last_job.completed_at
            if next_time.tzinfo is None:
                next_time = next_time.replace(tzinfo=timezone.utc)
            next_time = next_time + timedelta(minutes=settings.parser_sync_period_minutes)
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
        return self.source_run_service.create_source_run(job_id=job_id, source_id=source_id)

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
        return self.source_run_service.update_source_run(
            source_run_id=source_run_id,
            status=status,
            products_discovered=products_discovered,
            products_fetched=products_fetched,
            products_failed=products_failed,
            error_message=error_message,
            discovery_mode=discovery_mode,
        )

    def mark_source_run_started(self, source_run_id: int) -> Optional[ParserJobSourceRun]:
        """Mark source run as started."""
        return self.source_run_service.mark_source_run_started(source_run_id=source_run_id)

    def get_job_summary(self, job_id: str) -> dict:
        """Get job with full summary including source runs."""
        job = self.job_repo.get_with_source_runs(job_id)
        if not job:
            return {}

        return build_job_summary_payload(job)
