"""Service layer for Shopify discovery endpoints."""

from __future__ import annotations

from app.config.source_registry import get_source_by_key
from app.core.exceptions import ValidationError
from app.parsers.shopify.parser import ShopifyParser
from app.schemas.shopify import (
    ShopifyDiscoveryRequest,
    ShopifyDiscoveryResponse,
    ShopifyProductPreviewResponse,
)


class ShopifyDiscoveryService:
    """Service with business flow for Shopify discovery diagnostics."""

    @staticmethod
    def discover(payload: ShopifyDiscoveryRequest) -> ShopifyDiscoveryResponse:
        """Run discovery and return normalized response model."""
        source_key: str | None = payload.source_key
        resolved_base_url = payload.base_url
        parser_type = "shopify"

        if source_key:
            source = get_source_by_key(source_key)
            if not source.enabled:
                raise ValidationError(f"Источник '{source_key}' отключен в sources файле")
            if source.parser_type != "shopify":
                raise ValidationError(
                    f"Источник '{source_key}' имеет parser_type='{source.parser_type}', "
                    "для этого endpoint нужен тип 'shopify'"
                )
            resolved_base_url = source.base_url
            parser_type = source.parser_type

        if not resolved_base_url:
            raise ValidationError("Не передан base_url и не выбран source_key")

        result = ShopifyParser.discover(
            resolved_base_url,
            max_products=payload.max_products,
            sample_products=payload.sample_products,
            timeout_sec=payload.timeout_sec,
            fetch_all_products=payload.fetch_all_products,
            response_products_limit=payload.response_products_limit,
            error_details_limit=payload.error_details_limit,
            parallel_workers=payload.parallel_workers,
            max_retries=payload.max_retries,
            retry_backoff_sec=payload.retry_backoff_sec,
            second_pass_enabled=payload.second_pass_enabled,
            second_pass_timeout_sec=payload.second_pass_timeout_sec,
        )

        previews = [
            ShopifyProductPreviewResponse(
                product_url=item.product_url,
                handle=item.handle,
                product_id=item.product_id,
                title=item.title,
                vendor=item.vendor,
                price=item.price,
                currency=item.currency,
                payload_source=item.payload_source,
            )
            for item in result.previews
        ]

        return ShopifyDiscoveryResponse(
            source_key=source_key,
            base_url=result.base_url,
            parser_type=parser_type,
            sitemap_url=result.sitemap_url,
            discovery_mode=result.discovery_mode,
            product_sitemaps_found=result.product_sitemaps_found,
            product_urls_found=result.product_urls_found,
            requested_previews=result.requested_previews,
            products_fetch_attempted=result.products_fetch_attempted,
            products_fetch_succeeded=result.products_fetch_succeeded,
            products_fetch_failed=result.products_fetch_failed,
            http_429_count=result.http_429_count,
            http_5xx_count=result.http_5xx_count,
            second_pass_attempted=result.second_pass_attempted,
            second_pass_recovered=result.second_pass_recovered,
            warnings=result.warnings,
            error_details=result.error_details,
            previews=previews,
        )
