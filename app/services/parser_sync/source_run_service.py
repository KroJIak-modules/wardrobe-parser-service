"""Service for parser job source run lifecycle operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import ParserJobSourceRun, SourceRunStatus
from app.repositories import ParserJobRepository


class ParserSourceRunService:
    """Manages creation and state transitions of source runs within a sync job."""

    def __init__(self, session: Session, job_repo: ParserJobRepository):
        self.session = session
        self.job_repo = job_repo

    def create_source_run(self, job_id: str, source_id: int) -> Optional[ParserJobSourceRun]:
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
