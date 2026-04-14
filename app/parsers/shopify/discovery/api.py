"""Discovery helpers for Shopify products JSON endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re
import time
from typing import Any

import requests

from app.core.config import settings
from app.parsers.shopify.http_client import ShopifyHTTPClient
from app.parsers.shopify_url_utils import normalize_product_url
from app.parsers.shopify.discovery.products_json import (
    collect_products_from_payload,
    discover_products_json_page,
    discover_products_json_since_id,
    extract_products_list,
)


_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


@dataclass(slots=True)
class DiscoveryEndpointResult:
    """Result of one discovery endpoint traversal."""

    urls: list[str]
    payloads: dict[str, dict[str, Any]]
    warnings: list[str]
    rate_limited: bool = False


def discover_products_json(
    *,
    base_url: str,
    max_products: int,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    session: requests.Session,
    deadline_monotonic: float | None = None,
) -> DiscoveryEndpointResult:
    urls, payloads, warnings, since_id_rate_limited = discover_products_json_since_id(
        base_url=base_url,
        max_products=max_products,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        session=session,
        deadline_monotonic=deadline_monotonic,
    )
    if urls:
        return DiscoveryEndpointResult(
            urls=urls,
            payloads=payloads,
            warnings=warnings,
            rate_limited=False,
        )

    page_urls, page_payloads, page_warnings, page_rate_limited = discover_products_json_page(
        base_url=base_url,
        max_products=max_products,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        session=session,
        deadline_monotonic=deadline_monotonic,
    )
    warnings.extend(page_warnings)
    return DiscoveryEndpointResult(
        urls=page_urls,
        payloads=page_payloads,
        warnings=warnings,
        rate_limited=since_id_rate_limited and page_rate_limited and not page_urls,
    )


def discover_collections_all_products(
    *,
    base_url: str,
    max_products: int,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    session: requests.Session,
    deadline_monotonic: float | None = None,
) -> DiscoveryEndpointResult:
    warnings: list[str] = []
    urls: list[str] = []
    url_set: set[str] = set()
    payloads: dict[str, dict[str, Any]] = {}
    rate_limited = False

    http_client = ShopifyHTTPClient()
    page = 1
    safety_limit = settings.parser_discovery_collections_safety_limit
    page_size = settings.parser_shopify_page_size

    for _ in range(safety_limit):
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            warnings.append("collections/all/products.json остановлен: SOURCE_TIMEOUT")
            break
        if len(urls) >= max_products:
            break
        request_url = f"{base_url}/collections/all/products.json?limit={page_size}&page={page}"
        payload, _, _, _, error = http_client.request_with_retries(
            url=request_url,
            is_json=True,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            session=session,
            deadline_monotonic=deadline_monotonic,
        )
        if error:
            if error == "HTTP 429":
                rate_limited = True
            if page == 1:
                warnings.append(f"collections/all/products.json недоступен: {error}")
            break

        products = extract_products_list(payload)
        if not products:
            break

        collect_products_from_payload(
            base_url=base_url,
            products=products,
            max_products=max_products,
            discovered_urls=urls,
            discovered_set=url_set,
            payloads=payloads,
        )

        if len(products) < page_size:
            break
        page += 1

    return DiscoveryEndpointResult(
        urls=urls,
        payloads=payloads,
        warnings=warnings,
        rate_limited=rate_limited and not urls,
    )


def _extract_product_links_from_html(*, html_text: str, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for raw_href in _HREF_RE.findall(html_text or ""):
        normalized = normalize_product_url(unescape(raw_href), base_url)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)
    return urls


def discover_collections_all_html_products(
    *,
    base_url: str,
    max_products: int,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    session: requests.Session,
    deadline_monotonic: float | None = None,
) -> DiscoveryEndpointResult:
    """Discover products by parsing /collections/all HTML pagination as anti-bot fallback."""
    warnings: list[str] = []
    urls: list[str] = []
    url_set: set[str] = set()
    http_client = ShopifyHTTPClient()

    page = 1
    safety_limit = min(settings.parser_discovery_collections_safety_limit, 120)
    empty_pages_streak = 0

    while page <= safety_limit and len(urls) < max_products:
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            warnings.append("collections/all(html) остановлен: SOURCE_TIMEOUT")
            break

        request_url = f"{base_url}/collections/all?page={page}"
        payload, _, _, _, error = http_client.request_with_retries(
            url=request_url,
            is_json=False,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            session=session,
            deadline_monotonic=deadline_monotonic,
        )
        if error:
            if page == 1:
                warnings.append(f"collections/all(html) недоступен: {error}")
            break

        if not isinstance(payload, str) or not payload.strip():
            empty_pages_streak += 1
            if empty_pages_streak >= 2:
                break
            page += 1
            continue

        links = _extract_product_links_from_html(html_text=payload, base_url=base_url)
        page_added = 0
        for link in links:
            if append_discovered_url(
                link,
                discovered_urls=urls,
                discovered_set=url_set,
                max_products=max_products,
            ):
                page_added += 1

        if page_added == 0:
            empty_pages_streak += 1
            if empty_pages_streak >= 2:
                break
        else:
            empty_pages_streak = 0

        page += 1

    if urls:
        warnings.append(f"collections/all(html) fallback used: discovered {len(urls)} urls")

    return DiscoveryEndpointResult(
        urls=urls,
        payloads={},
        warnings=warnings,
        rate_limited=False,
    )
