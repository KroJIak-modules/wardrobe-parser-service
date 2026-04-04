"""Data models for Shopify parser discovery responses."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    available: bool = True  # ← Product availability based on variants
    variants: list[dict] = field(default_factory=list)  # ← Size/color variants with availability
    weight_grams: float | None = None
    weight_source: str | None = None
    weight_match_keyword: str | None = None
    weight_value: float | None = None
    weight_unit: str | None = None


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
