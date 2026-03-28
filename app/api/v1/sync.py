"""
API endpoints for sync job management.
"""

from typing import Optional
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.parser import (
    JobResponse,
    JobLatestResponse,
    JobCreateRequest,
    JobCreateResponse,
)
from app.services.sync_job_service import SyncJobService

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
    service = SyncJobService(db)
    return service.create_sync_job(request)


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
    service = SyncJobService(db)
    return service.get_latest_job()


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    """
    Get detailed job status including per-source execution.
    
    Useful for debugging or detailed monitoring.
    """
    service = SyncJobService(db)
    return service.get_job(job_id)


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
    service = SyncJobService(db)
    return service.get_jobs_history(limit=limit, offset=offset)
