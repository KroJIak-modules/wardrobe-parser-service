"""Sitemap-based discovery step."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from typing import Pattern

from app.core.config import settings
from app.parsers.shopify.http_client import ShopifyHTTPClient
from app.parsers.shopify.discovery.progress import DiscoveryProgressEmitter, deadline_reached
from app.parsers.shopify.discovery.models import ProductSitemapFetchResult
from app.parsers.shopify_url_utils import normalize_product_url
from app.parsers.xml_parser import ShopifyXMLParser

LOGGER = logging.getLogger(__name__)


def fetch_product_sitemap(
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


def collect_from_sitemap(
    *,
    base_url: str,
    product_sitemap_re: Pattern[str],
    max_products: int,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    session,
    deadline_monotonic: float | None,
    progress: DiscoveryProgressEmitter,
    warnings: list[str],
) -> tuple[bool, bool, bool, bool, int]:
    """
    Collect URLs from sitemap.xml (+ product sitemaps).

    Returns:
    - source_from_sitemap
    - sitemap_rate_limited
    - sitemap_bot_protected
    - stop_early
    - product_sitemaps_found
    """
    source_from_sitemap = False
    sitemap_rate_limited = False
    sitemap_bot_protected = False
    stop_early = False
    product_sitemaps_found = 0

    sitemap_url = f"{base_url}/sitemap.xml"
    http_client = ShopifyHTTPClient()
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
            stop_early = True
        return source_from_sitemap, sitemap_rate_limited, sitemap_bot_protected, stop_early, product_sitemaps_found

    if not isinstance(sitemap_payload, str):
        return source_from_sitemap, sitemap_rate_limited, sitemap_bot_protected, stop_early, product_sitemaps_found

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
        sitemap_workers = max(1, min(settings.parser_discovery_sitemap_workers, len(product_sitemaps)))
        sitemap_workers = ShopifyHTTPClient.get_adaptive_workers(base_url, sitemap_workers)

        if sitemap_workers == 1:
            processed_sitemaps = 0
            no_new_sitemaps_streak = 0
            no_new_sitemaps_limit = 20
            all_rate_limited = True
            for index, product_sitemap_url in enumerate(product_sitemaps):
                progress.ping()
                if deadline_reached(deadline_monotonic):
                    warnings.append("product-sitemap остановлен: SOURCE_TIMEOUT")
                    break
                sitemap_result = fetch_product_sitemap(
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
                    if len(progress.discovered_urls) >= max_products:
                        break
                    normalized = normalize_product_url(raw_url, base_url)
                    if not normalized:
                        continue
                    if progress.append_url(normalized):
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
                        len(progress.discovered_urls),
                    )

                if len(progress.discovered_urls) >= max_products:
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
                        fetch_product_sitemap,
                        index=index,
                        product_sitemap_url=product_sitemap_url,
                        timeout_sec=timeout_sec,
                        max_retries=max_retries,
                        retry_backoff_sec=retry_backoff_sec,
                        deadline_monotonic=deadline_monotonic,
                    ): index
                    for index, product_sitemap_url in enumerate(product_sitemaps)
                    if not deadline_reached(deadline_monotonic)
                }
                by_index: dict[int, ProductSitemapFetchResult] = {}
                for future in as_completed(futures):
                    result = future.result()
                    by_index[result.index] = result
                sitemap_results = [by_index[index] for index in sorted(by_index)]

            for sitemap_result in sitemap_results:
                if len(progress.discovered_urls) >= max_products:
                    break
                if sitemap_result.warning:
                    warnings.append(sitemap_result.warning)
                    continue
                for raw_url in sitemap_result.raw_urls:
                    normalized = normalize_product_url(raw_url, base_url)
                    if not normalized:
                        continue
                    progress.append_url(normalized)
            if product_sitemaps and all(result.rate_limited for result in sitemap_results):
                sitemap_rate_limited = True

    for raw_url in direct_product_urls:
        if len(progress.discovered_urls) >= max_products:
            break
        normalized = normalize_product_url(raw_url, base_url)
        if not normalized:
            continue
        progress.append_url(normalized)
        source_from_sitemap = True

    if not product_sitemaps:
        warnings.append("В sitemap не найден product-sitemap, используем fallback /products.json")

    return source_from_sitemap, sitemap_rate_limited, sitemap_bot_protected, stop_early, product_sitemaps_found
