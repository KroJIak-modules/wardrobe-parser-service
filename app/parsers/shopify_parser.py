"""Shopify discovery parser with resilient fallback and diagnostics."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import logging
import re
import threading
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse, urlunparse
import xml.etree.ElementTree as ET

import requests

from app.core.exceptions import ValidationError


LOGGER = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json, text/xml, application/xml, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

_PRODUCT_SITEMAP_RE = re.compile(r"(product-sitemap|sitemap_products)", re.IGNORECASE)


@dataclass(slots=True)
class ShopifyProductPreview:
    """Short preview payload for discovery response."""

    product_url: str
    handle: str
    product_id: str | None
    title: str | None
    vendor: str | None
    price: str | None
    currency: str | None
    payload_source: str


@dataclass(slots=True)
class ShopifyDiscoveryResult:
    """Discovery result used by service layer."""

    base_url: str
    sitemap_url: str
    discovery_mode: str
    product_sitemaps_found: int
    product_urls_found: int
    requested_previews: int
    products_fetch_attempted: int
    products_fetch_succeeded: int
    products_fetch_failed: int
    http_429_count: int
    http_5xx_count: int
    second_pass_attempted: int
    second_pass_recovered: int
    warnings: list[str]
    error_details: list[str]
    previews: list[ShopifyProductPreview]


@dataclass(slots=True)
class _RequestResult:
    payload: Any | None
    status_code: int | None
    error: str | None
    headers: dict[str, str]
    http_429_count: int
    http_5xx_count: int


@dataclass(slots=True)
class _FetchOutcome:
    product_url: str
    preview: ShopifyProductPreview | None
    error: str | None
    http_429_count: int
    http_5xx_count: int


class ShopifyParser:
    """Diagnostics-oriented Shopify parser."""

    _thread_local = threading.local()

    @classmethod
    def discover(
        cls,
        base_url: str,
        *,
        max_products: int,
        sample_products: int,
        timeout_sec: float,
        fetch_all_products: bool,
        response_products_limit: int,
        error_details_limit: int,
        parallel_workers: int,
        max_retries: int,
        retry_backoff_sec: float,
        second_pass_enabled: bool,
        second_pass_timeout_sec: float,
    ) -> ShopifyDiscoveryResult:
        """Run discovery and optionally fetch product previews."""
        resolved_base_url = cls._normalize_base_url(base_url)
        sitemap_url = f"{resolved_base_url}/sitemap.xml"

        warnings: list[str] = []
        discovered_urls: list[str] = []
        discovered_set: set[str] = set()
        payload_cache: dict[str, dict[str, Any]] = {}

        source_from_sitemap = False
        source_from_fallback = False

        with requests.Session() as session:
            session.headers.update(_DEFAULT_HEADERS)

            sitemap_result = cls._request_json_or_text_with_retries(
                session=session,
                url=sitemap_url,
                timeout_sec=timeout_sec,
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff_sec,
                expect_json=False,
            )
            if sitemap_result.error:
                warnings.append(f"Не удалось прочитать sitemap.xml: {sitemap_result.error}")
            else:
                text_payload = sitemap_result.payload
                if isinstance(text_payload, str):
                    product_sitemaps, direct_product_urls = cls._parse_sitemap(text_payload)
                    if product_sitemaps:
                        source_from_sitemap = True
                        for product_sitemap_url in product_sitemaps:
                            if len(discovered_urls) >= max_products:
                                break
                            product_sitemap_result = cls._request_json_or_text_with_retries(
                                session=session,
                                url=product_sitemap_url,
                                timeout_sec=timeout_sec,
                                max_retries=max_retries,
                                retry_backoff_sec=retry_backoff_sec,
                                expect_json=False,
                            )
                            if product_sitemap_result.error:
                                warnings.append(
                                    f"Не удалось прочитать {product_sitemap_url}: {product_sitemap_result.error}"
                                )
                                continue
                            if not isinstance(product_sitemap_result.payload, str):
                                warnings.append(f"Некорректный XML в {product_sitemap_url}")
                                continue
                            for raw_url in cls._extract_loc_urls(product_sitemap_result.payload):
                                normalized = cls._normalize_product_url(raw_url, resolved_base_url)
                                if not normalized:
                                    continue
                                if cls._append_discovered_url(
                                    normalized,
                                    discovered_urls=discovered_urls,
                                    discovered_set=discovered_set,
                                    max_products=max_products,
                                ):
                                    source_from_sitemap = True

                    for raw_url in direct_product_urls:
                        if len(discovered_urls) >= max_products:
                            break
                        normalized = cls._normalize_product_url(raw_url, resolved_base_url)
                        if not normalized:
                            continue
                        if cls._append_discovered_url(
                            normalized,
                            discovered_urls=discovered_urls,
                            discovered_set=discovered_set,
                            max_products=max_products,
                        ):
                            source_from_sitemap = True

                    if not product_sitemaps:
                        warnings.append(
                            "В sitemap не найден product-sitemap, используем fallback /products.json"
                        )

            products_api_urls, products_api_payloads, products_api_warnings = cls._discover_products_json(
                session=session,
                base_url=resolved_base_url,
                max_products=max_products,
                timeout_sec=timeout_sec,
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff_sec,
            )
            warnings.extend(products_api_warnings)
            if products_api_urls:
                source_from_fallback = True
            for url in products_api_urls:
                if len(discovered_urls) >= max_products:
                    break
                if cls._append_discovered_url(
                    url,
                    discovered_urls=discovered_urls,
                    discovered_set=discovered_set,
                    max_products=max_products,
                ):
                    payload = products_api_payloads.get(url)
                    if isinstance(payload, dict):
                        payload_cache[url] = payload

            if len(discovered_urls) < max_products:
                collection_urls, collection_payloads, collection_warnings = cls._discover_collections_all_products(
                    session=session,
                    base_url=resolved_base_url,
                    max_products=max_products - len(discovered_urls),
                    timeout_sec=timeout_sec,
                    max_retries=max_retries,
                    retry_backoff_sec=retry_backoff_sec,
                )
                warnings.extend(collection_warnings)
                if collection_urls:
                    source_from_fallback = True
                for url in collection_urls:
                    if len(discovered_urls) >= max_products:
                        break
                    if cls._append_discovered_url(
                        url,
                        discovered_urls=discovered_urls,
                        discovered_set=discovered_set,
                        max_products=max_products,
                    ):
                        payload = collection_payloads.get(url)
                        if isinstance(payload, dict):
                            payload_cache[url] = payload

        product_sitemaps_found = 0
        if source_from_sitemap:
            product_sitemaps_found = cls._count_product_sitemaps(sitemap_result_payload=sitemap_result.payload)

        discovery_mode = cls._resolve_discovery_mode(
            from_sitemap=source_from_sitemap,
            from_fallback=source_from_fallback,
        )

        if fetch_all_products:
            target_urls = discovered_urls
        else:
            target_urls = discovered_urls[:sample_products]

        fetch_attempted = len(target_urls)
        previews: list[ShopifyProductPreview] = []
        final_errors: list[tuple[str, str]] = []
        http_429_count = 0
        http_5xx_count = 0
        second_pass_attempted = 0
        second_pass_recovered = 0

        if target_urls:
            by_url: dict[str, _FetchOutcome] = {}
            first_pass_failures: list[str] = []

            for outcome in cls._fetch_many_product_previews(
                base_url=resolved_base_url,
                product_urls=target_urls,
                payload_cache=payload_cache,
                timeout_sec=timeout_sec,
                parallel_workers=parallel_workers,
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff_sec,
            ):
                by_url[outcome.product_url] = outcome

            for product_url in target_urls:
                outcome = by_url.get(product_url)
                if not outcome:
                    first_pass_failures.append(product_url)
                    final_errors.append((product_url, "внутренняя ошибка: нет результата воркера"))
                    continue
                http_429_count += outcome.http_429_count
                http_5xx_count += outcome.http_5xx_count
                if outcome.preview:
                    previews.append(outcome.preview)
                else:
                    first_pass_failures.append(product_url)
                    final_errors.append((product_url, outcome.error or "не удалось получить товар"))

            if second_pass_enabled and first_pass_failures:
                second_pass_attempted = len(first_pass_failures)
                second_pass_timeout = max(second_pass_timeout_sec, timeout_sec)

                second_pass_results = cls._fetch_many_product_previews(
                    base_url=resolved_base_url,
                    product_urls=first_pass_failures,
                    payload_cache=payload_cache,
                    timeout_sec=second_pass_timeout,
                    parallel_workers=max(1, min(parallel_workers, 8)),
                    max_retries=max_retries + 1,
                    retry_backoff_sec=max(retry_backoff_sec, 0.5),
                )
                second_pass_by_url = {item.product_url: item for item in second_pass_results}

                refreshed_errors: list[tuple[str, str]] = []
                for product_url, first_error in final_errors:
                    second = second_pass_by_url.get(product_url)
                    if not second:
                        refreshed_errors.append((product_url, first_error))
                        continue

                    http_429_count += second.http_429_count
                    http_5xx_count += second.http_5xx_count

                    if second.preview:
                        previews.append(second.preview)
                        second_pass_recovered += 1
                    else:
                        refreshed_errors.append((product_url, second.error or first_error))

                final_errors = refreshed_errors

        previews = cls._dedupe_and_keep_ordered_previews(target_urls=target_urls, previews=previews)

        if len(previews) > response_products_limit:
            warnings.append(f"Список previews обрезан до response_products_limit={response_products_limit}")
            previews = previews[:response_products_limit]

        if final_errors:
            for product_url, error in final_errors[:20]:
                warnings.append(f"Ошибка чтения карточки {product_url}: {error}")
            if len(final_errors) > 20:
                warnings.append(
                    f"Подробные предупреждения обрезаны: показано 20 из {len(final_errors)} ошибок чтения"
                )
        else:
            if fetch_all_products and fetch_attempted:
                warnings.append("Полный обход: все найденные карточки успешно прочитаны")

        if second_pass_attempted:
            warnings.append(
                f"Второй проход: повторно проверено {second_pass_attempted}, "
                f"восстановлено {second_pass_recovered}"
            )

        products_fetch_succeeded = fetch_attempted - len(final_errors)
        products_fetch_failed = len(final_errors)

        error_details = [f"{url} -> {error}" for url, error in final_errors]
        if not error_details:
            error_details = ["Детальных ошибок не зафиксировано"]
        elif len(error_details) > error_details_limit:
            warnings.append(f"Список error_details обрезан до {error_details_limit}")
            error_details = error_details[:error_details_limit]

        if fetch_all_products and products_fetch_failed:
            warnings.append(
                f"Есть ошибки чтения карточек: {products_fetch_failed} из {fetch_attempted}"
            )

        return ShopifyDiscoveryResult(
            base_url=resolved_base_url,
            sitemap_url=sitemap_url,
            discovery_mode=discovery_mode,
            product_sitemaps_found=product_sitemaps_found,
            product_urls_found=len(discovered_urls),
            requested_previews=fetch_attempted,
            products_fetch_attempted=fetch_attempted,
            products_fetch_succeeded=products_fetch_succeeded,
            products_fetch_failed=products_fetch_failed,
            http_429_count=http_429_count,
            http_5xx_count=http_5xx_count,
            second_pass_attempted=second_pass_attempted,
            second_pass_recovered=second_pass_recovered,
            warnings=warnings,
            error_details=error_details,
            previews=previews,
        )

    @classmethod
    def _fetch_many_product_previews(
        cls,
        *,
        base_url: str,
        product_urls: list[str],
        payload_cache: dict[str, dict[str, Any]],
        timeout_sec: float,
        parallel_workers: int,
        max_retries: int,
        retry_backoff_sec: float,
    ) -> list[_FetchOutcome]:
        if not product_urls:
            return []

        if parallel_workers <= 1 or len(product_urls) <= 1:
            return [
                cls._fetch_one_product_preview(
                    base_url=base_url,
                    product_url=product_url,
                    cached_payload=payload_cache.get(product_url),
                    timeout_sec=timeout_sec,
                    max_retries=max_retries,
                    retry_backoff_sec=retry_backoff_sec,
                )
                for product_url in product_urls
            ]

        results: list[_FetchOutcome] = []
        workers = max(1, min(parallel_workers, len(product_urls)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    cls._fetch_one_product_preview,
                    base_url=base_url,
                    product_url=product_url,
                    cached_payload=payload_cache.get(product_url),
                    timeout_sec=timeout_sec,
                    max_retries=max_retries,
                    retry_backoff_sec=retry_backoff_sec,
                ): product_url
                for product_url in product_urls
            }
            for future in as_completed(futures):
                product_url = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # pragma: no cover - defensive fallback
                    LOGGER.exception("Shopify worker failed for %s", product_url)
                    results.append(
                        _FetchOutcome(
                            product_url=product_url,
                            preview=None,
                            error=f"worker_exception: {exc}",
                            http_429_count=0,
                            http_5xx_count=0,
                        )
                    )
        return results

    @classmethod
    def _fetch_one_product_preview(
        cls,
        *,
        base_url: str,
        product_url: str,
        cached_payload: dict[str, Any] | None,
        timeout_sec: float,
        max_retries: int,
        retry_backoff_sec: float,
    ) -> _FetchOutcome:
        handle = cls._extract_handle(product_url)
        if not handle:
            return _FetchOutcome(
                product_url=product_url,
                preview=None,
                error="не удалось извлечь handle из URL",
                http_429_count=0,
                http_5xx_count=0,
            )

        if isinstance(cached_payload, dict):
            preview = cls._build_preview(product_url, handle, cached_payload, payload_source="products_json")
            return _FetchOutcome(
                product_url=product_url,
                preview=preview,
                error=None,
                http_429_count=0,
                http_5xx_count=0,
            )

        session = cls._thread_session()
        http_429_count = 0
        http_5xx_count = 0
        last_error = "нет данных"

        js_url = f"{base_url}/products/{handle}.js"
        json_url = f"{base_url}/products/{handle}.json"

        for endpoint_url, payload_source in ((js_url, "js"), (json_url, "json")):
            result = cls._request_json_or_text_with_retries(
                session=session,
                url=endpoint_url,
                timeout_sec=timeout_sec,
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff_sec,
                expect_json=True,
            )
            http_429_count += result.http_429_count
            http_5xx_count += result.http_5xx_count

            if result.error:
                last_error = f"ошибка запроса .{payload_source}: {result.error}"
                continue
            payload = result.payload

            if payload_source == "json" and isinstance(payload, dict) and isinstance(payload.get("product"), dict):
                payload = payload["product"]

            if not isinstance(payload, dict):
                last_error = f"некорректный payload .{payload_source}"
                continue

            preview = cls._build_preview(product_url, handle, payload, payload_source=payload_source)
            return _FetchOutcome(
                product_url=product_url,
                preview=preview,
                error=None,
                http_429_count=http_429_count,
                http_5xx_count=http_5xx_count,
            )

        return _FetchOutcome(
            product_url=product_url,
            preview=None,
            error=last_error,
            http_429_count=http_429_count,
            http_5xx_count=http_5xx_count,
        )

    @classmethod
    def _request_json_or_text_with_retries(
        cls,
        *,
        session: requests.Session,
        url: str,
        timeout_sec: float,
        max_retries: int,
        retry_backoff_sec: float,
        expect_json: bool,
    ) -> _RequestResult:
        http_429_count = 0
        http_5xx_count = 0
        last_error: str | None = None
        headers: dict[str, str] = {}
        status_code: int | None = None

        for attempt in range(max_retries + 1):
            try:
                response = session.get(url, timeout=timeout_sec, allow_redirects=True)
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt < max_retries:
                    cls._sleep_backoff(attempt, retry_backoff_sec)
                    continue
                return _RequestResult(
                    payload=None,
                    status_code=None,
                    error=last_error,
                    headers={},
                    http_429_count=http_429_count,
                    http_5xx_count=http_5xx_count,
                )

            headers = dict(response.headers)
            status_code = response.status_code

            if status_code == 429:
                http_429_count += 1
                last_error = "HTTP 429"
                if attempt < max_retries:
                    cls._sleep_backoff(attempt, max(retry_backoff_sec, 0.5))
                    continue
                break
            if 500 <= status_code < 600:
                http_5xx_count += 1
                last_error = f"HTTP {status_code}"
                if attempt < max_retries:
                    cls._sleep_backoff(attempt, retry_backoff_sec)
                    continue
                break
            if status_code >= 400:
                last_error = f"HTTP {status_code}"
                break

            if expect_json:
                try:
                    payload = response.json()
                except ValueError:
                    last_error = "ответ не является JSON"
                    if attempt < max_retries:
                        cls._sleep_backoff(attempt, retry_backoff_sec)
                        continue
                    break
                return _RequestResult(
                    payload=payload,
                    status_code=status_code,
                    error=None,
                    headers=headers,
                    http_429_count=http_429_count,
                    http_5xx_count=http_5xx_count,
                )

            return _RequestResult(
                payload=response.text,
                status_code=status_code,
                error=None,
                headers=headers,
                http_429_count=http_429_count,
                http_5xx_count=http_5xx_count,
            )

        return _RequestResult(
            payload=None,
            status_code=status_code,
            error=last_error or "неизвестная ошибка",
            headers=headers,
            http_429_count=http_429_count,
            http_5xx_count=http_5xx_count,
        )

    @classmethod
    def _discover_products_json(
        cls,
        *,
        session: requests.Session,
        base_url: str,
        max_products: int,
        timeout_sec: float,
        max_retries: int,
        retry_backoff_sec: float,
    ) -> tuple[list[str], dict[str, dict[str, Any]], list[str]]:
        urls, payloads, warnings = cls._discover_products_json_since_id(
            session=session,
            base_url=base_url,
            max_products=max_products,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
        )
        if urls:
            return urls, payloads, warnings

        page_urls, page_payloads, page_warnings = cls._discover_products_json_page(
            session=session,
            base_url=base_url,
            max_products=max_products,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
        )
        warnings.extend(page_warnings)
        return page_urls, page_payloads, warnings

    @classmethod
    def _discover_products_json_since_id(
        cls,
        *,
        session: requests.Session,
        base_url: str,
        max_products: int,
        timeout_sec: float,
        max_retries: int,
        retry_backoff_sec: float,
    ) -> tuple[list[str], dict[str, dict[str, Any]], list[str]]:
        warnings: list[str] = []
        urls: list[str] = []
        url_set: set[str] = set()
        payloads: dict[str, dict[str, Any]] = {}

        since_id = 0
        safety_limit = 2000

        for _ in range(safety_limit):
            if len(urls) >= max_products:
                break
            request_url = f"{base_url}/products.json?limit=250"
            if since_id > 0:
                request_url = f"{request_url}&since_id={since_id}"

            result = cls._request_json_or_text_with_retries(
                session=session,
                url=request_url,
                timeout_sec=timeout_sec,
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff_sec,
                expect_json=True,
            )
            if result.error:
                warnings.append(f"products.json(since_id) недоступен: {result.error}")
                break

            products = cls._extract_products_list(result.payload)
            if not products:
                break

            max_id_on_page = since_id
            added_on_page = 0

            for product in products:
                handle = cls._safe_str(product.get("handle"))
                if not handle:
                    continue
                product_url = cls._normalize_product_url(f"{base_url}/products/{handle}", base_url)
                if not product_url:
                    continue

                if cls._append_discovered_url(
                    product_url,
                    discovered_urls=urls,
                    discovered_set=url_set,
                    max_products=max_products,
                ):
                    payloads[product_url] = product
                    added_on_page += 1

                product_id = cls._safe_int(product.get("id"))
                if product_id and product_id > max_id_on_page:
                    max_id_on_page = product_id

            if len(products) < 250:
                break
            if max_id_on_page <= since_id:
                warnings.append("products.json(since_id) остановлен: курсор не растет")
                break
            if added_on_page == 0:
                warnings.append("products.json(since_id) остановлен: страница без новых товаров")
                break

            since_id = max_id_on_page

        return urls, payloads, warnings

    @classmethod
    def _discover_products_json_page(
        cls,
        *,
        session: requests.Session,
        base_url: str,
        max_products: int,
        timeout_sec: float,
        max_retries: int,
        retry_backoff_sec: float,
    ) -> tuple[list[str], dict[str, dict[str, Any]], list[str]]:
        warnings: list[str] = []
        urls: list[str] = []
        url_set: set[str] = set()
        payloads: dict[str, dict[str, Any]] = {}

        page = 1
        repeated_first_product_counter = 0
        last_first_product_id: int | None = None
        safety_limit = 2000

        for _ in range(safety_limit):
            if len(urls) >= max_products:
                break
            request_url = f"{base_url}/products.json?limit=250&page={page}"
            result = cls._request_json_or_text_with_retries(
                session=session,
                url=request_url,
                timeout_sec=timeout_sec,
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff_sec,
                expect_json=True,
            )
            if result.error:
                warnings.append(f"products.json(page) остановлен на page={page}: {result.error}")
                break

            products = cls._extract_products_list(result.payload)
            if not products:
                break

            first_product_id = cls._safe_int(products[0].get("id"))
            if first_product_id is not None and first_product_id == last_first_product_id:
                repeated_first_product_counter += 1
            else:
                repeated_first_product_counter = 0
            last_first_product_id = first_product_id

            if repeated_first_product_counter >= 2:
                warnings.append("products.json(page) остановлен: магазин повторяет одну и ту же страницу")
                break

            for product in products:
                handle = cls._safe_str(product.get("handle"))
                if not handle:
                    continue
                product_url = cls._normalize_product_url(f"{base_url}/products/{handle}", base_url)
                if not product_url:
                    continue
                if cls._append_discovered_url(
                    product_url,
                    discovered_urls=urls,
                    discovered_set=url_set,
                    max_products=max_products,
                ):
                    payloads[product_url] = product

            if len(products) < 250:
                break
            page += 1

        return urls, payloads, warnings

    @classmethod
    def _discover_collections_all_products(
        cls,
        *,
        session: requests.Session,
        base_url: str,
        max_products: int,
        timeout_sec: float,
        max_retries: int,
        retry_backoff_sec: float,
    ) -> tuple[list[str], dict[str, dict[str, Any]], list[str]]:
        warnings: list[str] = []
        urls: list[str] = []
        url_set: set[str] = set()
        payloads: dict[str, dict[str, Any]] = {}

        page = 1
        safety_limit = 300

        for _ in range(safety_limit):
            if len(urls) >= max_products:
                break
            request_url = f"{base_url}/collections/all/products.json?limit=250&page={page}"
            result = cls._request_json_or_text_with_retries(
                session=session,
                url=request_url,
                timeout_sec=timeout_sec,
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff_sec,
                expect_json=True,
            )
            if result.error:
                if page == 1:
                    warnings.append(f"collections/all/products.json недоступен: {result.error}")
                break

            products = cls._extract_products_list(result.payload)
            if not products:
                break

            for product in products:
                handle = cls._safe_str(product.get("handle"))
                if not handle:
                    continue
                product_url = cls._normalize_product_url(f"{base_url}/products/{handle}", base_url)
                if not product_url:
                    continue
                if cls._append_discovered_url(
                    product_url,
                    discovered_urls=urls,
                    discovered_set=url_set,
                    max_products=max_products,
                ):
                    payloads[product_url] = product

            if len(products) < 250:
                break
            page += 1

        return urls, payloads, warnings

    @classmethod
    def _parse_sitemap(cls, xml_text: str) -> tuple[list[str], list[str]]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return [], []

        root_name = cls._xml_local_name(root.tag)
        loc_urls = cls._extract_loc_urls(xml_text)
        if not loc_urls:
            return [], []

        if root_name == "sitemapindex":
            product_sitemaps = [url for url in loc_urls if cls._is_product_sitemap_url(url)]
            return product_sitemaps, []
        if root_name == "urlset":
            return [], loc_urls

        product_sitemaps = [url for url in loc_urls if cls._is_product_sitemap_url(url)]
        direct_product_urls = [url for url in loc_urls if "/products/" in url.lower()]
        return product_sitemaps, direct_product_urls

    @classmethod
    def _extract_loc_urls(cls, xml_text: str) -> list[str]:
        """Extract top-level <loc> elements from XML sitemap.
        
        Important: Only extracts direct <url><loc> elements, not nested ones like
        <url><image:image><image:loc> to avoid including image URLs.
        """
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        loc_urls: list[str] = []
        
        # Only iterate <url> elements (not all elements)
        for url_elem in root.iter():
            if cls._xml_local_name(url_elem.tag) != "url":
                continue
            
            # Find direct <loc> child of this <url>
            for child in url_elem:
                if cls._xml_local_name(child.tag) != "loc":
                    continue
                if not child.text:
                    continue
                value = child.text.strip()
                if value:
                    loc_urls.append(value)
                break  # Only one <loc> per <url>
        
        return loc_urls

    @classmethod
    def _build_preview(
        cls,
        product_url: str,
        handle: str,
        payload: dict[str, Any],
        *,
        payload_source: str,
    ) -> ShopifyProductPreview:
        product_id = cls._safe_str(payload.get("id"))
        title = cls._safe_str(payload.get("title"))
        vendor = cls._safe_str(payload.get("vendor"))
        price = cls._extract_price(payload)
        currency = cls._extract_currency(payload)
        return ShopifyProductPreview(
            product_url=product_url,
            handle=handle,
            product_id=product_id,
            title=title,
            vendor=vendor,
            price=price,
            currency=currency,
            payload_source=payload_source,
        )

    @classmethod
    def _extract_price(cls, payload: dict[str, Any]) -> str | None:
        variants = payload.get("variants")
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                price = cls._safe_str(variant.get("price"))
                if price is not None:
                    return price
        return cls._safe_str(payload.get("price"))

    @classmethod
    def _extract_currency(cls, payload: dict[str, Any]) -> str | None:
        variants = payload.get("variants")
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                currency = cls._safe_str(variant.get("currency"))
                if currency is not None:
                    return currency
        return cls._safe_str(payload.get("currency"))

    @classmethod
    def _extract_products_list(cls, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        products = payload.get("products")
        if not isinstance(products, list):
            return []
        return [item for item in products if isinstance(item, dict)]

    @classmethod
    def _normalize_base_url(cls, base_url: str) -> str:
        raw = base_url.strip()
        if not raw:
            raise ValidationError("Пустой base_url")
        if "://" not in raw:
            raw = f"https://{raw}"

        parsed = urlparse(raw)
        if not parsed.netloc:
            parsed = urlparse(f"https://{raw}")

        if not parsed.netloc:
            raise ValidationError(f"Некорректный base_url: {base_url}")

        scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
        normalized = urlunparse((scheme, parsed.netloc.lower(), "", "", "", ""))
        return normalized.rstrip("/")

    @classmethod
    def _normalize_product_url(cls, raw_url: str, base_url: str) -> str | None:
        candidate = raw_url.strip()
        if not candidate:
            return None

        absolute = urljoin(f"{base_url}/", candidate)
        parsed = urlparse(absolute)
        handle = cls._extract_handle_from_path(parsed.path)
        if not handle:
            return None

        return f"{base_url}/products/{handle}"

    @classmethod
    def _extract_handle(cls, product_url: str) -> str | None:
        parsed = urlparse(product_url)
        return cls._extract_handle_from_path(parsed.path)

    @classmethod
    def _extract_handle_from_path(cls, path: str) -> str | None:
        segments = [segment for segment in path.split("/") if segment]
        if not segments:
            return None
        for index, segment in enumerate(segments):
            if segment != "products":
                continue
            if index + 1 >= len(segments):
                return None
            handle = unquote(segments[index + 1]).strip()
            if handle.endswith(".js"):
                handle = handle[:-3]
            if handle.endswith(".json"):
                handle = handle[:-5]
            return handle or None
        return None

    @classmethod
    def _resolve_discovery_mode(cls, *, from_sitemap: bool, from_fallback: bool) -> str:
        if from_sitemap and from_fallback:
            return "mixed_discovery"
        if from_sitemap:
            return "sitemap_only"
        if from_fallback:
            return "api_fallback_only"
        return "empty_discovery"

    @classmethod
    def _count_product_sitemaps(cls, *, sitemap_result_payload: Any) -> int:
        if not isinstance(sitemap_result_payload, str):
            return 0
        product_sitemaps, _ = cls._parse_sitemap(sitemap_result_payload)
        return len(product_sitemaps)

    @classmethod
    def _is_product_sitemap_url(cls, url: str) -> bool:
        return bool(_PRODUCT_SITEMAP_RE.search(url))

    @classmethod
    def _append_discovered_url(
        cls,
        product_url: str,
        *,
        discovered_urls: list[str],
        discovered_set: set[str],
        max_products: int,
    ) -> bool:
        if len(discovered_urls) >= max_products:
            return False
        if product_url in discovered_set:
            return False
        discovered_set.add(product_url)
        discovered_urls.append(product_url)
        return True

    @classmethod
    def _dedupe_and_keep_ordered_previews(
        cls,
        *,
        target_urls: list[str],
        previews: list[ShopifyProductPreview],
    ) -> list[ShopifyProductPreview]:
        by_url: dict[str, ShopifyProductPreview] = {}
        for preview in previews:
            by_url[preview.product_url] = preview
        ordered: list[ShopifyProductPreview] = []
        for url in target_urls:
            preview = by_url.get(url)
            if preview:
                ordered.append(preview)
        return ordered

    @classmethod
    def _thread_session(cls) -> requests.Session:
        session = getattr(cls._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(_DEFAULT_HEADERS)
            cls._thread_local.session = session
        return session

    @classmethod
    def _sleep_backoff(cls, attempt: int, backoff: float) -> None:
        delay = max(0.0, backoff) * (2**attempt)
        if delay > 0:
            time.sleep(delay)

    @classmethod
    def _xml_local_name(cls, tag: str) -> str:
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    @classmethod
    def _safe_str(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    @classmethod
    def _safe_int(cls, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _extract_page_info_from_link_header(cls, link_header: str | None) -> str | None:
        if not link_header:
            return None
        parts = [item.strip() for item in link_header.split(",") if item.strip()]
        for part in parts:
            if 'rel="next"' not in part:
                continue
            start = part.find("<")
            end = part.find(">", start + 1)
            if start == -1 or end == -1:
                continue
            next_url = part[start + 1 : end]
            query = parse_qs(urlparse(next_url).query)
            values = query.get("page_info")
            if values:
                token = values[0].strip()
                if token:
                    return token
        return None
