"""URL discovery orchestration for Shopify parser."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import time
import logging
from typing import Any, Callable

from app.core.config import settings
from app.parsers.shopify.http_client import ShopifyHTTPClient
from app.parsers.shopify.discovery.api import (
    discover_collections_all_products,
    discover_collections_all_html_products,
    discover_products_json,
)
from app.parsers.shopify_url_utils import append_discovered_url, normalize_product_url
from app.parsers.xml_parser import ShopifyXMLParser

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DiscoveryCollectionResult:
    """Collected product URLs and diagnostics from discovery sources."""

    sitemap_url: str
    discovered_urls: list[str]
    payload_cache: dict[str, dict[str, Any]]
    warnings: list[str]
    source_from_sitemap: bool
    source_from_fallback: bool
    product_sitemaps_found: int


@dataclass(slots=True)
class ProductSitemapFetchResult:
    """One fetched product-sitemap payload with warnings."""

    index: int
    raw_urls: list[str]
    warning: str | None = None
    rate_limited: bool = False


def _fetch_product_sitemap(
    *,
    index: int,
    product_sitemap_url: str,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    deadline_monotonic: float | None = None,
) -> ProductSitemapFetchResult:
    """Fetch and parse one product-sitemap file."""
    http_client = ShopifyHTTPClient()
    session = ShopifyHTTPClient.create_session()
    ps_text, _, _, _, ps_error = http_client.request_with_retries(
        url=product_sitemap_url,
        is_json=False,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        session=session,
        deadline_monotonic=deadline_monotonic,
    )
    if ps_error:
        return ProductSitemapFetchResult(
            index=index,
            raw_urls=[],
            warning=f"Не удалось прочитать {product_sitemap_url}: {ps_error}",
            rate_limited=ps_error == "HTTP 429",
        )
    if not isinstance(ps_text, str):
        return ProductSitemapFetchResult(
            index=index,
            raw_urls=[],
            warning=f"Некорректный XML в {product_sitemap_url}",
        )
    return ProductSitemapFetchResult(
        index=index,
        raw_urls=ShopifyXMLParser.extract_loc_urls(ps_text),
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
) -> DiscoveryCollectionResult:
    """Collect product URLs from sitemap.xml and API fallbacks."""
    LOGGER.info("shopify discovery started base_url=%s max_products=%s", base_url, max_products)
    sitemap_url = f"{base_url}/sitemap.xml"
    warnings: list[str] = []
    discovered_urls: list[str] = []
    discovered_set: set[str] = set()
    payload_cache: dict[str, dict[str, Any]] = {}
    appended_since_ping = 0

    def ping_progress() -> None:
        if on_progress:
            on_progress()

    def append_and_ping(url: str) -> None:
        nonlocal appended_since_ping
        append_discovered_url(
            url,
            discovered_urls=discovered_urls,
            discovered_set=discovered_set,
            max_products=max_products,
        )
        appended_since_ping += 1
        if appended_since_ping >= 100:
            appended_since_ping = 0
            ping_progress()

    source_from_sitemap = False
    source_from_fallback = False
    product_sitemaps_found = 0
    sitemap_rate_limited = False
    sitemap_bot_protected = False

    http_client = ShopifyHTTPClient()
    session = ShopifyHTTPClient.create_session()

    sitemap_payload, _, _, _, sitemap_error = http_client.request_with_retries(
        url=sitemap_url,
        is_json=False,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        session=session,
        deadline_monotonic=deadline_monotonic,
    )

    if sitemap_error:
        warnings.append(f"Не удалось прочитать sitemap.xml: {sitemap_error}")
        sitemap_rate_limited = sitemap_error == "HTTP 429"
        sitemap_bot_protected = sitemap_error == "BOT_PROTECTION_429"
        LOGGER.info("shopify discovery sitemap failed base_url=%s error=%s", base_url, sitemap_error)
        if settings.parser_discovery_fail_fast_on_rate_limit and sitemap_bot_protected:
            warnings.append("Discovery остановлен раньше: BOT_PROTECTION_429 на sitemap.xml")
            return DiscoveryCollectionResult(
                sitemap_url=sitemap_url,
                discovered_urls=discovered_urls,
                payload_cache=payload_cache,
                warnings=warnings,
                source_from_sitemap=source_from_sitemap,
                source_from_fallback=source_from_fallback,
                product_sitemaps_found=product_sitemaps_found,
            )
    elif isinstance(sitemap_payload, str):
        sitemap_urls, direct_product_urls = ShopifyXMLParser.parse_sitemap(sitemap_payload)
        product_sitemaps = [url for url in sitemap_urls if product_sitemap_re.search(url)]
        product_sitemaps_found = len(product_sitemaps)
        LOGGER.info(
            "shopify discovery sitemap parsed base_url=%s product_sitemaps=%s direct_product_links=%s",
            base_url,
            product_sitemaps_found,
            len(direct_product_urls),
        )

        if product_sitemaps:
            source_from_sitemap = True
            sitemap_results: list[ProductSitemapFetchResult] = []
            sitemap_workers = max(1, min(settings.parser_discovery_sitemap_workers, len(product_sitemaps)))
            sitemap_workers = ShopifyHTTPClient.get_adaptive_workers(base_url, sitemap_workers)

            if sitemap_workers == 1:
                processed_sitemaps = 0
                no_new_sitemaps_streak = 0
                no_new_sitemaps_limit = 20
                all_rate_limited = True
                for index, product_sitemap_url in enumerate(product_sitemaps):
                    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                        warnings.append("product-sitemap остановлен: SOURCE_TIMEOUT")
                        break
                    sitemap_result = _fetch_product_sitemap(
                        index=index,
                        product_sitemap_url=product_sitemap_url,
                        timeout_sec=timeout_sec,
                        max_retries=max_retries,
                        retry_backoff_sec=retry_backoff_sec,
                        deadline_monotonic=deadline_monotonic,
                    )
                    processed_sitemaps += 1
                    if not sitemap_result.rate_limited:
                        all_rate_limited = False
                    if sitemap_result.warning:
                        warnings.append(sitemap_result.warning)
                        continue

                    added_on_this_sitemap = 0
                    for raw_url in sitemap_result.raw_urls:
                        if len(discovered_urls) >= max_products:
                            break
                        normalized = normalize_product_url(raw_url, base_url)
                        if not normalized:
                            continue
                        before_len = len(discovered_urls)
                        append_and_ping(normalized)
                        if len(discovered_urls) > before_len:
                            added_on_this_sitemap += 1

                    if added_on_this_sitemap == 0:
                        no_new_sitemaps_streak += 1
                    else:
                        no_new_sitemaps_streak = 0

                    if processed_sitemaps % 10 == 0:
                        LOGGER.info(
                            "shopify discovery sitemap progress base_url=%s processed=%s/%s discovered=%s",
                            base_url,
                            processed_sitemaps,
                            len(product_sitemaps),
                            len(discovered_urls),
                        )

                    if len(discovered_urls) >= max_products:
                        break
                    if no_new_sitemaps_streak >= no_new_sitemaps_limit:
                        warnings.append(
                            f"product-sitemap остановлен: {no_new_sitemaps_streak} подряд без новых товаров"
                        )
                        break

                if processed_sitemaps > 0 and all_rate_limited:
                    sitemap_rate_limited = True
            else:
                with ThreadPoolExecutor(max_workers=sitemap_workers) as pool:
                    futures = {
                        pool.submit(
                            _fetch_product_sitemap,
                            index=index,
                            product_sitemap_url=product_sitemap_url,
                            timeout_sec=timeout_sec,
                            max_retries=max_retries,
                            retry_backoff_sec=retry_backoff_sec,
                            deadline_monotonic=deadline_monotonic,
                        ): index
                        for index, product_sitemap_url in enumerate(product_sitemaps)
                        if deadline_monotonic is None or time.monotonic() < deadline_monotonic
                    }
                    by_index: dict[int, ProductSitemapFetchResult] = {}
                    for future in as_completed(futures):
                        result = future.result()
                        by_index[result.index] = result
                    sitemap_results = [by_index[index] for index in sorted(by_index)]

            if sitemap_workers > 1:
                for sitemap_result in sitemap_results:
                    if len(discovered_urls) >= max_products:
                        break
                    if sitemap_result.warning:
                        warnings.append(sitemap_result.warning)
                        continue
                    for raw_url in sitemap_result.raw_urls:
                        normalized = normalize_product_url(raw_url, base_url)
                        if not normalized:
                            continue
                        append_and_ping(normalized)
                if product_sitemaps and all(result.rate_limited for result in sitemap_results):
                    sitemap_rate_limited = True

        for raw_url in direct_product_urls:
            if len(discovered_urls) >= max_products:
                break
            normalized = normalize_product_url(raw_url, base_url)
            if not normalized:
                continue
            append_and_ping(normalized)
            source_from_sitemap = True

        if not product_sitemaps:
            warnings.append("В sitemap не найден product-sitemap, используем fallback /products.json")

    if max_products > 0:
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
            was_known = url in discovered_set
            if not was_known and len(discovered_urls) < max_products:
                append_and_ping(url)
                if url in discovered_set and not was_known:
                    added_from_fallback = True
            payload = products_api_result.payloads.get(url)
            # Keep payload cache enriched even for URLs already discovered from sitemap.
            if isinstance(payload, dict) and url in discovered_set:
                payload_cache[url] = payload
        if added_from_fallback:
            source_from_fallback = True
        if (
            settings.parser_discovery_fail_fast_on_rate_limit
            and not discovered_urls
            and sitemap_rate_limited
            and products_api_result.rate_limited
        ):
            warnings.append("Discovery остановлен раньше: магазин отвечает HTTP 429 на sitemap и products.json")
            return DiscoveryCollectionResult(
                sitemap_url=sitemap_url,
                discovered_urls=discovered_urls,
                payload_cache=payload_cache,
                warnings=warnings,
                source_from_sitemap=source_from_sitemap,
                source_from_fallback=source_from_fallback,
                product_sitemaps_found=product_sitemaps_found,
            )

    if len(discovered_urls) < max_products:
        collections_result = discover_collections_all_products(
            base_url=base_url,
            max_products=max_products - len(discovered_urls),
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
            if len(discovered_urls) >= max_products:
                break
            append_and_ping(url)
            payload = collections_result.payloads.get(url)
            if isinstance(payload, dict):
                payload_cache[url] = payload

    if len(discovered_urls) < max_products:
        html_collections_result = discover_collections_all_html_products(
            base_url=base_url,
            max_products=max_products - len(discovered_urls),
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
            if len(discovered_urls) >= max_products:
                break
            append_and_ping(url)

    LOGGER.info(
        "shopify discovery finished base_url=%s discovered=%s cached_payloads=%s warnings=%s",
        base_url,
        len(discovered_urls),
        len(payload_cache),
        len(warnings),
    )
    return DiscoveryCollectionResult(
        sitemap_url=sitemap_url,
        discovered_urls=discovered_urls,
        payload_cache=payload_cache,
        warnings=warnings,
        source_from_sitemap=source_from_sitemap,
        source_from_fallback=source_from_fallback,
        product_sitemaps_found=product_sitemaps_found,
    )
