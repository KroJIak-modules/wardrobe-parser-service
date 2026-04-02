"""Executor for syncing one source within a parser job."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ProductStatus, SourceRunStatus
from app.parsers.shopify.models import ShopifyDiscoveryResult, ShopifyProductPreview
from app.parsers.shopify.parser import ShopifyParser
from app.services.parser_sync.product_sync_service import ParserProductSyncService
from app.services.parser_sync.source_run_service import ParserSourceRunService


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

    @staticmethod
    def _should_retry_empty_discovery(
        *,
        previous_products: int,
        product_urls_found: int,
        attempt_number: int,
        max_attempts: int,
    ) -> bool:
        """Retry only when discovery unexpectedly returns zero for a known source."""
        return previous_products > 0 and product_urls_found == 0 and attempt_number < max_attempts

    @staticmethod
    def _build_empty_discovery_error(previous_products: int, attempts_used: int) -> str:
        """Build readable diagnostic for sources that suddenly returned no URLs."""
        if attempts_used <= 1:
            return f"empty discovery: no URLs found, previously had {previous_products} products"
        return (
            f"empty discovery after {attempts_used} attempts: "
            f"no URLs found, previously had {previous_products} products"
        )

    def _recover_shopify_from_existing_urls(
        self,
        *,
        source_id: int,
        base_url: str,
        deadline_monotonic: float | None = None,
    ):
        """Fallback for completeness: retry product fetch from previously known URLs."""
        known_products = []
        page_size = 2000
        offset = 0
        while True:
            batch = self.product_sync_service.product_repo.get_by_source(
                source_id,
                skip=offset,
                limit=page_size,
                active_only=True,
            )
            if not batch:
                break
            known_products.extend(batch)
            if len(batch) < page_size:
                break
            offset += len(batch)

        known_urls = [item.url for item in known_products if item.url]
        if not known_urls:
            return None

        LOGGER.warning(
            "Empty discovery fallback: source_id=%s base_url=%s known_urls=%s",
            source_id,
            base_url,
            len(known_urls),
        )

        if not settings.parser_recovery_network_enabled:
            previews = []
            for product in known_products:
                url = (product.url or "").strip()
                handle = (product.handle or "").strip()
                if not url or not handle:
                    continue
                previews.append(
                    ShopifyProductPreview(
                        product_url=url,
                        handle=handle,
                        product_id=str(product.id),
                        title=product.title,
                        vendor=product.vendor,
                        product_type=product.product_type,
                        price=None if product.price is None else str(product.price),
                        currency=product.currency,
                        image_urls=list(product.image_urls or []),
                        payload_source="cache_fallback",
                        available=product.status == ProductStatus.AVAILABLE,
                        variants=list(product.variants or []),
                    )
                )

            return ShopifyDiscoveryResult(
                base_url=base_url.rstrip("/"),
                sitemap_url=f"{base_url.rstrip('/')}/sitemap.xml",
                discovery_mode="cache_fallback",
                product_sitemaps_found=0,
                product_urls_found=len(previews),
                requested_previews=len(previews),
                products_fetch_attempted=len(previews),
                products_fetch_succeeded=len(previews),
                products_fetch_failed=0,
                http_429_count=0,
                http_5xx_count=0,
                second_pass_attempted=0,
                second_pass_recovered=0,
                warnings=[f"empty discovery fallback: reused {len(previews)} cached products"],
                error_details=["cache fallback used for empty discovery"],
                previews=previews,
            )

        return ShopifyParser.recover_from_known_product_urls(
            base_url,
            known_product_urls=known_urls,
            timeout_sec=settings.parser_recovery_timeout_sec,
            parallel_workers=settings.parser_recovery_parallel_workers,
            max_retries=settings.parser_recovery_max_retries,
            retry_backoff_sec=settings.parser_recovery_retry_backoff_sec,
            second_pass_enabled=settings.parser_default_second_pass_enabled,
            second_pass_timeout_sec=settings.parser_recovery_second_pass_timeout_sec,
            error_details_limit=settings.parser_default_error_details_limit,
            deadline_monotonic=deadline_monotonic,
        )

    def sync_source(
        self,
        *,
        job_id: str,
        source_id: int,
        base_url: str,
        parser_type: str,
        on_source_discovered: Optional[Callable[[int], None]] = None,
        on_product_processed: Optional[Callable[[str | None, int, int], None]] = None,
    ) -> SourceSyncStats:
        source_run = self.source_run_service.create_source_run(job_id=job_id, source_id=source_id)
        if not source_run:
            return SourceSyncStats(errors=1)

        self.source_run_service.mark_source_run_started(source_run.id)
        self.session.commit()

        try:
            stall_timeout_sec = float(settings.parser_source_timeout_sec)
            source_deadline_monotonic = time.monotonic() + stall_timeout_sec

            def bump_progress() -> None:
                nonlocal source_deadline_monotonic
                source_deadline_monotonic = time.monotonic() + stall_timeout_sec

            def ensure_source_not_timed_out(stage: str) -> None:
                if time.monotonic() >= source_deadline_monotonic:
                    raise TimeoutError(
                        f"SOURCE_STALLED_TIMEOUT: no progress for {stall_timeout_sec:.0f}s at stage={stage}"
                    )

            previous_products = self.product_sync_service.product_repo.count_by_source(source_id)
            max_attempts = 1 + settings.parser_empty_discovery_source_retries
            result = None
            attempts_used = 0

            while attempts_used < max_attempts:
                ensure_source_not_timed_out("discovery")
                attempts_used += 1
                result = self.discover_source(
                    parser_type,
                    base_url,
                    deadline_monotonic=source_deadline_monotonic,
                )
                bump_progress()
                if not self._should_retry_empty_discovery(
                    previous_products=previous_products,
                    product_urls_found=result.product_urls_found,
                    attempt_number=attempts_used,
                    max_attempts=max_attempts,
                ):
                    break

                delay_sec = settings.parser_empty_discovery_retry_backoff_sec * attempts_used
                LOGGER.warning(
                    "Retrying source after empty discovery source_id=%s base_url=%s attempt=%s/%s delay=%.2fs",
                    source_id,
                    base_url,
                    attempts_used,
                    max_attempts,
                    delay_sec,
                )
                if delay_sec > 0:
                    sleep_cap = source_deadline_monotonic - time.monotonic()
                    if sleep_cap <= 0:
                        ensure_source_not_timed_out("retry_backoff")
                    time.sleep(min(delay_sec, sleep_cap))

            if result is None:
                raise RuntimeError("Discovery returned no result")
            ensure_source_not_timed_out("post_discovery")

            if attempts_used > 1 and result.product_urls_found > 0:
                result.warnings = [
                    f"empty discovery recovered on attempt {attempts_used}"
                ] + list(result.warnings or [])

            used_history_fallback = False
            if (
                parser_type == "shopify"
                and settings.parser_recover_from_existing_urls_enabled
                and previous_products > 0
                and result.product_urls_found == 0
            ):
                recovered_result = self._recover_shopify_from_existing_urls(
                    source_id=source_id,
                    base_url=base_url,
                    deadline_monotonic=source_deadline_monotonic,
                )
                if recovered_result:
                    recovered_result.http_429_count += result.http_429_count
                    recovered_result.http_5xx_count += result.http_5xx_count
                    recovered_result.warnings = list(result.warnings or []) + list(recovered_result.warnings or [])
                    if result.error_details:
                        recovered_result.error_details = list(result.error_details) + list(recovered_result.error_details)
                    result = recovered_result
                    used_history_fallback = True

            if on_source_discovered:
                bump_progress()
                on_source_discovered(len(result.previews))

            ensure_source_not_timed_out("before_product_sync")
            def on_product_processed_with_heartbeat(
                product_title: str | None,
                processed_in_source: int,
                total_in_source: int,
            ) -> None:
                bump_progress()
                if on_product_processed:
                    on_product_processed(
                        product_title,
                        processed_in_source,
                        total_in_source,
                    )

            created, updated = self.product_sync_service.sync_source_products(
                source_id,
                result.previews,
                on_product_processed=(
                    on_product_processed_with_heartbeat if on_product_processed else None
                ),
            )
            stats = SourceSyncStats(
                created=created,
                updated=updated,
                fetched=result.products_fetch_succeeded,
                errors=result.products_fetch_failed,
                http_429=result.http_429_count,
                http_5xx=result.http_5xx_count,
            )

            run_status = SourceRunStatus.SUCCESS
            run_error_message = (
                "; ".join(result.error_details[: settings.parser_default_error_details_limit])
                if result.error_details
                else None
            )

            if result.products_fetch_failed > 0:
                run_status = SourceRunStatus.PARTIAL
            elif result.product_urls_found == 0 and previous_products > 0:
                run_status = SourceRunStatus.PARTIAL
                run_error_message = self._build_empty_discovery_error(
                    previous_products=previous_products,
                    attempts_used=attempts_used,
                )

            if used_history_fallback:
                run_status = SourceRunStatus.PARTIAL
                recovery_note = (
                    "empty discovery fallback via known URLs: "
                    f"fetched {result.products_fetch_succeeded}/{result.products_fetch_attempted}"
                )
                if run_error_message:
                    run_error_message = f"{recovery_note}; {run_error_message}"
                else:
                    run_error_message = recovery_note

            if not run_error_message and getattr(result, "warnings", None):
                warnings = [str(item).strip() for item in (result.warnings or []) if str(item).strip()]
                if warnings:
                    run_error_message = "; ".join(warnings[:2])

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
            return stats
        except Exception as exc:
            LOGGER.exception(
                "Source sync failed for source_id=%s parser_type=%s base_url=%s",
                source_id,
                parser_type,
                base_url,
            )
            # Recover session after any DB error to allow marking source run as failed.
            self.session.rollback()
            self.source_run_service.update_source_run(
                source_run.id,
                status=SourceRunStatus.FAILED,
                error_message=f"{type(exc).__name__}: {exc}",
            )
            self.session.commit()
            return SourceSyncStats(errors=1)
