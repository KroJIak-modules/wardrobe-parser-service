"""URL discovery orchestration for Shopify parser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.parsers.shopify.http_client import ShopifyHTTPClient
from app.parsers.shopify.discovery.api import (
    discover_collections_all_products,
    discover_products_json,
)
from app.parsers.shopify_url_utils import append_discovered_url, normalize_product_url
from app.parsers.xml_parser import ShopifyXMLParser


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


def collect_discovery_urls(
    *,
    base_url: str,
    product_sitemap_re,
    max_products: int,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
) -> DiscoveryCollectionResult:
    """Collect product URLs from sitemap.xml and API fallbacks."""
    sitemap_url = f"{base_url}/sitemap.xml"
    warnings: list[str] = []
    discovered_urls: list[str] = []
    discovered_set: set[str] = set()
    payload_cache: dict[str, dict[str, Any]] = {}

    source_from_sitemap = False
    source_from_fallback = False
    product_sitemaps_found = 0

    http_client = ShopifyHTTPClient()
    session = ShopifyHTTPClient.create_session()

    sitemap_payload, _, _, _, sitemap_error = http_client.request_with_retries(
        url=sitemap_url,
        is_json=False,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        session=session,
    )

    if sitemap_error:
        warnings.append(f"Не удалось прочитать sitemap.xml: {sitemap_error}")
    elif isinstance(sitemap_payload, str):
        sitemap_urls, direct_product_urls = ShopifyXMLParser.parse_sitemap(sitemap_payload)
        product_sitemaps = [url for url in sitemap_urls if product_sitemap_re.search(url)]
        product_sitemaps_found = len(product_sitemaps)

        if product_sitemaps:
            source_from_sitemap = True
            for product_sitemap_url in product_sitemaps:
                if len(discovered_urls) >= max_products:
                    break
                ps_text, _, _, _, ps_error = http_client.request_with_retries(
                    url=product_sitemap_url,
                    is_json=False,
                    timeout_sec=timeout_sec,
                    max_retries=max_retries,
                    retry_backoff_sec=retry_backoff_sec,
                    session=session,
                )
                if ps_error:
                    warnings.append(f"Не удалось прочитать {product_sitemap_url}: {ps_error}")
                    continue
                if not isinstance(ps_text, str):
                    warnings.append(f"Некорректный XML в {product_sitemap_url}")
                    continue
                for raw_url in ShopifyXMLParser.extract_loc_urls(ps_text):
                    normalized = normalize_product_url(raw_url, base_url)
                    if not normalized:
                        continue
                    append_discovered_url(
                        normalized,
                        discovered_urls=discovered_urls,
                        discovered_set=discovered_set,
                        max_products=max_products,
                    )

        for raw_url in direct_product_urls:
            if len(discovered_urls) >= max_products:
                break
            normalized = normalize_product_url(raw_url, base_url)
            if not normalized:
                continue
            append_discovered_url(
                normalized,
                discovered_urls=discovered_urls,
                discovered_set=discovered_set,
                max_products=max_products,
            )
            source_from_sitemap = True

        if not product_sitemaps:
            warnings.append("В sitemap не найден product-sitemap, используем fallback /products.json")

    products_api_urls, products_api_payloads, products_api_warnings = discover_products_json(
        base_url=base_url,
        max_products=max_products,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        session=session,
    )
    warnings.extend(products_api_warnings)
    if products_api_urls:
        source_from_fallback = True
    for url in products_api_urls:
        if len(discovered_urls) >= max_products:
            break
        append_discovered_url(
            url,
            discovered_urls=discovered_urls,
            discovered_set=discovered_set,
            max_products=max_products,
        )
        payload = products_api_payloads.get(url)
        if isinstance(payload, dict):
            payload_cache[url] = payload

    if len(discovered_urls) < max_products:
        collection_urls, collection_payloads, collection_warnings = discover_collections_all_products(
            base_url=base_url,
            max_products=max_products - len(discovered_urls),
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            session=session,
        )
        warnings.extend(collection_warnings)
        if collection_urls:
            source_from_fallback = True
        for url in collection_urls:
            if len(discovered_urls) >= max_products:
                break
            append_discovered_url(
                url,
                discovered_urls=discovered_urls,
                discovered_set=discovered_set,
                max_products=max_products,
            )
            payload = collection_payloads.get(url)
            if isinstance(payload, dict):
                payload_cache[url] = payload

    return DiscoveryCollectionResult(
        sitemap_url=sitemap_url,
        discovered_urls=discovered_urls,
        payload_cache=payload_cache,
        warnings=warnings,
        source_from_sitemap=source_from_sitemap,
        source_from_fallback=source_from_fallback,
        product_sitemaps_found=product_sitemaps_found,
    )
