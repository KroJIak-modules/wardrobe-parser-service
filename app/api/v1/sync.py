"""
API endpoints for sync job management.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.parser import (
    JobResponse,
    JobLatestResponse,
    JobCreateRequest,
    JobCreateResponse,
)
from app.services.parser_job import ParserJobService

router = APIRouter(tags=["sync"])


@router.post("/jobs", response_model=JobCreateResponse, status_code=status.HTTP_201_CREATED)
def create_sync_job(
    request: JobCreateRequest,
    db: Session = Depends(get_db)
):
    """
    Create manual sync job.
    
    Returns job ID (UUID). Job will start immediately if no other job is running.
    Frontend should poll GET /api/v1/jobs/latest or GET /api/v1/jobs/{job_id} for status.
    
    If sync already in progress, returns 409 Conflict.
    """
    service = ParserJobService(db)
    
    # Check if sync is already running
    if service.is_sync_in_progress():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sync already in progress. Wait for completion or check status at GET /api/v1/jobs/latest"
        )
    
    job = service.create_sync_job(triggered_by=request.triggered_by)
    
    return JobCreateResponse(
        id=job.id,
        status=job.status,
        created_at=job.created_at,
    )


@router.get("/jobs/latest", response_model=Optional[JobLatestResponse])
def get_latest_job(db: Session = Depends(get_db)):
    """
    Get latest job status (most recent completed or in-progress).
    
    Used by frontend to:
    - Show "Last sync: 12:34"
    - Show "Next sync: 17:34"
    - Determine if "Sync Now" button should be enabled
    - Show NEW/UPDATED/DELETED product counts
    """
    service = ParserJobService(db)
    job = service.get_latest_job()
    
    if not job:
        return None
    
    next_scheduled = service.get_next_scheduled_sync()
    
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
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    """
    Get detailed job status including per-source execution.
    
    Useful for debugging or detailed monitoring.
    """
    service = ParserJobService(db)
    job = service.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    summary = service.get_job_summary(job_id)
    
    return JobResponse(**summary)


@router.get("/jobs", response_model=list[JobResponse])
def get_jobs_history(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    Get job history (recent sync jobs).
    
    Useful for monitoring/debugging.
    
    Query params:
    - limit: Number of jobs (default 20, max 100)
    - offset: Pagination offset (default 0)
    """
    if limit > 100:
        limit = 100
    
    service = ParserJobService(db)
    repo = service.job_repo
    
    jobs = (
        repo.query()
        .filter(repo.model_class.deleted_at.is_(None))
        .order_by(repo.model_class.created_at.desc())
        .offset(offset)
        .limit(limit)
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
