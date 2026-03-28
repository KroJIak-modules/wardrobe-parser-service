"""Service layer for sync job API endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.parser import JobCreateRequest, JobCreateResponse, JobLatestResponse, JobResponse
from app.services.parser_sync.job_service import ParserJobService


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

        job = self.parser_job_service.create_sync_job(triggered_by=request.triggered_by)
        return JobCreateResponse(
            id=job.id,
            status=job.status,
            created_at=job.created_at,
        )

    def get_latest_job(self) -> Optional[JobLatestResponse]:
        job = self.parser_job_service.get_latest_job()
        if not job:
            return None

        next_scheduled = self.parser_job_service.get_next_scheduled_sync()
        return JobLatestResponse(
            status=job.status,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            next_scheduled_at=next_scheduled,
            total_products=job.total_products,
            new_products=job.new_products or 0,
            updated_products=job.updated_products or 0,
            new_images=job.new_images or 0,
            sync_period_minutes=settings.parser_sync_period_minutes,
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
        bounded_limit = min(limit, 100)
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
