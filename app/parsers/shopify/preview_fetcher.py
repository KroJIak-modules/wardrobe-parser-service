"""Helpers for fetching Shopify product previews in single or parallel mode."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import logging
from threading import local
from typing import Any, Callable

import requests

from app.parsers.shopify.http_client import ShopifyHTTPClient
from app.parsers.shopify_url_utils import extract_handle

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class FetchOutcome:
    """Result for one product preview fetch."""

    product_url: str
    preview: Any | None
    error: str | None
    http_429_count: int
    http_5xx_count: int


def fetch_one_product_preview(
    *,
    base_url: str,
    product_url: str,
    cached_payload: dict[str, Any] | None,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    build_preview: Callable[..., Any],
    store_currency: str | None = None,
    session: requests.Session | None = None,
    deadline_monotonic: float | None = None,
) -> FetchOutcome:
    """Fetch preview for one product URL trying .js then .json endpoints."""
    handle = extract_handle(product_url)
    if not handle:
        return FetchOutcome(
            product_url=product_url,
            preview=None,
            error="не удалось извлечь handle из URL",
            http_429_count=0,
            http_5xx_count=0,
        )

    if isinstance(cached_payload, dict):
        payload = dict(cached_payload)
        if store_currency and not payload.get("currency") and not payload.get("currency_code"):
            payload["currency"] = store_currency
        preview = build_preview(
            product_url,
            handle,
            payload,
            payload_source="products_json",
        )
        return FetchOutcome(
            product_url=product_url,
            preview=preview,
            error=None,
            http_429_count=0,
            http_5xx_count=0,
        )

    http_client = ShopifyHTTPClient()
    http_429_count = 0
    http_5xx_count = 0
    last_error = "нет данных"

    json_url = f"{base_url}/products/{handle}.json"
    js_url = f"{base_url}/products/{handle}.js"

    for endpoint_url, payload_source in ((json_url, "json"), (js_url, "js")):
        payload, _, http_429, http_5xx, error = http_client.request_with_retries(
            url=endpoint_url,
            is_json=True,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            session=session,
            deadline_monotonic=deadline_monotonic,
        )
        http_429_count += http_429
        http_5xx_count += http_5xx

        if error:
            last_error = f"ошибка запроса .{payload_source}: {error}"
            # If store rate-limited this request, do not hit alternate endpoint immediately.
            if "HTTP 429" in error:
                break
            continue

        if payload_source == "json" and isinstance(payload, dict) and isinstance(payload.get("product"), dict):
            payload = payload["product"]

        if not isinstance(payload, dict):
            last_error = f"некорректный payload .{payload_source}"
            continue

        payload = dict(payload)
        if store_currency and not payload.get("currency") and not payload.get("currency_code"):
            payload["currency"] = store_currency

        preview = build_preview(
            product_url,
            handle,
            payload,
            payload_source=payload_source,
        )
        return FetchOutcome(
            product_url=product_url,
            preview=preview,
            error=None,
            http_429_count=http_429_count,
            http_5xx_count=http_5xx_count,
        )

    return FetchOutcome(
        product_url=product_url,
        preview=None,
        error=last_error,
        http_429_count=http_429_count,
        http_5xx_count=http_5xx_count,
    )


def fetch_store_currency(
    *,
    base_url: str,
    timeout_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    session: requests.Session | None = None,
    deadline_monotonic: float | None = None,
) -> str | None:
    """Read Shopify store currency from lightweight public endpoints."""
    http_client = ShopifyHTTPClient()
    for endpoint in ("meta.json", "cart.js"):
        payload, _, _, _, error = http_client.request_with_retries(
            url=f"{base_url}/{endpoint}",
            is_json=True,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            session=session,
            deadline_monotonic=deadline_monotonic,
        )
        if error or not isinstance(payload, dict):
            continue
        raw_currency = payload.get("currency")
        if not isinstance(raw_currency, str):
            continue
        normalized = raw_currency.strip().upper()
        if len(normalized) == 3:
            return normalized
    return None


def fetch_many_product_previews(
    *,
    base_url: str,
    product_urls: list[str],
    payload_cache: dict[str, dict[str, Any]],
    timeout_sec: float,
    parallel_workers: int,
    max_retries: int,
    retry_backoff_sec: float,
    build_preview: Callable[..., Any],
    deadline_monotonic: float | None = None,
    on_outcome: Callable[[FetchOutcome], None] | None = None,
) -> list[FetchOutcome]:
    """Fetch many product previews with optional thread pool concurrency."""
    if not product_urls:
        return []

    if parallel_workers <= 1 or len(product_urls) <= 1:
        session = ShopifyHTTPClient.create_session()
        store_currency = fetch_store_currency(
            base_url=base_url,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            session=session,
            deadline_monotonic=deadline_monotonic,
        )
        outcomes: list[FetchOutcome] = []
        for product_url in product_urls:
            outcome = fetch_one_product_preview(
                base_url=base_url,
                product_url=product_url,
                cached_payload=payload_cache.get(product_url),
                timeout_sec=timeout_sec,
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff_sec,
                build_preview=build_preview,
                store_currency=store_currency,
                session=session,
                deadline_monotonic=deadline_monotonic,
            )
            outcomes.append(outcome)
            if on_outcome:
                on_outcome(outcome)
        return outcomes

    results: list[FetchOutcome] = []
    workers = max(1, min(parallel_workers, len(product_urls)))
    workers = ShopifyHTTPClient.get_adaptive_workers(base_url, workers)
    thread_state = local()
    main_session = ShopifyHTTPClient.create_session()
    store_currency = fetch_store_currency(
        base_url=base_url,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
        session=main_session,
        deadline_monotonic=deadline_monotonic,
    )

    def fetch_with_thread_session(product_url: str) -> FetchOutcome:
        session = getattr(thread_state, "session", None)
        if session is None:
            session = ShopifyHTTPClient.create_session()
            thread_state.session = session
        return fetch_one_product_preview(
            base_url=base_url,
            product_url=product_url,
            cached_payload=payload_cache.get(product_url),
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            build_preview=build_preview,
            store_currency=store_currency,
            session=session,
            deadline_monotonic=deadline_monotonic,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                fetch_with_thread_session,
                product_url,
            ): product_url
            for product_url in product_urls
        }
        for future in as_completed(futures):
            product_url = futures[future]
            try:
                outcome = future.result()
                results.append(outcome)
                if on_outcome:
                    on_outcome(outcome)
            except Exception as exc:  # pragma: no cover
                LOGGER.exception("Shopify worker failed for %s", product_url)
                outcome = FetchOutcome(
                    product_url=product_url,
                    preview=None,
                    error=f"worker_exception: {exc}",
                    http_429_count=0,
                    http_5xx_count=0,
                )
                results.append(outcome)
                if on_outcome:
                    on_outcome(outcome)
    return results
