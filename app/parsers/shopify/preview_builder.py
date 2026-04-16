"""Payload-to-preview conversion helpers for Shopify parser."""

from __future__ import annotations

from typing import Any

from app.parsers.product_extractor import ShopifyProductExtractor
from app.parsers.shopify.models import ShopifyProductPreview


def build_preview_from_payload(
    product_url: str,
    handle: str,
    payload: dict[str, Any],
    *,
    payload_source: str,
) -> ShopifyProductPreview:
    """Build preview from raw payload extracted from .js or .json product endpoints."""
    product_id = ShopifyProductExtractor._safe_str(payload.get("id"))
    title = ShopifyProductExtractor._safe_str(payload.get("title"))
    description = ShopifyProductExtractor.extract_description(payload)
    vendor = ShopifyProductExtractor._safe_str(payload.get("vendor"))
    product_type = ShopifyProductExtractor._safe_str(payload.get("product_type"))
    price = ShopifyProductExtractor.extract_price(payload)
    currency = ShopifyProductExtractor.extract_currency(payload)
    image_urls = ShopifyProductExtractor.extract_image_urls(payload)
    available = ShopifyProductExtractor.extract_availability(payload)
    variants = ShopifyProductExtractor.extract_variants(payload)
    weight_data = ShopifyProductExtractor.extract_weight(payload)
    return ShopifyProductPreview(
        product_url=product_url,
        handle=handle,
        product_id=product_id,
        title=title,
        description=description,
        vendor=vendor,
        product_type=product_type,
        price=price,
        currency=currency,
        image_urls=image_urls,
        payload_source=payload_source,
        available=available,
        variants=variants,
        weight_grams=weight_data.get("weight_grams"),
        weight_source="source" if weight_data.get("weight_grams") else None,
        weight_match_keyword=None,
        weight_value=weight_data.get("weight_value"),
        weight_unit=weight_data.get("weight_unit"),
    )
