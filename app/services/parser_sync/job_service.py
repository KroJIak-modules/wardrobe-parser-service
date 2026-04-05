"""
Parser job service for job orchestration.
"""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import uuid
from typing import Callable, Optional, List
from datetime import datetime
import logging
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import (
    ParserJob,
    JobStatus,
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
from app.services.settings.weight_rule_service import WeightRuleService
from app.services.parser_sync.job_execution import (
    JobExecutionTotals,
    get_or_create_source,
    resolve_enabled_sources,
)
from app.services.parser_sync.source_sync_executor import ParserSourceSyncExecutor
from app.services.parser_sync.source_sync_executor import SourceSyncStats
from app.services.parser_sync.progress_tracker import job_progress_tracker


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SourceExecutionInput:
    """Immutable payload for one source execution worker."""

    source_id: int
    source_name: str
    source_index: int
    base_url: str
    parser_type: str


class ParserJobService:
    """Service for parser job orchestration."""

    def __init__(self, session: Session):
        self.session = session
        self.job_repo = ParserJobRepository(session)
        self.source_repo = ParserSourceRepository(session)
        self.product_repo = ParserProductRepository(session)
        self.image_repo = ParserImageAssetRepository(session)
        self.source_run_service = ParserSourceRunService(session=session, job_repo=self.job_repo)
        self.weight_rule_service = WeightRuleService(session)
        self.product_sync_service = ParserProductSyncService(
            product_repo=self.product_repo,
            image_repo=self.image_repo,
            weight_rule_service=self.weight_rule_service,
        )
        self.job_state_service = ParserJobStateService(job_repo=self.job_repo)
        self.source_sync_executor = ParserSourceSyncExecutor(
            session=self.session,
            source_run_service=self.source_run_service,
            product_sync_service=self.product_sync_service,
            discover_source=self._discover_source,
        )

    def _discover_source(
        self,
        parser_type: str,
        base_url: str,
        *,
        deadline_monotonic: float | None = None,
        on_progress: Callable[[], None] | None = None,
    ):
        engine = get_parser_engine(parser_type)
        return engine.discover(
            base_url,
            deadline_monotonic=deadline_monotonic,
            on_progress=on_progress,
        )

    @staticmethod
    def _sync_one_source_worker(job_id: str, source_input: SourceExecutionInput) -> SourceSyncStats:
        """Execute one source in an isolated DB session for safe parallel processing."""
        db = SessionLocal()
        try:
            service = ParserJobService(db)
            current = service.job_repo.get_by_id(job_id)
            if not current or current.status == JobStatus.CANCELLED:
                return SourceSyncStats()

            job_progress_tracker.start_source(
                job_id=job_id,
                source_name=source_input.source_name,
                source_index=source_input.source_index,
            )

            def on_source_discovered(total_products_in_source: int) -> None:
                job_progress_tracker.set_current_source_expected_products(
                    job_id=job_id,
                    total_products=total_products_in_source,
                )

            def on_product_processed(
                product_title: str | None,
                processed_in_source: int,
                _total_in_source: int,
            ) -> None:
                job_progress_tracker.mark_product_processed(
                    job_id=job_id,
                    product_title=product_title,
                    processed_in_current_source=processed_in_source,
                )

            return service.source_sync_executor.sync_source(
                job_id=job_id,
                source_id=source_input.source_id,
                base_url=source_input.base_url,
                parser_type=source_input.parser_type,
                on_source_discovered=on_source_discovered,
                on_product_processed=on_product_processed,
            )
        except Exception:
            db.rollback()
            LOGGER.exception(
                "Parallel source worker failed job_id=%s source_id=%s base_url=%s",
                job_id,
                source_input.source_id,
                source_input.base_url,
            )
            return SourceSyncStats(errors=1)
        finally:
            job_progress_tracker.finish_source(job_id=job_id)
            db.close()

    def create_pending_job(self, triggered_by: str = "manual") -> ParserJob:
        """Create a pending sync job row and persist it."""
        job_id = str(uuid.uuid4())
        job = self.job_repo.create_job(job_id=job_id, triggered_by=triggered_by)
        self.session.commit()
        return job

    def execute_job(self, job_id: str) -> Optional[ParserJob]:
        """Execute a previously created job by id."""
        job = self.job_repo.get_by_id(job_id)
        if not job:
            return None

        if job.status == JobStatus.CANCELLED:
            job_progress_tracker.finish_job(job_id=job_id)
            return job

        self.job_repo.mark_started(job)
        self.session.commit()

        totals = JobExecutionTotals()
        sources = resolve_enabled_sources()
        job_progress_tracker.start_job(job_id=job_id, total_sources=len(sources))

        if not sources:
            current = self.job_repo.get_by_id(job_id)
            if current and current.status == JobStatus.CANCELLED:
                self.session.commit()
                job_progress_tracker.finish_job(job_id=job_id)
                return current
            self.job_repo.mark_completed(job, total_products=0, new_products=0, updated_products=0)
            self.session.commit()
            job_progress_tracker.finish_job(job_id=job_id)
            return job

        source_inputs: list[SourceExecutionInput] = []

        for source_index, source_item in enumerate(sources, start=1):
            current = self.job_repo.get_by_id(job_id)
            if current and current.status == JobStatus.CANCELLED:
                self.session.commit()
                job_progress_tracker.finish_job(job_id=job_id)
                return current

            source = get_or_create_source(
                source_repo=self.source_repo,
                name=source_item.name,
                url=source_item.base_url,
                parser_type=source_item.parser_type,
                enabled=source_item.enabled,
            )
            try:
                self.session.flush()
            except Exception:
                self.session.rollback()
                LOGGER.exception("Failed to upsert parser source for base_url=%s", source_item.base_url)
                totals.errors += 1
                continue

            if not source.enabled:
                continue

            source_inputs.append(
                SourceExecutionInput(
                    source_id=source.id,
                    source_name=source_item.name,
                    source_index=source_index,
                    base_url=source_item.base_url,
                    parser_type=source_item.parser_type,
                )
            )

        self.session.commit()

        worker_count = max(1, min(settings.parser_sync_source_workers, len(source_inputs)))
        pending_inputs = iter(source_inputs)

        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {}
            stop_submitting = False

            def submit_next_source() -> None:
                if stop_submitting:
                    return
                try:
                    source_input = next(pending_inputs)
                except StopIteration:
                    return
                futures[pool.submit(self._sync_one_source_worker, job.id, source_input)] = source_input

            for _ in range(worker_count):
                submit_next_source()

            while futures:
                done, _ = wait(list(futures.keys()), return_when=FIRST_COMPLETED)
                for future in done:
                    source_input = futures.pop(future)
                    try:
                        stats = future.result()
                    except Exception:
                        LOGGER.exception(
                            "Source future failed job_id=%s source_id=%s",
                            job.id,
                            source_input.source_id,
                        )
                        stats = SourceSyncStats(errors=1)
                    totals.add(stats)

                    current = self.job_repo.get_by_id(job_id)
                    if current and current.status == JobStatus.CANCELLED:
                        stop_submitting = True
                    else:
                        submit_next_source()

        current = self.job_repo.get_by_id(job_id)
        if current and current.status == JobStatus.CANCELLED:
            self.session.commit()
            job_progress_tracker.finish_job(job_id=job_id)
            return current

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
        job_progress_tracker.finish_job(job_id=job_id)

        return job

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
