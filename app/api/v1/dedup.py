"""API for duplicate candidates and moderation actions."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.parser import (
    DedupCandidateListResponse,
    DedupMergeRequest,
    DedupRejectRequest,
)
from app.services.dedup_service import DedupService

router = APIRouter(tags=["dedup"])


@router.get("/dedup/candidates", response_model=DedupCandidateListResponse)
def get_dedup_candidates(
    limit: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Build duplicate candidates from active parser products."""
    service = DedupService(db)
    return service.get_candidates(limit=limit)


@router.post("/dedup/merge")
def merge_duplicate(payload: DedupMergeRequest, db: Session = Depends(get_db)):
    """Merge two products by keeping primary and soft-deleting duplicate."""
    service = DedupService(db)
    return service.merge_duplicate(payload)


@router.post("/dedup/reject")
def reject_duplicate(payload: DedupRejectRequest, db: Session = Depends(get_db)):
    """Mark pair as non-duplicate to hide from moderation queue."""
    service = DedupService(db)
    return service.reject_duplicate(payload)
