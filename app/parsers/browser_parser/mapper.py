"""Map browser-parser payloads to shared discovery model."""

from __future__ import annotations

from app.parsers.browser_parser.models import BrowserParserDiscoveryPayload
from app.parsers.shopify.models import ShopifyDiscoveryResult, ShopifyProductPreview
from app.parsers.shopify_url_utils import normalize_base_url


def to_shopify_discovery_result(payload: BrowserParserDiscoveryPayload) -> ShopifyDiscoveryResult:
    """Convert browser-parser payload into ShopifyDiscoveryResult."""
    normalized_base_url = normalize_base_url(payload.base_url)
    previews = [
        ShopifyProductPreview(
            product_url=item.product_url,
            handle=item.handle,
            product_id=None,
            title=item.title,
            description=item.description,
            vendor=item.vendor,
            product_type=item.product_type,
            price=item.price,
            currency=(item.currency or "").upper() or None,
            image_urls=list(item.image_urls or []),
            payload_source=item.payload_source or "browser_parser",
            available=bool(item.available),
            variants=list(item.variants or []),
            weight_grams=None,
            weight_source=None,
            weight_match_keyword=None,
            weight_value=None,
            weight_unit=None,
        )
        for item in payload.previews
    ]
    return ShopifyDiscoveryResult(
        base_url=normalized_base_url,
        sitemap_url=f"{normalized_base_url}/sitemap.xml",
        discovery_mode=payload.discovery_mode or "browser_parser",
        product_sitemaps_found=0,
        product_urls_found=int(payload.product_urls_found),
        requested_previews=int(payload.products_fetch_attempted),
        products_fetch_attempted=int(payload.products_fetch_attempted),
        products_fetch_succeeded=int(payload.products_fetch_succeeded),
        products_fetch_failed=int(payload.products_fetch_failed),
        http_429_count=int(payload.http_429_count),
        http_5xx_count=int(payload.http_5xx_count),
        second_pass_attempted=0,
        second_pass_recovered=0,
        warnings=list(payload.warnings or []),
        error_details=list(payload.error_details or []),
        previews=previews,
    )

