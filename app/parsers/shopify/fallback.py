"""Fallback orchestration for Shopify discovery."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable
import logging

from app.core.config import settings
from app.parsers.browser_parser.engine import BrowserParserEngine
from app.parsers.shopify.models import ShopifyDiscoveryResult

LOGGER = logging.getLogger(__name__)


def should_use_browser_fallback(result: ShopifyDiscoveryResult) -> bool:
    """Decide whether browser-parser fallback should be invoked."""
    attempted = max(0, int(result.products_fetch_attempted or 0))
    succeeded = max(0, int(result.products_fetch_succeeded or 0))
    discovered = max(0, int(result.product_urls_found or 0))
    failed = max(0, int(result.products_fetch_failed or 0))

    if discovered == 0:
        return True
    if attempted == 0:
        return True
    if succeeded == 0:
        return True
    if failed >= attempted:
        return True

    success_ratio = succeeded / attempted if attempted else 0.0
    if success_ratio < settings.parser_browser_fallback_min_success_ratio:
        return True

    return False


def merge_prefer_more_complete(
    *,
    primary: ShopifyDiscoveryResult,
    fallback: ShopifyDiscoveryResult,
) -> ShopifyDiscoveryResult:
    """Return the better result; preserve diagnostics from both runs."""
    primary_score = (
        int(primary.products_fetch_succeeded),
        int(primary.product_urls_found),
        -int(primary.products_fetch_failed),
    )
    fallback_score = (
        int(fallback.products_fetch_succeeded),
        int(fallback.product_urls_found),
        -int(fallback.products_fetch_failed),
    )
    winner = fallback if fallback_score > primary_score else primary
    loser = primary if winner is fallback else fallback

    merged_warnings = list(winner.warnings or [])
    merged_warnings.extend(
        f"[fallback:{loser.discovery_mode}] {item}"
        for item in (loser.warnings or [])[:50]
    )
    merged_error_details = list(winner.error_details or [])
    merged_error_details.extend(
        f"[fallback:{loser.discovery_mode}] {item}"
        for item in (loser.error_details or [])[:200]
    )

    return replace(
        winner,
        warnings=merged_warnings,
        error_details=merged_error_details,
        http_429_count=int(winner.http_429_count) + int(loser.http_429_count),
        http_5xx_count=int(winner.http_5xx_count) + int(loser.http_5xx_count),
    )


def discover_with_browser_fallback(
    *,
    primary_result: ShopifyDiscoveryResult,
    base_url: str,
    deadline_monotonic: float | None = None,
    on_progress: Callable[[], None] | None = None,
) -> ShopifyDiscoveryResult:
    """Run browser fallback and merge with primary Shopify result."""
    if not settings.parser_browser_fallback_enabled:
        return primary_result
    if not should_use_browser_fallback(primary_result):
        return primary_result

    fallback_engine = BrowserParserEngine()
    try:
        fallback_result = fallback_engine.discover(
            base_url,
            # Do not reuse primary source deadline here: primary Shopify pass may consume
            # most/all budget and starve fallback before it even starts.
            # Browser parser has its own hard process timeout.
            deadline_monotonic=None,
            on_progress=on_progress,
            export_concurrency=max(
                1,
                int(settings.parser_browser_fallback_export_concurrency),
            ),
        )
    except Exception as exc:
        LOGGER.exception("Browser fallback failed for %s", base_url)
        return replace(
            primary_result,
            warnings=list(primary_result.warnings or []) + [f"browser fallback failed: {exc}"],
        )

    fallback_result = replace(
        fallback_result,
        discovery_mode=f"{fallback_result.discovery_mode}+shopify_fallback",
    )
    return merge_prefer_more_complete(primary=primary_result, fallback=fallback_result)
