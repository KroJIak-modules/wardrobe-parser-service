"""Shopify discovery and product preview parser."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from time import sleep
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse
from xml.etree import ElementTree

import httpx

from app.core.exceptions import ValidationError


DEFAULT_USER_AGENT = "WardrobeShopifyParser/1.0 (+https://wardrobe.local)"
PRODUCT_PATH_RE = re.compile(r"^/products/([^/?#]+)$")
MAX_WARNING_ITEMS = 500
RETRIABLE_STATUS_CODES = {408, 409, 425, 429}


@dataclass
class ShopifyProductPreview:
    """Product preview payload returned by discovery flow."""

    product_url: str
    handle: str
    product_id: str | None
    title: str | None
    vendor: str | None
    price: str | None
    currency: str | None
    payload_source: str


@dataclass
class ShopifyDiscoveryResult:
    """Discovery summary with preview items and warnings."""

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


@dataclass
class ProductFetchResult:
    """Technical result of one product fetch attempt."""

    product_url: str
    preview: ShopifyProductPreview | None
    error_detail: str | None
    warnings: list[str]
    http_429_count: int
    http_5xx_count: int


@dataclass
class BatchFetchResult:
    """Batch fetch result for a set of product URLs."""

    previews_by_url: dict[str, ShopifyProductPreview]
    errors_by_url: dict[str, str]
    warnings: list[str]
    http_429_count: int
    http_5xx_count: int


class ShopifyParser:
    """Shopify parser utilities for discovery and preview."""

    @staticmethod
    def normalize_base_url(base_url: str) -> str:
        """Normalize raw source URL to scheme + host format."""
        normalized = base_url.strip()
        if not normalized:
            raise ValidationError("base_url не может быть пустым")

        if "://" not in normalized:
            normalized = f"https://{normalized}"

        parsed = urlparse(normalized)
        if not parsed.netloc:
            raise ValidationError("base_url должен содержать домен, например https://example.com")

        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    @staticmethod
    def discover(
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
        """Discover product URLs for Shopify source and load product previews."""
        warnings: list[str] = []

        normalized_base_url = ShopifyParser.normalize_base_url(base_url)
        sitemap_url = f"{normalized_base_url}/sitemap.xml"

        discovery_flags: list[str] = []
        product_sitemap_urls: list[str] = []
        product_urls: list[str] = []

        headers = {"User-Agent": DEFAULT_USER_AGENT}
        with httpx.Client(timeout=timeout_sec, follow_redirects=True, headers=headers) as client:
            sitemap_text = ShopifyParser._safe_get_text(
                client=client,
                url=sitemap_url,
                warnings=warnings,
                error_label="Ошибка получения sitemap.xml",
            )

            if sitemap_text:
                product_sitemap_urls = ShopifyParser._extract_product_sitemap_urls(sitemap_text)
                product_sitemap_urls = ShopifyParser._dedupe_and_limit(product_sitemap_urls, max_items=max_products)

            if product_sitemap_urls:
                discovery_flags.append("sitemap")
                for product_sitemap_url in product_sitemap_urls:
                    product_sitemap_text = ShopifyParser._safe_get_text(
                        client=client,
                        url=product_sitemap_url,
                        warnings=warnings,
                        error_label=f"Ошибка получения {product_sitemap_url}",
                    )
                    if not product_sitemap_text:
                        continue
                    product_urls.extend(ShopifyParser._extract_product_urls(product_sitemap_text))
            else:
                warnings.append("В sitemap не найден product-sitemap, используем fallback /products.json")

            product_urls = ShopifyParser._prepare_product_urls(
                product_urls,
                base_url=normalized_base_url,
                max_products=max_products,
            )

            if not product_urls:
                products_api_urls = ShopifyParser._discover_product_urls_by_products_api(
                    client=client,
                    base_url=normalized_base_url,
                    max_products=max_products,
                    warnings=warnings,
                )
                if products_api_urls:
                    discovery_flags.append("products_api")
                product_urls.extend(products_api_urls)

            product_urls = ShopifyParser._prepare_product_urls(
                product_urls,
                base_url=normalized_base_url,
                max_products=max_products,
            )

            if not product_urls:
                collections_urls = ShopifyParser._discover_product_urls_by_collections_api(
                    client=client,
                    base_url=normalized_base_url,
                    max_products=max_products,
                    warnings=warnings,
                )
                if collections_urls:
                    discovery_flags.append("collections_api")
                product_urls.extend(collections_urls)

            product_urls = ShopifyParser._prepare_product_urls(
                product_urls,
                base_url=normalized_base_url,
                max_products=max_products,
            )

            if not product_urls:
                raise ValidationError(
                    "Не удалось найти товары Shopify через sitemap, /products.json или "
                    "/collections/all/products.json. Проверьте домен и доступность сайта."
                )

            fetch_targets = product_urls if fetch_all_products else product_urls[:sample_products]
            requested_previews = len(fetch_targets)

            first_batch = ShopifyParser._fetch_products_batch(
                client=client,
                product_urls=fetch_targets,
                base_url=normalized_base_url,
                parallel_workers=parallel_workers,
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff_sec,
            )

        previews_by_url = dict(first_batch.previews_by_url)
        errors_by_url = dict(first_batch.errors_by_url)
        http_429_count = first_batch.http_429_count
        http_5xx_count = first_batch.http_5xx_count
        warnings.extend(first_batch.warnings)

        second_pass_attempted = 0
        second_pass_recovered = 0

        if second_pass_enabled and errors_by_url:
            failed_urls = list(errors_by_url.keys())
            second_pass_attempted = len(failed_urls)
            reduced_workers = max(1, min(parallel_workers, 4))

            with httpx.Client(timeout=second_pass_timeout_sec, follow_redirects=True, headers=headers) as second_client:
                second_batch = ShopifyParser._fetch_products_batch(
                    client=second_client,
                    product_urls=failed_urls,
                    base_url=normalized_base_url,
                    parallel_workers=reduced_workers,
                    max_retries=max_retries + 1,
                    retry_backoff_sec=retry_backoff_sec,
                )

            warnings.extend(second_batch.warnings)
            http_429_count += second_batch.http_429_count
            http_5xx_count += second_batch.http_5xx_count

            for url, preview in second_batch.previews_by_url.items():
                previews_by_url[url] = preview
                if url in errors_by_url:
                    second_pass_recovered += 1
                    errors_by_url.pop(url, None)

            for url, detail in second_batch.errors_by_url.items():
                errors_by_url[url] = detail

            if second_pass_recovered > 0:
                warnings.append(f"Второй проход восстановил товаров: {second_pass_recovered}")

        products_fetch_attempted = len(fetch_targets)
        products_fetch_failed = len(errors_by_url)
        products_fetch_succeeded = products_fetch_attempted - products_fetch_failed

        ordered_previews: list[ShopifyProductPreview] = []
        for product_url in fetch_targets:
            preview = previews_by_url.get(product_url)
            if preview is None:
                continue
            ordered_previews.append(preview)
            if len(ordered_previews) >= response_products_limit:
                break

        if fetch_all_products and len(fetch_targets) > response_products_limit:
            warnings.append(f"Список previews обрезан до response_products_limit={response_products_limit}")

        if products_fetch_failed > 0:
            warnings.append(
                f"Есть ошибки чтения карточек: {products_fetch_failed} из {products_fetch_attempted}"
            )

        if http_429_count > 0:
            warnings.append(f"Источник вернул HTTP 429: {http_429_count} раз")

        if http_5xx_count > 0:
            warnings.append(f"Источник вернул HTTP 5xx: {http_5xx_count} раз")

        if fetch_all_products and products_fetch_failed == 0:
            warnings.append("Полный обход: все найденные карточки успешно прочитаны")

        if not fetch_all_products and products_fetch_succeeded == 0:
            warnings.append("Sample-режим: не удалось получить ни одну карточку")

        if not warnings:
            warnings.append("Диагностика выполнена без предупреждений")

        if len(discovery_flags) == 0:
            discovery_mode = "unknown"
        elif len(discovery_flags) == 1:
            discovery_mode = discovery_flags[0]
        else:
            discovery_mode = "mixed_discovery"

        error_details = list(errors_by_url.values())
        if not error_details:
            error_details = ["Детальных ошибок не зафиксировано"]

        return ShopifyDiscoveryResult(
            base_url=normalized_base_url,
            sitemap_url=sitemap_url,
            discovery_mode=discovery_mode,
            product_sitemaps_found=len(product_sitemap_urls),
            product_urls_found=len(product_urls),
            requested_previews=requested_previews,
            products_fetch_attempted=products_fetch_attempted,
            products_fetch_succeeded=products_fetch_succeeded,
            products_fetch_failed=products_fetch_failed,
            http_429_count=http_429_count,
            http_5xx_count=http_5xx_count,
            second_pass_attempted=second_pass_attempted,
            second_pass_recovered=second_pass_recovered,
            warnings=warnings[:MAX_WARNING_ITEMS],
            error_details=error_details[:error_details_limit],
            previews=ordered_previews,
        )

    @staticmethod
    def _fetch_products_batch(
        *,
        client: httpx.Client,
        product_urls: list[str],
        base_url: str,
        parallel_workers: int,
        max_retries: int,
        retry_backoff_sec: float,
    ) -> BatchFetchResult:
        """Fetch products in batch with optional parallel workers."""
        previews_by_url: dict[str, ShopifyProductPreview] = {}
        errors_by_url: dict[str, str] = {}
        warnings: list[str] = []
        http_429_count = 0
        http_5xx_count = 0

        def run_one(url: str) -> ProductFetchResult:
            return ShopifyParser._fetch_one_product(
                client=client,
                base_url=base_url,
                product_url=url,
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff_sec,
            )

        if parallel_workers <= 1:
            for product_url in product_urls:
                result = run_one(product_url)
                ShopifyParser._merge_product_result(
                    result=result,
                    previews_by_url=previews_by_url,
                    errors_by_url=errors_by_url,
                    warnings=warnings,
                )
                http_429_count += result.http_429_count
                http_5xx_count += result.http_5xx_count
        else:
            with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
                futures = {executor.submit(run_one, product_url): product_url for product_url in product_urls}
                for future in as_completed(futures):
                    result = future.result()
                    ShopifyParser._merge_product_result(
                        result=result,
                        previews_by_url=previews_by_url,
                        errors_by_url=errors_by_url,
                        warnings=warnings,
                    )
                    http_429_count += result.http_429_count
                    http_5xx_count += result.http_5xx_count

        return BatchFetchResult(
            previews_by_url=previews_by_url,
            errors_by_url=errors_by_url,
            warnings=warnings,
            http_429_count=http_429_count,
            http_5xx_count=http_5xx_count,
        )

    @staticmethod
    def _merge_product_result(
        *,
        result: ProductFetchResult,
        previews_by_url: dict[str, ShopifyProductPreview],
        errors_by_url: dict[str, str],
        warnings: list[str],
    ) -> None:
        """Merge one product fetch result into aggregations."""
        warnings.extend(result.warnings)
        if result.preview is not None:
            previews_by_url[result.product_url] = result.preview
            errors_by_url.pop(result.product_url, None)
            return

        if result.error_detail:
            errors_by_url[result.product_url] = result.error_detail
        else:
            errors_by_url[result.product_url] = f"{result.product_url} -> неизвестная ошибка загрузки"

    @staticmethod
    def _fetch_one_product(
        *,
        client: httpx.Client,
        base_url: str,
        product_url: str,
        max_retries: int,
        retry_backoff_sec: float,
    ) -> ProductFetchResult:
        """Fetch one product by URL and parse product preview."""
        handle = ShopifyParser.extract_handle(product_url)
        if not handle:
            return ProductFetchResult(
                product_url=product_url,
                preview=None,
                error_detail=f"{product_url} -> не удалось выделить handle",
                warnings=[],
                http_429_count=0,
                http_5xx_count=0,
            )

        return ShopifyParser._load_product_preview(
            client=client,
            base_url=base_url,
            product_url=product_url,
            handle=handle,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
        )

    @staticmethod
    def extract_handle(product_url: str) -> str | None:
        """Extract Shopify product handle from URL."""
        path = urlparse(product_url).path
        match = PRODUCT_PATH_RE.match(path.rstrip("/"))
        if not match:
            return None
        handle = match.group(1).strip()
        return handle or None

    @staticmethod
    def _safe_get_text(
        *,
        client: httpx.Client,
        url: str,
        warnings: list[str],
        error_label: str,
    ) -> str | None:
        """Fetch URL text with warning-based failure strategy."""
        try:
            response = client.get(url)
            if response.status_code >= 400:
                warnings.append(f"{error_label}: HTTP {response.status_code}")
                return None
            return response.text
        except httpx.RequestError as exc:
            warnings.append(f"{error_label}: {exc!s}")
            return None

    @staticmethod
    def _extract_product_sitemap_urls(sitemap_xml: str) -> list[str]:
        """Extract product sitemap URLs from sitemap index XML."""
        root = ShopifyParser._parse_xml(sitemap_xml)
        if root is None:
            return []

        urls: list[str] = []
        for loc in ShopifyParser._extract_loc_values(root):
            if "product-sitemap" in loc:
                urls.append(loc)
        return urls

    @staticmethod
    def _extract_product_urls(product_sitemap_xml: str) -> list[str]:
        """Extract product URLs from product sitemap XML."""
        root = ShopifyParser._parse_xml(product_sitemap_xml)
        if root is None:
            return []

        urls: list[str] = []
        for loc in ShopifyParser._extract_loc_values(root):
            if "/products/" in loc:
                urls.append(loc)
        return urls

    @staticmethod
    def _extract_loc_values(root: ElementTree.Element) -> list[str]:
        """Extract <loc> values from XML tree regardless of namespace."""
        values: list[str] = []
        for element in root.iter():
            if ShopifyParser._local_name(element.tag) != "loc":
                continue
            if element.text and element.text.strip():
                values.append(element.text.strip())
        return values

    @staticmethod
    def _parse_xml(raw_xml: str) -> ElementTree.Element | None:
        """Parse XML and return root element."""
        try:
            return ElementTree.fromstring(raw_xml)
        except ElementTree.ParseError:
            return None

    @staticmethod
    def _local_name(tag: str) -> str:
        """Return local XML tag name without namespace."""
        if "}" not in tag:
            return tag
        return tag.split("}", 1)[1]

    @staticmethod
    def _discover_product_urls_by_products_api(
        *,
        client: httpx.Client,
        base_url: str,
        max_products: int,
        warnings: list[str],
    ) -> list[str]:
        """Fallback discovery via /products.json with page pagination + Link pagination."""
        discovered_urls: list[str] = []
        page = 1
        next_url = f"{base_url}/products.json?limit=250&page={page}"
        max_pages = 200
        pages_count = 0

        while next_url and len(discovered_urls) < max_products and pages_count < max_pages:
            pages_count += 1
            try:
                response = client.get(next_url)
            except httpx.RequestError as exc:
                warnings.append(f"Ошибка /products.json: {exc!s}")
                break

            if response.status_code >= 400:
                warnings.append(f"/products.json вернул HTTP {response.status_code}")
                break

            try:
                payload = response.json()
            except ValueError:
                warnings.append("/products.json вернул невалидный JSON")
                break

            products = payload.get("products", [])
            if not isinstance(products, list):
                warnings.append("Некорректный формат /products.json: products не является списком")
                break

            if not products:
                break

            for product in products:
                if not isinstance(product, dict):
                    continue
                handle = str(product.get("handle", "")).strip()
                if not handle:
                    continue
                discovered_urls.append(urljoin(f"{base_url}/", f"products/{handle}"))
                if len(discovered_urls) >= max_products:
                    break

            next_from_link = ShopifyParser._extract_next_link(response.headers.get("Link"))
            if next_from_link:
                next_url = next_from_link
                continue

            page += 1
            next_url = f"{base_url}/products.json?limit=250&page={page}"

        return ShopifyParser._prepare_product_urls(
            discovered_urls,
            base_url=base_url,
            max_products=max_products,
        )

    @staticmethod
    def _discover_product_urls_by_collections_api(
        *,
        client: httpx.Client,
        base_url: str,
        max_products: int,
        warnings: list[str],
    ) -> list[str]:
        """Fallback discovery via /collections/all/products.json pagination."""
        discovered_urls: list[str] = []
        page = 1
        max_pages = 200

        while page <= max_pages and len(discovered_urls) < max_products:
            page_url = f"{base_url}/collections/all/products.json?limit=250&page={page}"
            try:
                response = client.get(page_url)
            except httpx.RequestError as exc:
                warnings.append(f"Ошибка /collections/all/products.json: {exc!s}")
                break

            if response.status_code >= 400:
                warnings.append(f"/collections/all/products.json вернул HTTP {response.status_code}")
                break

            try:
                payload = response.json()
            except ValueError:
                warnings.append("/collections/all/products.json вернул невалидный JSON")
                break

            products = payload.get("products", [])
            if not isinstance(products, list):
                warnings.append(
                    "Некорректный формат /collections/all/products.json: products не является списком"
                )
                break

            if not products:
                break

            for product in products:
                if not isinstance(product, dict):
                    continue
                handle = str(product.get("handle", "")).strip()
                if not handle:
                    continue
                discovered_urls.append(urljoin(f"{base_url}/", f"products/{handle}"))
                if len(discovered_urls) >= max_products:
                    break

            page += 1

        return ShopifyParser._prepare_product_urls(
            discovered_urls,
            base_url=base_url,
            max_products=max_products,
        )

    @staticmethod
    def _extract_next_link(link_header: str | None) -> str | None:
        """Parse Link header and return URL with rel=next."""
        if not link_header:
            return None

        for part in link_header.split(","):
            chunk = part.strip()
            if 'rel="next"' not in chunk:
                continue
            left = chunk.find("<")
            right = chunk.find(">", left + 1)
            if left == -1 or right == -1:
                continue
            return chunk[left + 1 : right].strip()
        return None

    @staticmethod
    def _load_product_preview(
        *,
        client: httpx.Client,
        base_url: str,
        product_url: str,
        handle: str,
        max_retries: int,
        retry_backoff_sec: float,
    ) -> ProductFetchResult:
        """Load single product preview from .js with .json fallback."""
        js_url = f"{base_url}/products/{handle}.js"
        json_url = f"{base_url}/products/{handle}.json"
        warnings: list[str] = []
        http_429_count = 0
        http_5xx_count = 0
        payload_source = "js"

        js_payload, js_warnings, js_429, js_5xx = ShopifyParser._request_json_with_retries(
            client=client,
            url=js_url,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
        )
        warnings.extend(js_warnings)
        http_429_count += js_429
        http_5xx_count += js_5xx

        product_data: dict[str, Any] | None = None
        if isinstance(js_payload, dict):
            product_data = js_payload

        if product_data is None:
            payload_source = "json"
            json_payload, json_warnings, json_429, json_5xx = ShopifyParser._request_json_with_retries(
                client=client,
                url=json_url,
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff_sec,
            )
            warnings.extend(json_warnings)
            http_429_count += json_429
            http_5xx_count += json_5xx

            if not isinstance(json_payload, dict):
                return ProductFetchResult(
                    product_url=product_url,
                    preview=None,
                    error_detail=f"{product_url} -> ошибка запроса .json",
                    warnings=warnings,
                    http_429_count=http_429_count,
                    http_5xx_count=http_5xx_count,
                )

            raw_product = json_payload.get("product")
            if not isinstance(raw_product, dict):
                return ProductFetchResult(
                    product_url=product_url,
                    preview=None,
                    error_detail=f"{product_url} -> объект product отсутствует в .json",
                    warnings=warnings,
                    http_429_count=http_429_count,
                    http_5xx_count=http_5xx_count,
                )
            product_data = raw_product

        variants = product_data.get("variants", [])
        first_variant = variants[0] if isinstance(variants, list) and variants else {}
        if not isinstance(first_variant, dict):
            first_variant = {}

        preview = ShopifyProductPreview(
            product_url=product_url,
            handle=handle,
            product_id=str(product_data.get("id")) if product_data.get("id") is not None else None,
            title=ShopifyParser._to_optional_str(product_data.get("title")),
            vendor=ShopifyParser._to_optional_str(product_data.get("vendor")),
            price=ShopifyParser._to_decimal_string(first_variant.get("price")),
            currency=ShopifyParser._extract_currency(first_variant),
            payload_source=payload_source,
        )

        return ProductFetchResult(
            product_url=product_url,
            preview=preview,
            error_detail=None,
            warnings=warnings,
            http_429_count=http_429_count,
            http_5xx_count=http_5xx_count,
        )

    @staticmethod
    def _request_json_with_retries(
        *,
        client: httpx.Client,
        url: str,
        max_retries: int,
        retry_backoff_sec: float,
    ) -> tuple[dict[str, Any] | list[Any] | None, list[str], int, int]:
        """Request JSON endpoint with retries for transient failures."""
        warnings: list[str] = []
        http_429_count = 0
        http_5xx_count = 0

        for attempt in range(max_retries + 1):
            try:
                response = client.get(url)
            except httpx.RequestError as exc:
                warnings.append(f"Ошибка чтения {url}: {exc!s}")
                if attempt < max_retries:
                    sleep(retry_backoff_sec * (2**attempt))
                    continue
                return None, warnings, http_429_count, http_5xx_count

            status = response.status_code
            if status >= 400:
                if status == 429:
                    http_429_count += 1
                if 500 <= status <= 599:
                    http_5xx_count += 1

                warnings.append(f"Не удалось получить {url}: HTTP {status}")
                if attempt < max_retries and (status in RETRIABLE_STATUS_CODES or 500 <= status <= 599):
                    sleep(retry_backoff_sec * (2**attempt))
                    continue
                return None, warnings, http_429_count, http_5xx_count

            try:
                payload = response.json()
            except ValueError:
                warnings.append(f"Некорректный JSON в {url}")
                if attempt < max_retries:
                    sleep(retry_backoff_sec * (2**attempt))
                    continue
                return None, warnings, http_429_count, http_5xx_count

            return payload, warnings, http_429_count, http_5xx_count

        return None, warnings, http_429_count, http_5xx_count

    @staticmethod
    def _prepare_product_urls(values: list[str], *, base_url: str, max_products: int) -> list[str]:
        """Normalize, filter and deduplicate product URLs."""
        normalized: list[str] = []
        for raw_url in values:
            normalized_url = ShopifyParser._normalize_product_url(raw_url, base_url=base_url)
            if not normalized_url:
                continue
            if not ShopifyParser._is_valid_product_url(normalized_url):
                continue
            normalized.append(normalized_url)
        return ShopifyParser._dedupe_and_limit(normalized, max_items=max_products)

    @staticmethod
    def _normalize_product_url(raw_url: str, *, base_url: str) -> str | None:
        """Normalize product URL and strip query/fragment."""
        raw = str(raw_url).strip()
        if not raw:
            return None
        absolute = urljoin(f"{base_url}/", raw)
        parsed = urlparse(absolute)
        if not parsed.netloc:
            return None
        clean = parsed._replace(query="", fragment="")
        return urlunparse(clean)

    @staticmethod
    def _is_valid_product_url(url: str) -> bool:
        """Check that URL points to /products/{handle} without extra path segments."""
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        return bool(PRODUCT_PATH_RE.match(path))

    @staticmethod
    def _extract_currency(variant: dict[str, Any]) -> str | None:
        """Extract variant currency from several known Shopify payload shapes."""
        for key in ("price_currency", "currency", "currency_code"):
            value = ShopifyParser._to_optional_str(variant.get(key))
            if value:
                return value

        presentment_prices = variant.get("presentment_prices")
        if isinstance(presentment_prices, list):
            for item in presentment_prices:
                if not isinstance(item, dict):
                    continue
                price_block = item.get("price")
                if not isinstance(price_block, dict):
                    continue
                currency_code = ShopifyParser._to_optional_str(price_block.get("currency_code"))
                if currency_code:
                    return currency_code
        return None

    @staticmethod
    def _to_decimal_string(raw_value: Any) -> str | None:
        """Convert incoming numeric/string value to normalized decimal string."""
        if raw_value is None:
            return None
        raw_text = str(raw_value).strip()
        if not raw_text:
            return None
        try:
            value = Decimal(raw_text)
        except InvalidOperation:
            return None
        return f"{value:.2f}"

    @staticmethod
    def _to_optional_str(raw_value: Any) -> str | None:
        """Convert value to stripped string or None."""
        if raw_value is None:
            return None
        text = str(raw_value).strip()
        return text or None

    @staticmethod
    def _dedupe_and_limit(values: list[str], *, max_items: int) -> list[str]:
        """Deduplicate list preserving input order and apply max_items limit."""
        deduped = list(dict.fromkeys(values))
        return deduped[:max_items]
