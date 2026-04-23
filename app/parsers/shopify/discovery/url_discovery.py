"""URL discovery orchestration for Shopify parser."""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.parsers.shopify.http_client import ShopifyHTTPClient
from app.parsers.shopify.discovery.fallback_discovery import collect_from_fallbacks
from app.parsers.shopify.discovery.progress import DiscoveryProgressEmitter
from app.parsers.shopify.discovery.sitemap_discovery import collect_from_sitemap
from app.parsers.shopify.discovery.models import DiscoveryCollectionResult

LOGGER = logging.getLogger(__name__)


def _build_result(
    *,
    sitemap_url: str,
    discovered_urls: list[str],
    payload_cache: dict[str, dict[str, Any]],
    warnings: list[str],
    source_from_sitemap: bool,
    source_from_fallback: bool,
    product_sitemaps_found: int,
) -> DiscoveryCollectionResult:
    return DiscoveryCollectionResult(
        sitemap_url=sitemap_url,
        discovered_urls=discovered_urls,
        payload_cache=payload_cache,
        warnings=warnings,
        source_from_sitemap=source_from_sitemap,
        source_from_fallback=source_from_fallback,
        product_sitemaps_found=product_sitemaps_found,
    )


def collect_discovery_urls(
    *,
    base_url: str,
    product_sitemap_re,
    max_products: int,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    deadline_monotonic: float | None = None,
    on_progress: Callable[[], None] | None = None,
    on_detail_progress: Callable[[dict], None] | None = None,
) -> DiscoveryCollectionResult:
    """Collect product URLs from sitemap.xml and API fallbacks."""
    LOGGER.info("shopify discovery started base_url=%s max_products=%s", base_url, max_products)
    sitemap_url = f"{base_url}/sitemap.xml"
    warnings: list[str] = []
    discovered_urls: list[str] = []
    discovered_set: set[str] = set()
    payload_cache: dict[str, dict[str, Any]] = {}

    progress = DiscoveryProgressEmitter(
        max_products=max_products,
        discovered_urls=discovered_urls,
        discovered_set=discovered_set,
        on_progress=on_progress,
        on_detail_progress=on_detail_progress,
    )

    source_from_fallback = False
    source_from_sitemap = False
    product_sitemaps_found = 0

    session = ShopifyHTTPClient.create_session()
    (
        source_from_sitemap,
        sitemap_rate_limited,
        _sitemap_bot_protected,
        stop_after_sitemap,
        product_sitemaps_found,
    ) = collect_from_sitemap(
        base_url=base_url,
        product_sitemap_re=product_sitemap_re,
        max_products=max_products,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        session=session,
        deadline_monotonic=deadline_monotonic,
        progress=progress,
        warnings=warnings,
    )

    if stop_after_sitemap:
        return _build_result(
            sitemap_url=sitemap_url,
            discovered_urls=discovered_urls,
            payload_cache=payload_cache,
            warnings=warnings,
            source_from_sitemap=source_from_sitemap,
            source_from_fallback=source_from_fallback,
            product_sitemaps_found=product_sitemaps_found,
        )

    source_from_fallback, stop_after_fallbacks = collect_from_fallbacks(
        base_url=base_url,
        max_products=max_products,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        session=session,
        deadline_monotonic=deadline_monotonic,
        progress=progress,
        warnings=warnings,
        payload_cache=payload_cache,
        source_from_fallback=source_from_fallback,
        sitemap_rate_limited=sitemap_rate_limited,
    )

    if stop_after_fallbacks:
        return _build_result(
            sitemap_url=sitemap_url,
            discovered_urls=discovered_urls,
            payload_cache=payload_cache,
            warnings=warnings,
            source_from_sitemap=source_from_sitemap,
            source_from_fallback=source_from_fallback,
            product_sitemaps_found=product_sitemaps_found,
        )

    LOGGER.info(
        "shopify discovery finished base_url=%s discovered=%s cached_payloads=%s warnings=%s",
        base_url,
        len(discovered_urls),
        len(payload_cache),
        len(warnings),
    )
    return _build_result(
        sitemap_url=sitemap_url,
        discovered_urls=discovered_urls,
        payload_cache=payload_cache,
        warnings=warnings,
        source_from_sitemap=source_from_sitemap,
        source_from_fallback=source_from_fallback,
        product_sitemaps_found=product_sitemaps_found,
    )
