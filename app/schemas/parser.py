"""
Pydantic schemas for API requests/responses.
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class ProductResponse(BaseModel):
    """Product entity response."""
    id: int
    source_id: int
    handle: str
    title: str
    vendor: Optional[str] = None
    product_type: Optional[str] = None
    url: str
    price: Optional[float] = None
    currency: str
    status: str
    image_count: int
    image_urls: list[str] = Field(default_factory=list)
    image_ids: list[int] = Field(default_factory=list)
    variants: list[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProductListResponse(BaseModel):
    """Paginated products response with available filters."""
    items: List[ProductResponse]
    total: int
    limit: int
    offset: int
    filters: dict = Field(
        default_factory=dict,
        description="Available filter options"
    )


class ProductFilterResponse(BaseModel):
    """Available filter options for product list."""
    sources: List[dict] = Field(default_factory=list)  # [{id, name, count}]
    vendors: List[dict] = Field(default_factory=list)  # [{name, count}]
    product_types: List[dict] = Field(default_factory=list)  # [{name, count}]
    price_range: dict = Field(default_factory=dict)  # {min, max}
    statuses: List[dict] = Field(default_factory=list)  # [{name, count}]


class SourceRunResponse(BaseModel):
    """Source execution within a job."""
    id: int
    source_id: int
    status: str
    products_discovered: int
    products_fetched: int
    products_failed: int
    error_message: Optional[str] = None
    discovery_mode: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class JobResponse(BaseModel):
    """Full job detail response."""
    id: str
    status: str
    triggered_by: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    total_products: Optional[int] = None
    new_products: Optional[int] = 0
    updated_products: Optional[int] = 0
    new_images: Optional[int] = 0
    error_count: int = 0
    http_429_count: int = 0
    http_5xx_count: int = 0
    source_runs: List[SourceRunResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class JobLatestResponse(BaseModel):
    """Simplified latest job status for frontend."""
    job_id: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    next_scheduled_at: Optional[datetime] = None
    total_products: Optional[int] = None
    new_products: int = 0
    updated_products: int = 0
    new_images: int = 0
    total_sources: int = 0
    processed_sources: int = 0
    progress_percent: int = 0
    processed_products: int = 0
    expected_products: int = 0
    failed_products: int = 0
    products_progress_percent: int = 0
    current_source_name: Optional[str] = None
    current_source_index: int = 0
    current_stage: Optional[str] = None
    current_source_processed_products: int = 0
    current_source_total_products: int = 0
    current_product_title: Optional[str] = None
    site_products_total: int = 0
    can_cancel: bool = False
    sync_period_minutes: int


class JobCreateRequest(BaseModel):
    """Request to create manual sync job."""
    triggered_by: str = Field(default="manual")


class JobCreateResponse(BaseModel):
    """Response when creating job."""
    id: str
    status: str
    created_at: datetime


class JobCancelResponse(BaseModel):
    """Response when cancelling running/pending job."""
    id: str
    status: str
    message: str


class ProductAddByUrlRequest(BaseModel):
    """Request for adding a product from URL preview."""

    url: str = Field(min_length=8, max_length=2048)
    title: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    vendor: Optional[str] = Field(default=None, max_length=255)
    product_type: Optional[str] = Field(default=None, max_length=255)
    price: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    image_count: Optional[int] = Field(default=None, ge=0)


class ProductUrlPreviewResponse(BaseModel):
    """Preview payload for URL-based product adding flow."""

    handle: str
    title: str
    vendor: Optional[str] = None
    product_type: Optional[str] = None
    product_url: str
    price: Optional[float] = None
    currency: str = "USD"
    image_urls: list[str] = Field(default_factory=list)


class ProductManualCreateRequest(BaseModel):
    """Request for manually creating a product."""

    title: str = Field(min_length=1, max_length=2048)
    price: Optional[float] = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    product_type: Optional[str] = Field(default=None, max_length=255)
    vendor: Optional[str] = Field(default="Manual", max_length=255)
    image_count: int = Field(default=0, ge=0)


class CategoryKeywordRequest(BaseModel):
    """Add keyword into a category."""

    keyword: str = Field(min_length=1, max_length=255)


class CategoryCreateRequest(BaseModel):
    """Create one category node."""

    name: str = Field(min_length=1, max_length=255)
    parent_id: Optional[int] = None


class CategoryUpdateRequest(BaseModel):
    """Update one category node."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    parent_id: Optional[int] = None


class CategoryTreeNodeResponse(BaseModel):
    """Recursive category tree response."""

    id: int
    name: str
    slug: str
    parent_id: Optional[int] = None
    is_fallback: bool
    keywords: list[str] = Field(default_factory=list)
    effective_keywords: list[str] = Field(default_factory=list)
    children: list["CategoryTreeNodeResponse"] = Field(default_factory=list)

    class Config:
        from_attributes = True


class DedupCandidateResponse(BaseModel):
    """One duplicate candidate pair for moderation UI."""

    pair_key: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    left: ProductResponse
    right: ProductResponse


class DedupCandidateListResponse(BaseModel):
    """Paginated dedup candidate list."""

    items: list[DedupCandidateResponse]
    total: int
    limit: int


class DedupMergeRequest(BaseModel):
    """Request to merge duplicate pair."""

    primary_product_id: int
    duplicate_product_id: int


class DedupRejectRequest(BaseModel):
    """Request to mark pair as non-duplicate."""

    product_a_id: int
    product_b_id: int


class ErrorResponse(BaseModel):
    """Error response."""
    code: str
    message: str
    details: Optional[dict] = None


CategoryTreeNodeResponse.model_rebuild()
