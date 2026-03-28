"""Shopify discovery parser with resilient fallback and diagnostics."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import logging
import re
from typing import Any
from urllib.parse import urlparse

from app.core.exceptions import ValidationError
from app.parsers.http_client import ShopifyHTTPClient
from app.parsers.xml_parser import ShopifyXMLParser
from app.parsers.product_extractor import ShopifyProductExtractor
from app.parsers.shopify_discovery_api import discover_collections_all_products, discover_products_json
from app.parsers.shopify_url_utils import (
    append_discovered_url,
    dedupe_and_keep_ordered_previews,
    extract_handle,
    normalize_base_url,
    normalize_product_url,
)


LOGGER = logging.getLogger(__name__)

_PRODUCT_SITEMAP_RE = re.compile(r"(product-sitemap|sitemap_products)", re.IGNORECASE)


@dataclass(slots=True)
class ShopifyProductPreview:
    """Short preview payload for discovery response."""

    product_url: str
    handle: str
    product_id: str | None
    title: str | None
    vendor: str | None
    product_type: str | None
    price: str | None
    currency: str | None
    image_urls: list[str]
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
class _FetchOutcome:
    product_url: str
    preview: ShopifyProductPreview | None
    error: str | None
    http_429_count: int
    http_5xx_count: int


class ShopifyParser:
    """Diagnostics-oriented Shopify parser with extracted utilities."""

    @classmethod
    def preview_product_url(
        cls,
        product_url: str,
        *,
        timeout_sec: float,
        max_retries: int,
        retry_backoff_sec: float,
    ) -> ShopifyProductPreview:
        """Fetch one product preview by direct product URL."""
        parsed = urlparse(product_url.strip())
        if not parsed.scheme or not parsed.netloc:
            raise ValidationError("Некорректный URL товара")

        base_url = normalize_base_url(f"{parsed.scheme}://{parsed.netloc}")
        normalized_product_url = normalize_product_url(product_url, base_url)
        if not normalized_product_url:
            raise ValidationError("URL не похож на Shopify product URL")

        outcome = cls._fetch_one_product_preview(
            base_url=base_url,
            product_url=normalized_product_url,
            cached_payload=None,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
        )
        if not outcome.preview:
            raise ValidationError(outcome.error or "Не удалось получить preview товара")
        return outcome.preview

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
        resolved_base_url = normalize_base_url(base_url)
        sitemap_url = f"{resolved_base_url}/sitemap.xml"

        warnings: list[str] = []
        discovered_urls: list[str] = []
        discovered_set: set[str] = set()
        payload_cache: dict[str, dict[str, Any]] = {}

        source_from_sitemap = False
        source_from_fallback = False
        sitemap_text: str | None = None

        http_client = ShopifyHTTPClient()
        session = ShopifyHTTPClient.create_session()

        # Fetch main sitemap.xml
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
            sitemap_text = sitemap_payload
            product_sitemaps, direct_product_urls = cls._parse_sitemap(sitemap_text)
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
                        normalized = normalize_product_url(raw_url, resolved_base_url)
                        if not normalized:
                            continue
                        append_discovered_url(
                            normalized,
                            discovered_urls=discovered_urls,
                            discovered_set=discovered_set,
                            max_products=max_products,
                        )
                        source_from_sitemap = True

            for raw_url in direct_product_urls:
                if len(discovered_urls) >= max_products:
                    break
                normalized = normalize_product_url(raw_url, resolved_base_url)
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
                warnings.append(
                    "В sitemap не найден product-sitemap, используем fallback /products.json"
                )

        # Try /products.json API
        products_api_urls, products_api_payloads, products_api_warnings = discover_products_json(
            base_url=resolved_base_url,
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

        # Try /collections/all/products.json
        if len(discovered_urls) < max_products:
            collection_urls, collection_payloads, collection_warnings = discover_collections_all_products(
                base_url=resolved_base_url,
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

        # Count product sitemaps found
        product_sitemaps_found = 0
        if source_from_sitemap and sitemap_text:
            product_sitemaps, _ = cls._parse_sitemap(sitemap_text)
            product_sitemaps_found = len(product_sitemaps)

        discovery_mode = cls._resolve_discovery_mode(
            from_sitemap=source_from_sitemap,
            from_fallback=source_from_fallback,
        )

        # Select which URLs to preview
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

            # Second pass for failures
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

        previews = dedupe_and_keep_ordered_previews(target_urls=target_urls, previews=previews)

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
                except Exception as exc:  # pragma: no cover
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
        handle = extract_handle(product_url)
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

        http_client = ShopifyHTTPClient()
        http_429_count = 0
        http_5xx_count = 0
        last_error = "нет данных"

        js_url = f"{base_url}/products/{handle}.js"
        json_url = f"{base_url}/products/{handle}.json"

        for endpoint_url, payload_source in ((js_url, "js"), (json_url, "json")):
            payload, _, http_429, http_5xx, error = http_client.request_with_retries(
                url=endpoint_url,
                is_json=True,
                timeout_sec=timeout_sec,
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff_sec,
            )
            http_429_count += http_429
            http_5xx_count += http_5xx

            if error:
                last_error = f"ошибка запроса .{payload_source}: {error}"
                continue

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
    def _parse_sitemap(cls, xml_text: str) -> tuple[list[str], list[str]]:
        """Parse main sitemap.xml and keep only product sitemap URLs."""
        sitemap_urls, direct_product_urls = ShopifyXMLParser.parse_sitemap(xml_text)
        product_sitemap_urls = [url for url in sitemap_urls if _PRODUCT_SITEMAP_RE.search(url)]
        return product_sitemap_urls, direct_product_urls

    @classmethod
    def _build_preview(
        cls,
        product_url: str,
        handle: str,
        payload: dict[str, Any],
        *,
        payload_source: str,
    ) -> ShopifyProductPreview:
        """Build preview from payload, delegate extraction to ShopifyProductExtractor."""
        product_id = ShopifyProductExtractor._safe_str(payload.get("id"))
        title = ShopifyProductExtractor._safe_str(payload.get("title"))
        vendor = ShopifyProductExtractor._safe_str(payload.get("vendor"))
        product_type = ShopifyProductExtractor._safe_str(payload.get("product_type"))
        price = ShopifyProductExtractor.extract_price(payload)
        currency = ShopifyProductExtractor.extract_currency(payload)
        image_urls = ShopifyProductExtractor.extract_image_urls(payload)
        return ShopifyProductPreview(
            product_url=product_url,
            handle=handle,
            product_id=product_id,
            title=title,
            vendor=vendor,
            product_type=product_type,
            price=price,
            currency=currency,
            image_urls=image_urls,
            payload_source=payload_source,
        )

    @classmethod
    def _resolve_discovery_mode(cls, *, from_sitemap: bool, from_fallback: bool) -> str:
        if from_sitemap and from_fallback:
            return "mixed_discovery"
        if from_sitemap:
            return "sitemap_only"
        if from_fallback:
            return "api_fallback_only"
        return "empty_discovery"

