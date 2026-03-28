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
    JobStatus,
    ParserJobSourceRun,
    SourceRunStatus,
    ProductStatus,
)
from app.parsers.shopify_parser import ShopifyParser
from app.repositories import (
    ParserJobRepository,
    ParserSourceRepository,
    ParserProductRepository,
    ParserImageAssetRepository,
)


class ParserJobService:
    """Service for parser job orchestration."""

    def __init__(self, session: Session):
        self.session = session
        self.job_repo = ParserJobRepository(session)
        self.source_repo = ParserSourceRepository(session)
        self.product_repo = ParserProductRepository(session)
        self.image_repo = ParserImageAssetRepository(session)

    @staticmethod
    def _to_float(value: str | None) -> float | None:
        if value is None:
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

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

    def _upsert_product_from_preview(self, source_id: int, preview) -> tuple[int, int]:
        existing = self.product_repo.get_by_source_and_handle(source_id, preview.handle)
        parsed_price = self._to_float(preview.price)
        preview_image_urls = preview.image_urls or []
        assets = self.image_repo.ensure_assets(preview_image_urls)
        preview_image_asset_ids = [asset.id for asset in assets]

        if existing is None:
            self.product_repo.create_product(
                source_id=source_id,
                handle=preview.handle,
                title=preview.title or preview.handle,
                url=preview.product_url,
                vendor=preview.vendor,
                product_type=preview.product_type,
                price=parsed_price,
                currency=preview.currency or "USD",
                image_count=len(preview_image_urls),
                image_urls=preview_image_urls,
                image_asset_ids=preview_image_asset_ids,
                status=ProductStatus.AVAILABLE,
            )
            return 1, 0

        changed = (
            existing.title != (preview.title or preview.handle)
            or existing.url != preview.product_url
            or existing.vendor != preview.vendor
            or existing.product_type != preview.product_type
            or existing.price != parsed_price
            or existing.currency != (preview.currency or "USD")
            or (existing.image_urls or []) != preview_image_urls
            or (existing.image_asset_ids or []) != preview_image_asset_ids
            or existing.image_count != len(preview_image_urls)
            or existing.status != ProductStatus.AVAILABLE
        )
        if not changed:
            return 0, 0

        self.product_repo.update(
            existing,
            title=preview.title or preview.handle,
            url=preview.product_url,
            vendor=preview.vendor,
            product_type=preview.product_type,
            price=parsed_price,
            currency=preview.currency or "USD",
            image_count=len(preview_image_urls),
            image_urls=preview_image_urls,
            image_asset_ids=preview_image_asset_ids,
            status=ProductStatus.AVAILABLE,
            deleted_at=None,
        )
        return 0, 1

    def _sync_source_products(self, source_id: int, previews: list) -> tuple[int, int]:
        created_for_source = 0
        updated_for_source = 0
        for preview in previews:
            created_delta, updated_delta = self._upsert_product_from_preview(source_id, preview)
            created_for_source += created_delta
            updated_for_source += updated_delta
        return created_for_source, updated_for_source

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

            source_run = self.create_source_run(job.id, source.id)
            if not source_run:
                total_errors += 1
                continue

            self.mark_source_run_started(source_run.id)

            try:
                result = self._discover_source(source_item.base_url)

                created_for_source, updated_for_source = self._sync_source_products(source.id, result.previews)

                total_created += created_for_source
                total_updated += updated_for_source
                total_fetched += result.products_fetch_succeeded
                total_errors += result.products_fetch_failed
                total_429 += result.http_429_count
                total_5xx += result.http_5xx_count

                self.update_source_run(
                    source_run.id,
                    status=SourceRunStatus.SUCCESS if result.products_fetch_failed == 0 else SourceRunStatus.PARTIAL,
                    products_discovered=result.product_urls_found,
                    products_fetched=result.products_fetch_succeeded,
                    products_failed=result.products_fetch_failed,
                    discovery_mode=result.discovery_mode,
                    error_message="; ".join(result.error_details[:3]) if result.error_details else None,
                )
                self.session.commit()
            except Exception as exc:
                total_errors += 1
                self.update_source_run(
                    source_run.id,
                    status=SourceRunStatus.FAILED,
                    error_message=str(exc),
                )
                self.session.commit()

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
