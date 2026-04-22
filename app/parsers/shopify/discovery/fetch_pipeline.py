"""Preview fetch pipeline for Shopify discovery."""

from __future__ import annotations

from dataclasses import dataclass
import time
import logging
from typing import Any, Callable

from app.core.config import settings
from app.parsers.shopify.preview_fetcher import FetchOutcome, fetch_many_product_previews

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PreviewFetchPipelineResult:
    """Collected previews and diagnostics for discovered product URLs."""

    previews: list[Any]
    final_errors: list[tuple[str, str]]
    http_429_count: int
    http_5xx_count: int
    second_pass_attempted: int
    second_pass_recovered: int


def run_preview_fetch_pipeline(
    *,
    base_url: str,
    target_urls: list[str],
    payload_cache: dict[str, dict[str, Any]],
    timeout_sec: float,
    parallel_workers: int,
    max_retries: int,
    retry_backoff_sec: float,
    second_pass_enabled: bool,
    second_pass_timeout_sec: float,
    build_preview: Callable[..., Any],
    deadline_monotonic: float | None = None,
    on_progress: Callable[[], None] | None = None,
    on_detail_progress: Callable[[dict], None] | None = None,
) -> PreviewFetchPipelineResult:
    """Fetch previews for URLs with optional second pass on failures."""
    LOGGER.info(
        "shopify fetch pipeline started base_url=%s targets=%s workers=%s",
        base_url,
        len(target_urls),
        parallel_workers,
    )
    if not target_urls:
        return PreviewFetchPipelineResult(
            previews=[],
            final_errors=[],
            http_429_count=0,
            http_5xx_count=0,
            second_pass_attempted=0,
            second_pass_recovered=0,
        )

    previews: list[Any] = []
    final_errors: list[tuple[str, str]] = []
    http_429_count = 0
    http_5xx_count = 0
    second_pass_attempted = 0
    second_pass_recovered = 0

    by_url: dict[str, FetchOutcome] = {}
    first_pass_failures: list[str] = []
    first_pass_processed = 0

    if on_detail_progress:
        on_detail_progress(
            {
                "stage": "syncing_products",
                "products_total": len(target_urls),
                "products_processed": 0,
            }
        )

    def on_outcome_processed(_outcome: FetchOutcome) -> None:
        nonlocal first_pass_processed
        first_pass_processed += 1
        if on_progress:
            on_progress()
        if on_detail_progress and (
            first_pass_processed == len(target_urls)
            or first_pass_processed == 1
            or first_pass_processed % 25 == 0
        ):
            on_detail_progress(
                {
                    "stage": "syncing_products",
                    "products_total": len(target_urls),
                    "products_processed": first_pass_processed,
                }
            )

    processed_first_pass = 0
    for outcome in fetch_many_product_previews(
        base_url=base_url,
        product_urls=target_urls,
        payload_cache=payload_cache,
        timeout_sec=timeout_sec,
        parallel_workers=parallel_workers,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        build_preview=build_preview,
        target_currency=settings.parser_shopify_target_currency,
        deadline_monotonic=deadline_monotonic,
        on_outcome=on_outcome_processed,
    ):
        by_url[outcome.product_url] = outcome
        processed_first_pass += 1
        if processed_first_pass % 200 == 0:
            LOGGER.info(
                "shopify fetch pipeline first pass base_url=%s processed=%s/%s",
                base_url,
                processed_first_pass,
                len(target_urls),
            )

    for product_url in target_urls:
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            first_pass_failures.append(product_url)
            final_errors.append((product_url, "SOURCE_TIMEOUT"))
            continue
        outcome = by_url.get(product_url)
        if not outcome:
            first_pass_failures.append(product_url)
            final_errors.append((product_url, "внутренняя ошибка: нет результата воркера"))
            continue

        http_429_count += outcome.http_429_count
        http_5xx_count += outcome.http_5xx_count

        if outcome.preview:
            previews.append(outcome.preview)
            continue

        first_pass_failures.append(product_url)
        final_errors.append((product_url, outcome.error or "не удалось получить товар"))

    if second_pass_enabled and first_pass_failures:
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            return PreviewFetchPipelineResult(
                previews=previews,
                final_errors=final_errors,
                http_429_count=http_429_count,
                http_5xx_count=http_5xx_count,
                second_pass_attempted=0,
                second_pass_recovered=0,
            )
        second_pass_attempted = len(first_pass_failures)
        second_pass_timeout = max(second_pass_timeout_sec, timeout_sec)

        second_pass_results = fetch_many_product_previews(
            base_url=base_url,
            product_urls=first_pass_failures,
            payload_cache=payload_cache,
            timeout_sec=second_pass_timeout,
            parallel_workers=max(1, min(parallel_workers, settings.parser_second_pass_max_workers)),
            max_retries=max_retries + 1,
            retry_backoff_sec=max(retry_backoff_sec, settings.parser_second_pass_min_backoff_sec),
            build_preview=build_preview,
            target_currency=settings.parser_shopify_target_currency,
            deadline_monotonic=deadline_monotonic,
            on_outcome=on_outcome_processed,
        )
        second_pass_by_url = {item.product_url: item for item in second_pass_results}

        refreshed_errors: list[tuple[str, str]] = []
        for product_url, first_error in final_errors:
            second = second_pass_by_url.get(product_url)
            if not second:
                refreshed_errors.append((product_url, first_error))
                continue

            http_429_count += second.http_429_count
            http_5xx_count += second.http_5xx_count

            if second.preview:
                previews.append(second.preview)
                second_pass_recovered += 1
            else:
                refreshed_errors.append((product_url, second.error or first_error))

        final_errors = refreshed_errors
    LOGGER.info(
        "shopify fetch pipeline finished base_url=%s success=%s failed=%s second_pass_recovered=%s",
        base_url,
        len(previews),
        len(final_errors),
        second_pass_recovered,
    )
    return PreviewFetchPipelineResult(
        previews=previews,
        final_errors=final_errors,
        http_429_count=http_429_count,
        http_5xx_count=http_5xx_count,
        second_pass_attempted=second_pass_attempted,
        second_pass_recovered=second_pass_recovered,
    )
