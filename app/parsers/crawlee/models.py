"""Typed models for Crawlee parser subprocess payload."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CrawleeProductPreviewPayload(BaseModel):
    """One product preview payload emitted by Crawlee runner."""

    product_url: str = Field(min_length=1, max_length=4096)
    handle: str = Field(min_length=1, max_length=512)
    title: str | None = None
    description: str | None = None
    vendor: str | None = None
    product_type: str | None = None
    price: str | None = None
    currency: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    available: bool = True
    variants: list[dict] = Field(default_factory=list)
    payload_source: str = "crawlee"


class CrawleeDiscoveryPayload(BaseModel):
    """Full discovery payload emitted by Crawlee runner."""

    base_url: str = Field(min_length=1, max_length=1024)
    discovery_mode: str = Field(default="crawlee")
    product_urls_found: int = Field(ge=0)
    products_fetch_attempted: int = Field(ge=0)
    products_fetch_succeeded: int = Field(ge=0)
    products_fetch_failed: int = Field(ge=0)
    http_429_count: int = Field(default=0, ge=0)
    http_5xx_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    error_details: list[str] = Field(default_factory=list)
    previews: list[CrawleeProductPreviewPayload] = Field(default_factory=list)

