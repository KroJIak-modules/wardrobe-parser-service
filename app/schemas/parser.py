"""
Pydantic schemas for API requests/responses.
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class ProductResponse(BaseModel):
    """Product entity response."""
    id: int
    handle: str
    title: str
    vendor: Optional[str] = None
    product_type: Optional[str] = None
    url: str
    price: Optional[float] = None
    currency: str
    status: str
    image_count: int
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
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    next_scheduled_at: Optional[datetime] = None
    total_products: Optional[int] = None
    new_products: int = 0
    updated_products: int = 0
    new_images: int = 0


class JobCreateRequest(BaseModel):
    """Request to create manual sync job."""
    triggered_by: str = Field(default="manual")


class JobCreateResponse(BaseModel):
    """Response when creating job."""
    id: str
    status: str
    created_at: datetime


class ErrorResponse(BaseModel):
    """Error response."""
    code: str
    message: str
    details: Optional[dict] = None
