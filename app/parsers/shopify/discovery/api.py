"""Discovery helpers for Shopify products JSON endpoints."""

from __future__ import annotations

from typing import Any

import requests

from app.parsers.shopify.http_client import ShopifyHTTPClient
from app.parsers.shopify.discovery.products_json import (
    collect_products_from_payload,
    discover_products_json_page,
    discover_products_json_since_id,
    extract_products_list,
)


def discover_products_json(
    *,
    base_url: str,
    max_products: int,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    session: requests.Session,
) -> tuple[list[str], dict[str, dict[str, Any]], list[str]]:
    urls, payloads, warnings = discover_products_json_since_id(
        base_url=base_url,
        max_products=max_products,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        session=session,
    )
    if urls:
        return urls, payloads, warnings

    page_urls, page_payloads, page_warnings = discover_products_json_page(
        base_url=base_url,
        max_products=max_products,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        session=session,
    )
    warnings.extend(page_warnings)
    return page_urls, page_payloads, warnings


def discover_collections_all_products(
    *,
    base_url: str,
    max_products: int,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    session: requests.Session,
) -> tuple[list[str], dict[str, dict[str, Any]], list[str]]:
    warnings: list[str] = []
    urls: list[str] = []
    url_set: set[str] = set()
    payloads: dict[str, dict[str, Any]] = {}

    http_client = ShopifyHTTPClient()
    page = 1
    safety_limit = 300

    for _ in range(safety_limit):
        if len(urls) >= max_products:
            break
        request_url = f"{base_url}/collections/all/products.json?limit=250&page={page}"
        payload, _, _, _, error = http_client.request_with_retries(
            url=request_url,
            is_json=True,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            session=session,
        )
        if error:
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

        if len(products) < 250:
            break
        page += 1

    return urls, payloads, warnings

