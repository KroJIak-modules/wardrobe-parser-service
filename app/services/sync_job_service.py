"""Service layer for sync job API endpoints."""

from __future__ import annotations

from typing import Optional
import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import JobStatus, ParserJobSourceRun, SourceRunStatus
from app.models import ParserProduct, ParserSource
from app.schemas.parser import (
    JobCreateRequest,
    JobCreateResponse,
    JobLatestResponse,
    JobResponse,
    JobCancelResponse,
)
from app.services.parser_sync.job_execution import resolve_enabled_sources
from app.services.parser_sync.job_service import ParserJobService
from app.services.parser_sync.progress_tracker import job_progress_tracker


LOGGER = logging.getLogger(__name__)


class SyncJobService:
    """Facade service for sync endpoints backed by ParserJobService."""

    def __init__(self, db: Session):
        self.db = db
        self.parser_job_service = ParserJobService(db)

    def create_sync_job(self, request: JobCreateRequest) -> JobCreateResponse:
        if self.parser_job_service.is_sync_in_progress():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Sync already in progress. Wait for completion or check status at GET /api/v1/jobs/latest",
            )

        job = self.parser_job_service.create_pending_job(triggered_by=request.triggered_by)
        return JobCreateResponse(
            id=job.id,
            status=job.status,
            created_at=job.created_at,
        )

    @staticmethod
    def execute_sync_job_async(job_id: str) -> None:
        """Run a queued sync job in a fresh DB session (background task)."""
        db = SessionLocal()
        try:
            ParserJobService(db).execute_job(job_id)
        except Exception:
            db.rollback()
            LOGGER.exception("Background sync job failed job_id=%s", job_id)
        finally:
            db.close()

    def get_latest_job(self) -> Optional[JobLatestResponse]:
        job = self.parser_job_service.get_latest_job()
        if not job:
            return None

        next_scheduled = self.parser_job_service.get_next_scheduled_sync()
        total_sources = len(resolve_enabled_sources())
        source_runs_count = (
            self.db.query(ParserJobSourceRun)
            .filter(ParserJobSourceRun.job_id == job.id)
            .count()
        )
        # If source list has changed, keep denominator stable for this run.
        if source_runs_count > total_sources:
            total_sources = source_runs_count

        processed_sources = (
            self.db.query(ParserJobSourceRun)
            .filter(ParserJobSourceRun.job_id == job.id)
            .filter(
                ParserJobSourceRun.status.in_(
                    [SourceRunStatus.SUCCESS, SourceRunStatus.PARTIAL, SourceRunStatus.FAILED]
                )
            )
            .count()
        )
        progress_percent = int((processed_sources * 100) / total_sources) if total_sources > 0 else 100

        source_run_rows = (
            self.db.query(
                ParserJobSourceRun.products_discovered,
                ParserJobSourceRun.products_fetched,
            )
            .filter(ParserJobSourceRun.job_id == job.id)
            .all()
        )
        db_expected_products = sum((row.products_discovered or 0) for row in source_run_rows)
        db_processed_products = sum((row.products_fetched or 0) for row in source_run_rows)

        in_progress_row = (
            self.db.query(ParserJobSourceRun, ParserSource.name)
            .join(ParserSource, ParserSource.id == ParserJobSourceRun.source_id)
            .filter(ParserJobSourceRun.job_id == job.id)
            .filter(ParserJobSourceRun.status == SourceRunStatus.IN_PROGRESS)
            .order_by(ParserJobSourceRun.id.desc())
            .first()
        )
        current_source_name = in_progress_row[1] if in_progress_row else None
        current_source_processed_products = 0
        current_source_total_products = 0

        if in_progress_row:
            in_progress_run = in_progress_row[0]
            current_source_processed_products = in_progress_run.products_fetched or 0
            current_source_total_products = in_progress_run.products_discovered or 0

        tracker_state = job_progress_tracker.get(job_id=job.id)
        current_source_index = 0
        current_stage = None
        current_product_title = None
        if tracker_state:
            db_processed_products = max(db_processed_products, tracker_state.processed_products_total)
            db_expected_products = max(db_expected_products, tracker_state.expected_products_total)
            current_source_name = tracker_state.current_source_name or current_source_name
            current_source_index = tracker_state.current_source_index
            current_stage = tracker_state.current_stage
            current_source_processed_products = max(
                current_source_processed_products,
                tracker_state.current_source_processed_products,
            )
            current_source_total_products = max(
                current_source_total_products,
                tracker_state.current_source_total_products,
            )
            current_product_title = tracker_state.current_product_title

        if db_expected_products > 0:
            products_progress_percent = int((db_processed_products * 100) / db_expected_products)
        elif job.status in [JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED]:
            products_progress_percent = 100
        else:
            products_progress_percent = 0
        products_progress_percent = max(0, min(products_progress_percent, 100))
        failed_products = max((db_expected_products - db_processed_products), 0)

        # While run is still active and more sources remain, keep products progress below 100
        # because expected_products grows as each source discovery completes.
        if job.status in [JobStatus.PENDING, JobStatus.IN_PROGRESS] and processed_sources < total_sources:
            products_progress_percent = min(products_progress_percent, 99)

        site_products_total = (
            self.db.query(ParserProduct)
            .filter(ParserProduct.deleted_at.is_(None))
            .count()
        )

        return JobLatestResponse(
            job_id=job.id,
            status=job.status,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            next_scheduled_at=next_scheduled,
            total_products=job.total_products,
            new_products=job.new_products or 0,
            updated_products=job.updated_products or 0,
            new_images=job.new_images or 0,
            total_sources=total_sources,
            processed_sources=processed_sources,
            progress_percent=progress_percent,
            processed_products=db_processed_products,
            expected_products=db_expected_products,
            failed_products=failed_products,
            products_progress_percent=products_progress_percent,
            current_source_name=current_source_name,
            current_source_index=current_source_index,
            current_stage=current_stage,
            current_source_processed_products=current_source_processed_products,
            current_source_total_products=current_source_total_products,
            current_product_title=current_product_title,
            site_products_total=site_products_total,
            can_cancel=job.status in [JobStatus.PENDING, JobStatus.IN_PROGRESS],
            sync_period_minutes=settings.parser_sync_period_minutes,
        )

    def cancel_job(self, job_id: str) -> JobCancelResponse:
        job = self.parser_job_service.get_job(job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found",
            )

        if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            return JobCancelResponse(
                id=job.id,
                status=job.status,
                message="Job already finished",
            )

        self.parser_job_service.job_repo.mark_cancelled(job)

        self.db.query(ParserJobSourceRun).filter(
            ParserJobSourceRun.job_id == job.id,
            ParserJobSourceRun.status.in_([SourceRunStatus.PENDING, SourceRunStatus.IN_PROGRESS]),
        ).update(
            {
                "status": SourceRunStatus.FAILED,
                "error_message": "Cancelled by user",
            },
            synchronize_session=False,
        )

        self.db.commit()
        job_progress_tracker.finish_job(job_id=job.id)
        return JobCancelResponse(
            id=job.id,
            status=JobStatus.CANCELLED,
            message="Job cancelled",
        )

    def get_job(self, job_id: str) -> JobResponse:
        job = self.parser_job_service.get_job(job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found",
            )

        summary = self.parser_job_service.get_job_summary(job_id)
        return JobResponse(**summary)

    def get_jobs_history(self, limit: int = 20, offset: int = 0) -> list[JobResponse]:
        bounded_limit = min(limit, settings.sync_jobs_history_max_limit)
        repo = self.parser_job_service.job_repo

        jobs = (
            repo.query()
            .filter(repo.model_class.deleted_at.is_(None))
            .order_by(repo.model_class.created_at.desc())
            .offset(offset)
            .limit(bounded_limit)
            .all()
        )

        return [
            JobResponse(
                id=job.id,
                status=job.status,
                triggered_by=job.triggered_by,
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                total_products=job.total_products,
                new_products=job.new_products or 0,
                updated_products=job.updated_products or 0,
                new_images=job.new_images or 0,
                error_count=job.error_count,
                http_429_count=job.http_429_count,
                http_5xx_count=job.http_5xx_count,
            )
            for job in jobs
        ]
