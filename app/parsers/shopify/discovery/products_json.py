"""Shared pagination helpers for Shopify products.json discovery."""

from __future__ import annotations

import time
from typing import Any

import requests

from app.core.config import settings
from app.parsers.shopify.http_client import ShopifyHTTPClient
from app.parsers.product_extractor import ShopifyProductExtractor
from app.parsers.shopify_url_utils import append_discovered_url, normalize_product_url, safe_int


def discover_products_json_since_id(
    *,
    base_url: str,
    max_products: int,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    session: requests.Session,
    deadline_monotonic: float | None = None,
) -> tuple[list[str], dict[str, dict[str, Any]], list[str], bool]:
    warnings: list[str] = []
    urls: list[str] = []
    url_set: set[str] = set()
    payloads: dict[str, dict[str, Any]] = {}
    rate_limited = False

    http_client = ShopifyHTTPClient()
    since_id = 0
    safety_limit = settings.parser_discovery_safety_limit
    page_size = settings.parser_shopify_page_size

    for _ in range(safety_limit):
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            warnings.append("products.json(since_id) остановлен: SOURCE_TIMEOUT")
            break
        if len(urls) >= max_products:
            break
        request_url = f"{base_url}/products.json?limit={page_size}"
        if since_id > 0:
            request_url = f"{request_url}&since_id={since_id}"

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
            if error in {"HTTP 429", "BOT_PROTECTION_429"}:
                rate_limited = True
            warnings.append(f"products.json(since_id) недоступен: {error}")
            break

        products = extract_products_list(payload)
        if not products:
            break

        max_id_on_page = since_id
        added_on_page = collect_products_from_payload(
            base_url=base_url,
            products=products,
            max_products=max_products,
            discovered_urls=urls,
            discovered_set=url_set,
            payloads=payloads,
        )
        max_id_on_page = max(max_id_on_page, max_product_id(products))

        if len(products) < page_size:
            break
        if max_id_on_page <= since_id:
            warnings.append("products.json(since_id) остановлен: курсор не растет")
            break
        if added_on_page == 0:
            warnings.append("products.json(since_id) остановлен: страница без новых товаров")
            break

        since_id = max_id_on_page

    return urls, payloads, warnings, rate_limited


def discover_products_json_page(
    *,
    base_url: str,
    max_products: int,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    session: requests.Session,
    deadline_monotonic: float | None = None,
) -> tuple[list[str], dict[str, dict[str, Any]], list[str], bool]:
    warnings: list[str] = []
    urls: list[str] = []
    url_set: set[str] = set()
    payloads: dict[str, dict[str, Any]] = {}
    rate_limited = False

    http_client = ShopifyHTTPClient()
    page = 1
    repeated_first_product_counter = 0
    last_first_product_id: int | None = None
    safety_limit = settings.parser_discovery_safety_limit
    page_size = settings.parser_shopify_page_size

    for _ in range(safety_limit):
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            warnings.append("products.json(page) остановлен: SOURCE_TIMEOUT")
            break
        if len(urls) >= max_products:
            break
        request_url = f"{base_url}/products.json?limit={page_size}&page={page}"
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
            if error in {"HTTP 429", "BOT_PROTECTION_429"}:
                rate_limited = True
            warnings.append(f"products.json(page) остановлен на page={page}: {error}")
            break

        products = extract_products_list(payload)
        if not products:
            break

        first_product_id = safe_int(products[0].get("id"))
        if first_product_id is not None and first_product_id == last_first_product_id:
            repeated_first_product_counter += 1
        else:
            repeated_first_product_counter = 0
        last_first_product_id = first_product_id

        if repeated_first_product_counter >= 2:
            warnings.append("products.json(page) остановлен: магазин повторяет одну и ту же страницу")
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

    return urls, payloads, warnings, rate_limited


def extract_products_list(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    products = payload.get("products")
    if not isinstance(products, list):
        return []
    return [item for item in products if isinstance(item, dict)]


def collect_products_from_payload(
    *,
    base_url: str,
    products: list[dict[str, Any]],
    max_products: int,
    discovered_urls: list[str],
    discovered_set: set[str],
    payloads: dict[str, dict[str, Any]],
) -> int:
    added = 0
    for product in products:
        handle = ShopifyProductExtractor._safe_str(product.get("handle"))
        if not handle:
            continue
        product_url = normalize_product_url(f"{base_url}/products/{handle}", base_url)
        if not product_url:
            continue
        if append_discovered_url(
            product_url,
            discovered_urls=discovered_urls,
            discovered_set=discovered_set,
            max_products=max_products,
        ):
            payloads[product_url] = product
            added += 1
    return added


def max_product_id(products: list[dict[str, Any]]) -> int:
    max_id = 0
    for product in products:
        product_id = safe_int(product.get("id"))
        if product_id and product_id > max_id:
            max_id = product_id
    return max_id
