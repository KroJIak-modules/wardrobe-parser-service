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
    source_price: Optional[float] = None
    source_currency: Optional[str] = None
    final_price: Optional[float] = None
    final_currency: Optional[str] = None
    pricing_manual_required: bool = False
    pricing_reason: Optional[str] = None
    pricing_components: dict = Field(default_factory=dict)
    status: str
    image_count: int
    image_urls: list[str] = Field(default_factory=list)
    image_ids: list[int] = Field(default_factory=list)
    weight_grams: Optional[float] = None
    weight_source: Optional[str] = None
    weight_match_keyword: Optional[str] = None
    weight_value: Optional[float] = None
    weight_unit: Optional[str] = None
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


class WeightRuleKeywordRequest(BaseModel):
    """Add keyword to weight rule."""

    keyword: str = Field(min_length=1, max_length=255)


class WeightRuleCreateRequest(BaseModel):
    """Create weight rule."""

    weight_grams: int = Field(ge=1, le=100000)


class WeightRuleUpdateRequest(BaseModel):
    """Update weight rule."""

    weight_grams: int = Field(ge=1, le=100000)


class WeightRuleResponse(BaseModel):
    """Weight rule with keywords."""

    id: int
    weight_grams: int
    keywords: list[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class WeightMissingProductResponse(BaseModel):
    """One product where weight could not be resolved."""

    id: int
    title: str
    url: str
    source_id: int
    source_name: str


class PricingSettingsUpdateRequest(BaseModel):
    """Patchable parameters of final pricing formula."""

    markup_multiplier: Optional[float] = Field(default=None, ge=0.1, le=20.0)
    weight_tolerance: Optional[float] = Field(default=None, ge=0.1, le=5.0)
    promo_factor: Optional[float] = Field(default=None, ge=0.1, le=5.0)
    customs_threshold_eur: Optional[float] = Field(default=None, ge=0.0, le=10000.0)
    customs_threshold_currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    customs_duty_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    usd_to_rub: Optional[float] = Field(default=None, ge=0.01, le=100000.0)
    eur_to_rub: Optional[float] = Field(default=None, ge=0.01, le=100000.0)


class PricingSupplierRateResponse(BaseModel):
    """One SSR row for supplier by 500g step."""

    step_500g: int
    rate_rub: float


class PricingSupplierResponse(BaseModel):
    """Supplier with SSR table."""

    id: int
    key: str
    name: str
    category: str
    rate_currency: str
    rate_per_500g_value: float
    rate_per_500g_rub: float
    max_step_500g: int
    rates: list[PricingSupplierRateResponse] = Field(default_factory=list)


class PricingSupplierUpdateRequest(BaseModel):
    """Editable supplier SSR parameters."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    category: Optional[str] = Field(default=None, min_length=3, max_length=16)
    rate_currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    rate_per_500g_value: Optional[float] = Field(default=None, ge=0.0, le=1000000.0)
    rate_per_500g_rub: Optional[float] = Field(default=None, ge=0.0, le=1000000.0)
    max_step_500g: Optional[int] = Field(default=None, ge=1, le=1000)


class PricingSupplierCreateRequest(BaseModel):
    """Create a new supplier and bootstrap SSR table."""

    key: Optional[str] = Field(default=None, min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(default="main", min_length=3, max_length=16)
    rate_currency: str = Field(default="RUB", min_length=3, max_length=3)
    rate_per_500g_value: float = Field(default=0.0, ge=0.0, le=1000000.0)
    max_step_500g: int = Field(default=120, ge=1, le=1000)


class PricingSettingsResponse(BaseModel):
    """Current pricing settings and formula help content."""

    markup_multiplier: float
    weight_tolerance: float
    promo_factor: float
    customs_threshold_eur: float
    customs_threshold_currency: str
    customs_duty_rate: float
    usd_to_rub: float
    eur_to_rub: float
    suppliers: list[PricingSupplierResponse] = Field(default_factory=list)
    formula_latex: str = ""
    formula_lines: list[str] = Field(default_factory=list)
    formula_legend: list[dict[str, str]] = Field(default_factory=list)


CategoryTreeNodeResponse.model_rebuild()
