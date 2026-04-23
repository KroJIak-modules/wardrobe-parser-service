"""Fallback discovery chain for Shopify URLs."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.parsers.shopify.discovery.api import (
    discover_collections_all_html_products,
    discover_collections_all_products,
    discover_products_json,
)
from app.parsers.shopify.discovery.progress import DiscoveryProgressEmitter


def collect_from_fallbacks(
    *,
    base_url: str,
    max_products: int,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    session,
    deadline_monotonic: float | None,
    progress: DiscoveryProgressEmitter,
    warnings: list[str],
    payload_cache: dict[str, dict[str, Any]],
    source_from_fallback: bool,
    sitemap_rate_limited: bool,
) -> tuple[bool, bool]:
    """Collect URLs from API and HTML fallback chain."""
    stop_early = False

    if max_products > 0:
        progress.ping()
        products_api_result = discover_products_json(
            base_url=base_url,
            max_products=max_products,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            session=session,
            deadline_monotonic=deadline_monotonic,
        )
        warnings.extend(products_api_result.warnings)
        added_from_fallback = False
        for url in products_api_result.urls:
            was_known = url in progress.discovered_set
            if not was_known and len(progress.discovered_urls) < max_products:
                if progress.append_url(url):
                    added_from_fallback = True
            payload = products_api_result.payloads.get(url)
            if isinstance(payload, dict) and url in progress.discovered_set:
                payload_cache[url] = payload
        if added_from_fallback:
            source_from_fallback = True
        if (
            settings.parser_discovery_fail_fast_on_rate_limit
            and not progress.discovered_urls
            and sitemap_rate_limited
            and products_api_result.rate_limited
        ):
            warnings.append("Discovery остановлен раньше: магазин отвечает HTTP 429 на sitemap и products.json")
            stop_early = True
            return source_from_fallback, stop_early

    if len(progress.discovered_urls) < max_products:
        progress.ping()
        collections_result = discover_collections_all_products(
            base_url=base_url,
            max_products=max_products - len(progress.discovered_urls),
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            session=session,
            deadline_monotonic=deadline_monotonic,
        )
        warnings.extend(collections_result.warnings)
        if collections_result.urls:
            source_from_fallback = True
        for url in collections_result.urls:
            if len(progress.discovered_urls) >= max_products:
                break
            progress.append_url(url)
            payload = collections_result.payloads.get(url)
            if isinstance(payload, dict):
                payload_cache[url] = payload

    if len(progress.discovered_urls) < max_products:
        progress.ping()
        html_collections_result = discover_collections_all_html_products(
            base_url=base_url,
            max_products=max_products - len(progress.discovered_urls),
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            session=session,
            deadline_monotonic=deadline_monotonic,
        )
        warnings.extend(html_collections_result.warnings)
        if html_collections_result.urls:
            source_from_fallback = True
        for url in html_collections_result.urls:
            if len(progress.discovered_urls) >= max_products:
                break
            progress.append_url(url)

    return source_from_fallback, stop_early
