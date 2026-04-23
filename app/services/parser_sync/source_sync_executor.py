"""Executor for syncing one source within a parser job."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import SourceRunStatus
from app.services.parser_sync.product_sync_service import ParserProductSyncService
from app.services.parser_sync.source_run_service import ParserSourceRunService
from app.services.parser_sync.source_sync_result_mapper import (
    build_run_error_message,
    extract_result_counters,
    resolve_source_run_status,
)


LOGGER = logging.getLogger(__name__)


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
        discover_source: Callable[..., object],
    ):
        self.session = session
        self.source_run_service = source_run_service
        self.product_sync_service = product_sync_service
        self.discover_source = discover_source

    def sync_source(
        self,
        *,
        job_id: str,
        source_id: int,
        base_url: str,
        parser_type: str,
        on_source_discovered: Optional[Callable[[int], None]] = None,
        on_product_processed: Optional[Callable[[str | None, int, int], None]] = None,
        on_discovery_progress: Optional[Callable[[], None]] = None,
        on_discovery_detail_progress: Optional[Callable[[dict], None]] = None,
    ) -> SourceSyncStats:
        source_run = self.source_run_service.create_source_run(job_id=job_id, source_id=source_id)
        if not source_run:
            return SourceSyncStats(errors=1)

        self.source_run_service.mark_source_run_started(source_run.id)
        self.session.commit()

        try:
            source_deadline_monotonic = time.monotonic() + float(settings.parser_source_timeout_sec)
            LOGGER.info(
                "Source sync started source_id=%s parser_type=%s base_url=%s timeout_sec=%s",
                source_id,
                parser_type,
                base_url,
                settings.parser_source_timeout_sec,
            )
            result = self.discover_source(
                parser_type,
                base_url,
                deadline_monotonic=source_deadline_monotonic,
                on_progress=on_discovery_progress,
                on_detail_progress=on_discovery_detail_progress,
            )
            LOGGER.info(
                "Source discovery completed source_id=%s discovered=%s fetched=%s failed=%s mode=%s",
                source_id,
                result.product_urls_found,
                result.products_fetch_succeeded,
                result.products_fetch_failed,
                result.discovery_mode,
            )

            if on_source_discovered:
                on_source_discovered(len(result.previews))

            # Browser fallback already reports source-level progress from runner logs.
            should_emit_row_progress = "browser_parser" not in str(result.discovery_mode or "").lower()
            created, updated = self.product_sync_service.sync_source_products(
                source_id,
                result.previews,
                on_product_processed=(
                    on_product_processed
                    if (on_product_processed and should_emit_row_progress)
                    else None
                ),
            )
            fetched, errors, http_429, http_5xx = extract_result_counters(result)
            stats = SourceSyncStats(
                created=created,
                updated=updated,
                fetched=fetched,
                errors=errors,
                http_429=http_429,
                http_5xx=http_5xx,
            )

            run_status = resolve_source_run_status(result)

            run_error_message = build_run_error_message(
                result,
                error_details_limit=settings.parser_default_error_details_limit,
            )

            self.source_run_service.update_source_run(
                source_run.id,
                status=run_status,
                products_discovered=result.product_urls_found,
                products_fetched=result.products_fetch_succeeded,
                products_failed=result.products_fetch_failed,
                discovery_mode=result.discovery_mode,
                error_message=run_error_message,
            )
            self.session.commit()
            LOGGER.info(
                "Source sync finished source_id=%s status=%s discovered=%s fetched=%s failed=%s",
                source_id,
                run_status.value,
                result.product_urls_found,
                result.products_fetch_succeeded,
                result.products_fetch_failed,
            )
            return stats
        except Exception as exc:
            LOGGER.exception(
                "Source sync failed for source_id=%s parser_type=%s base_url=%s",
                source_id,
                parser_type,
                base_url,
            )
            self.session.rollback()
            self.source_run_service.update_source_run(
                source_run.id,
                status=SourceRunStatus.FAILED,
                error_message=f"{type(exc).__name__}: {exc}",
            )
            self.session.commit()
            return SourceSyncStats(errors=1)
