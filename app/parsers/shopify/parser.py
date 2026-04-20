"""Shopify discovery parser with resilient fallback and diagnostics."""

from __future__ import annotations

import re
from typing import Callable
from urllib.parse import urlparse

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.parsers.shopify.discovery.fetch_pipeline import run_preview_fetch_pipeline
from app.parsers.shopify.discovery.orchestrator import collect_discovery_urls
from app.parsers.shopify.discovery.result_builder import (
    build_discovery_summary,
    resolve_discovery_mode,
)
from app.parsers.shopify.models import ShopifyDiscoveryResult, ShopifyProductPreview
from app.parsers.shopify.preview_builder import build_preview_from_payload
from app.parsers.shopify.preview_fetcher import fetch_one_product_preview
from app.parsers.shopify_url_utils import (
    dedupe_and_keep_ordered_previews,
    normalize_base_url,
    normalize_product_url,
)

_PRODUCT_SITEMAP_RE = re.compile(r"(product-sitemap|sitemap_products)", re.IGNORECASE)


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

        outcome = fetch_one_product_preview(
            base_url=base_url,
            product_url=normalized_product_url,
            cached_payload=None,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            build_preview=build_preview_from_payload,
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
        deadline_monotonic: float | None = None,
        on_progress: Callable[[], None] | None = None,
    ) -> ShopifyDiscoveryResult:
        """Run discovery and optionally fetch product previews."""
        resolved_base_url = normalize_base_url(base_url)
        discovery = collect_discovery_urls(
            base_url=resolved_base_url,
            product_sitemap_re=_PRODUCT_SITEMAP_RE,
            max_products=max_products,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            deadline_monotonic=deadline_monotonic,
            on_progress=on_progress,
        )

        discovery_mode = resolve_discovery_mode(
            from_sitemap=discovery.source_from_sitemap,
            from_fallback=discovery.source_from_fallback,
        )

        # Select which URLs to preview
        if fetch_all_products:
            target_urls = discovery.discovered_urls
        else:
            target_urls = discovery.discovered_urls[:sample_products]

        return cls._build_result_from_target_urls(
            resolved_base_url=resolved_base_url,
            sitemap_url=discovery.sitemap_url,
            discovery_mode=discovery_mode,
            product_sitemaps_found=discovery.product_sitemaps_found,
            product_urls_found=len(discovery.discovered_urls),
            target_urls=target_urls,
            payload_cache=discovery.payload_cache,
            warnings=discovery.warnings,
            response_products_limit=response_products_limit,
            error_details_limit=error_details_limit,
            fetch_all_products=fetch_all_products,
            timeout_sec=timeout_sec,
            parallel_workers=parallel_workers,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            second_pass_enabled=second_pass_enabled,
            second_pass_timeout_sec=second_pass_timeout_sec,
            deadline_monotonic=deadline_monotonic,
            on_progress=on_progress,
        )

    @classmethod
    def _build_result_from_target_urls(
        cls,
        *,
        resolved_base_url: str,
        sitemap_url: str,
        discovery_mode: str,
        product_sitemaps_found: int,
        product_urls_found: int,
        target_urls: list[str],
        payload_cache: dict[str, dict],
        warnings: list[str],
        response_products_limit: int,
        error_details_limit: int,
        fetch_all_products: bool,
        timeout_sec: float,
        parallel_workers: int,
        max_retries: int,
        retry_backoff_sec: float,
        second_pass_enabled: bool,
        second_pass_timeout_sec: float,
        deadline_monotonic: float | None = None,
        on_progress: Callable[[], None] | None = None,
    ) -> ShopifyDiscoveryResult:
        """Build final discovery result from a prepared URL list."""
        fetch_attempted = len(target_urls)
        pipeline = run_preview_fetch_pipeline(
            base_url=resolved_base_url,
            target_urls=target_urls,
            payload_cache=payload_cache,
            timeout_sec=timeout_sec,
            parallel_workers=parallel_workers,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
            second_pass_enabled=second_pass_enabled,
            second_pass_timeout_sec=second_pass_timeout_sec,
            build_preview=build_preview_from_payload,
            deadline_monotonic=deadline_monotonic,
            on_progress=on_progress,
        )
        previews = pipeline.previews
        final_errors = pipeline.final_errors
        http_429_count = pipeline.http_429_count
        http_5xx_count = pipeline.http_5xx_count
        second_pass_attempted = pipeline.second_pass_attempted
        second_pass_recovered = pipeline.second_pass_recovered

        previews = dedupe_and_keep_ordered_previews(target_urls=target_urls, previews=previews)

        summary = build_discovery_summary(
            previews=previews,
            final_errors=final_errors,
            fetch_all_products=fetch_all_products,
            fetch_attempted=fetch_attempted,
            response_products_limit=response_products_limit,
            error_details_limit=error_details_limit,
            warning_items_limit=settings.parser_discovery_warning_items_limit,
            second_pass_attempted=second_pass_attempted,
            second_pass_recovered=second_pass_recovered,
        )

        return ShopifyDiscoveryResult(
            base_url=resolved_base_url,
            sitemap_url=sitemap_url,
            discovery_mode=discovery_mode,
            product_sitemaps_found=product_sitemaps_found,
            product_urls_found=product_urls_found,
            requested_previews=fetch_attempted,
            products_fetch_attempted=fetch_attempted,
            products_fetch_succeeded=summary.products_fetch_succeeded,
            products_fetch_failed=summary.products_fetch_failed,
            http_429_count=http_429_count,
            http_5xx_count=http_5xx_count,
            second_pass_attempted=second_pass_attempted,
            second_pass_recovered=second_pass_recovered,
            warnings=warnings + summary.warnings,
            error_details=summary.error_details,
            previews=summary.previews,
        )
