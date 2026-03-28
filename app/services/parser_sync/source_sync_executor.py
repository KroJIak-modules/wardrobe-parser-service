"""Executor for syncing one source within a parser job."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.models import SourceRunStatus
from app.services.parser_sync.product_sync_service import ParserProductSyncService
from app.services.parser_sync.source_run_service import ParserSourceRunService


@dataclass(slots=True)
class SourceSyncStats:
    """Counters returned from one source synchronization attempt."""

    created: int = 0
    updated: int = 0
    fetched: int = 0
    errors: int = 0
    http_429: int = 0
    http_5xx: int = 0


class ParserSourceSyncExecutor:
    """Coordinates source-run lifecycle and product synchronization for one source."""

    def __init__(
        self,
        session: Session,
        source_run_service: ParserSourceRunService,
        product_sync_service: ParserProductSyncService,
        discover_source: Callable[[str, str], object],
    ):
        self.session = session
        self.source_run_service = source_run_service
        self.product_sync_service = product_sync_service
        self.discover_source = discover_source

    def sync_source(self, *, job_id: str, source_id: int, base_url: str, parser_type: str) -> SourceSyncStats:
        source_run = self.source_run_service.create_source_run(job_id=job_id, source_id=source_id)
        if not source_run:
            return SourceSyncStats(errors=1)

        self.source_run_service.mark_source_run_started(source_run.id)

        try:
            result = self.discover_source(parser_type, base_url)

            created, updated = self.product_sync_service.sync_source_products(source_id, result.previews)
            stats = SourceSyncStats(
                created=created,
                updated=updated,
                fetched=result.products_fetch_succeeded,
                errors=result.products_fetch_failed,
                http_429=result.http_429_count,
                http_5xx=result.http_5xx_count,
            )

            self.source_run_service.update_source_run(
                source_run.id,
                status=SourceRunStatus.SUCCESS if result.products_fetch_failed == 0 else SourceRunStatus.PARTIAL,
                products_discovered=result.product_urls_found,
                products_fetched=result.products_fetch_succeeded,
                products_failed=result.products_fetch_failed,
                discovery_mode=result.discovery_mode,
                error_message="; ".join(result.error_details[:3]) if result.error_details else None,
            )
            self.session.commit()
            return stats
        except Exception as exc:
            self.source_run_service.update_source_run(
                source_run.id,
                status=SourceRunStatus.FAILED,
                error_message=str(exc),
            )
            self.session.commit()
            return SourceSyncStats(errors=1)
