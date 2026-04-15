"""
API endpoints for product catalog.
"""

from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.schemas.parser import (
    ProductAddByUrlRequest,
    ProductListResponse,
    ProductManualCreateRequest,
    ProductResponse,
    ProductUrlPreviewResponse,
)
from app.services.product_catalog_service import ProductCatalogService

router = APIRouter(tags=["products"])


@router.post("/products/preview-by-url", response_model=ProductUrlPreviewResponse)
def preview_product_by_url(payload: ProductAddByUrlRequest):
    """Validate URL and return preview fields for admin editing before saving."""
    service = ProductCatalogService(db=None)  # preview flow does not require DB access
    return service.preview_product_by_url(payload)


@router.get("/products", response_model=ProductListResponse)
def get_products(
    source_id: Optional[int] = Query(None),
    vendor: Optional[str] = Query(None),
    product_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    price_min: Optional[float] = Query(None),
    price_max: Optional[float] = Query(None),
    search: Optional[str] = Query(None, description="Search in title, handle, vendor"),
    limit: int = Query(
        settings.api_pagination_default_limit,
        ge=1,
        le=settings.api_pagination_max_limit,
    ),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Get paginated product list with advanced filtering.
    
    Query Parameters:
    - source_id: Filter by source (Shopify store)
    - vendor: Filter by brand/vendor
    - product_type: Filter by category
    - status: Filter by availability (available|out_of_stock|hidden)
    - price_min, price_max: Price range filter
    - search: Full-text search (title, handle, vendor)
    - limit: Items per page (1-200, default 20)
    - offset: Pagination offset (for page 2+)
    
    Response includes:
    - items: Product list
    - total: Total matching products
    - filters: Available filter options (for UI dropdowns)
    
    Example:
    GET /api/v1/products?source_id=1&vendor=RickOwens&price_min=100&price_max=1000&limit=20
    """
    service = ProductCatalogService(db)
    return service.list_products(
        source_id=source_id,
        vendor=vendor,
        product_type=product_type,
        status_value=status,
        price_min=price_min,
        price_max=price_max,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/products/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: Session = Depends(get_db)):
    """Get single product by ID."""
    service = ProductCatalogService(db)
    return service.get_product(product_id)


@router.post("/products/add-by-url", response_model=ProductResponse)
def add_product_by_url(payload: ProductAddByUrlRequest, db: Session = Depends(get_db)):
    """Validate URL against whitelist, fetch Shopify preview, and upsert product."""
    service = ProductCatalogService(db)
    return service.add_product_by_url(payload)


@router.post("/products/manual", response_model=ProductResponse)
def create_manual_product(payload: ProductManualCreateRequest, db: Session = Depends(get_db)):
    """Create manual product record for admin modal flow."""
    service = ProductCatalogService(db)
    return service.create_manual_product(payload)


@router.post("/products/upload-image")
async def upload_product_image(file: UploadFile = File(...)):
    """Upload one image file for manual product flow."""
    service = ProductCatalogService(db=None)  # upload flow does not require DB access
    return await service.upload_product_image(file)
