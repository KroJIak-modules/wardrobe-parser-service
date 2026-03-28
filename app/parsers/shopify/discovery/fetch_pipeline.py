"""Preview fetch pipeline for Shopify discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.parsers.shopify.preview_fetcher import FetchOutcome, fetch_many_product_previews


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
) -> PreviewFetchPipelineResult:
    """Fetch previews for URLs with optional second pass on failures."""
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

    for outcome in fetch_many_product_previews(
        base_url=base_url,
        product_urls=target_urls,
        payload_cache=payload_cache,
        timeout_sec=timeout_sec,
        parallel_workers=parallel_workers,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        build_preview=build_preview,
    ):
        by_url[outcome.product_url] = outcome

    for product_url in target_urls:
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
        second_pass_attempted = len(first_pass_failures)
        second_pass_timeout = max(second_pass_timeout_sec, timeout_sec)

        second_pass_results = fetch_many_product_previews(
            base_url=base_url,
            product_urls=first_pass_failures,
            payload_cache=payload_cache,
            timeout_sec=second_pass_timeout,
            parallel_workers=max(1, min(parallel_workers, 8)),
            max_retries=max_retries + 1,
            retry_backoff_sec=max(retry_backoff_sec, 0.5),
            build_preview=build_preview,
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

    return PreviewFetchPipelineResult(
        previews=previews,
        final_errors=final_errors,
        http_429_count=http_429_count,
        http_5xx_count=http_5xx_count,
        second_pass_attempted=second_pass_attempted,
        second_pass_recovered=second_pass_recovered,
    )
