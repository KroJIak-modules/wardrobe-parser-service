"""
API endpoints for product catalog.
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.parser import (
    ProductResponse,
    ProductListResponse,
)
from app.repositories import ParserProductRepository, ParserSourceRepository
from app.models import ProductStatus

router = APIRouter(prefix="/api/v1", tags=["products"])


@router.get("/products", response_model=ProductListResponse)
def get_products(
    source_id: Optional[int] = Query(None),
    vendor: Optional[str] = Query(None),
    product_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    price_min: Optional[float] = Query(None),
    price_max: Optional[float] = Query(None),
    search: Optional[str] = Query(None, description="Search in title, handle, vendor"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Get paginated product list with advanced filtering.
    
    Query Parameters:
    - source_id: Filter by source (Shopify store)
    - vendor: Filter by brand/vendor
    - product_type: Filter by category
    - status: Filter by availability (available|out_of_stock|discontinued)
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
    product_repo = ParserProductRepository(db)
    
    # Parse vendors and product_types (may be comma-separated from frontend)
    vendors = [v.strip() for v in vendor.split(",")] if vendor else None
    product_types = [t.strip() for t in product_type.split(",")] if product_type else None
    source_ids = [source_id] if source_id else None
    
    # Fetch products with filters
    products = product_repo.filter_products(
        source_ids=source_ids,
        vendors=vendors,
        product_types=product_types,
        status=status,
        price_min=price_min,
        price_max=price_max,
        search_text=search,
        skip=offset,
        limit=limit,
    )
    
    # Count total matches
    total = product_repo.count_filtered(
        source_ids=source_ids,
        vendors=vendors,
        product_types=product_types,
        status=status,
        price_min=price_min,
        price_max=price_max,
        search_text=search,
    )
    
    # Build filter options for UI
    source_repo = ParserSourceRepository(db)
    all_vendors = product_repo.get_distinct_vendors(source_id=source_id)
    all_types = product_repo.get_distinct_product_types(source_id=source_id)
    price_range = product_repo.get_price_range(source_id=source_id)
    
    # Get sources with product counts
    sources = source_repo.get_all_active()
    sources_data = [
        {
            "id": s.id,
            "name": s.name,
            "count": product_repo.count_by_source(s.id),
        }
        for s in sources
    ]
    
    filters = {
        "sources": sources_data,
        "vendors": all_vendors,
        "product_types": all_types,
        "price_range": {
            "min": price_range.get("min_price"),
            "max": price_range.get("max_price"),
        },
        "statuses": [
            {"name": ProductStatus.AVAILABLE, "label": "Available"},
            {"name": ProductStatus.OUT_OF_STOCK, "label": "Out of Stock"},
            {"name": ProductStatus.DISCONTINUED, "label": "Discontinued"},
        ],
    }
    
    return ProductListResponse(
        items=[ProductResponse.model_validate(p) for p in products],
        total=total,
        limit=limit,
        offset=offset,
        filters=filters,
    )


@router.get("/products/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: Session = Depends(get_db)):
    """Get single product by ID."""
    product_repo = ParserProductRepository(db)
    product = product_repo.get_by_id(product_id)
    
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found"
        )
    
    return ProductResponse.model_validate(product)
