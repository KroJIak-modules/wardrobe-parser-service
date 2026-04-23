"""Shared discovery result types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DiscoveryCollectionResult:
    """Collected product URLs and diagnostics from discovery sources."""

    sitemap_url: str
    discovered_urls: list[str]
    payload_cache: dict[str, dict[str, Any]]
    warnings: list[str]
    source_from_sitemap: bool
    source_from_fallback: bool
    product_sitemaps_found: int


@dataclass(slots=True)
class ProductSitemapFetchResult:
    """One fetched product-sitemap payload with warnings."""

    index: int
    raw_urls: list[str]
    warning: str | None = None
    rate_limited: bool = False
