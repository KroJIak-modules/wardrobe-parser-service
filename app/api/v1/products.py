"""
API endpoints for product catalog.
"""

import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.config.source_registry import list_sources
from app.core.config import settings
from app.core.database import get_db
from app.schemas.parser import (
    ProductAddByUrlRequest,
    ProductManualCreateRequest,
    ProductResponse,
    ProductListResponse,
    ProductUrlPreviewResponse,
)
from app.repositories import ParserProductRepository, ParserSourceRepository, ParserImageAssetRepository
from app.models import ProductStatus
from app.parsers.shopify_parser import ShopifyParser

router = APIRouter(tags=["products"])
_upload_dir = Path("/app/uploads")


def _build_product_response(product) -> ProductResponse:
    image_urls = product.image_urls or []
    image_ids = product.image_asset_ids or []
    return ProductResponse(
        id=product.id,
        source_id=product.source_id,
        handle=product.handle,
        title=product.title,
        vendor=product.vendor,
        product_type=product.product_type,
        url=product.url,
        price=product.price,
        currency=product.currency,
        status=product.status,
        image_count=product.image_count,
        image_urls=image_urls,
        image_ids=image_ids,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def _clean_host(url: str) -> str:
    return urlparse(url).hostname.lower().replace("www.", "")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "product"


def _allowed_shopify_hosts() -> list[str]:
    hosts: list[str] = []
    for source in list_sources(parser_type="shopify"):
        if not source.enabled:
            continue
        host = _clean_host(source.base_url)
        if host:
            hosts.append(host)
    return hosts


def _resolve_or_create_source(db: Session, product_url: str):
    host = _clean_host(product_url)
    source_repo = ParserSourceRepository(db)

    for source_cfg in list_sources(parser_type="shopify"):
        cfg_host = _clean_host(source_cfg.base_url)
        if host == cfg_host or host.endswith(f".{cfg_host}"):
            source = source_repo.get_by_url(source_cfg.base_url)
            if source:
                return source
            return source_repo.create_source(
                name=source_cfg.name,
                url=source_cfg.base_url,
                parser_type=source_cfg.parser_type,
                enabled=source_cfg.enabled,
            )

    source = source_repo.get_by_url(f"https://{host}")
    if source:
        return source
    return source_repo.create_source(name=host, url=f"https://{host}", parser_type="shopify", enabled=True)


def _normalize_preview_price(raw_price: str | None, payload_source: str | None) -> float | None:
    if raw_price is None:
        return None
    try:
        parsed = float(raw_price)
    except ValueError:
        return None

    # Shopify .js often returns integer cents while .json returns decimal currency units.
    if payload_source == "js" and parsed >= 1000 and parsed.is_integer():
        return parsed / 100
    return parsed


def _fetch_preview(url: str):
    try:
        host = _clean_host(url)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный URL") from exc

    allowed_hosts = _allowed_shopify_hosts()
    if not any(host == item or host.endswith(f".{item}") for item in allowed_hosts):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Домен не входит в whitelist")

    try:
        return ShopifyParser.preview_product_url(
            url,
            timeout_sec=settings.parser_default_timeout_sec,
            max_retries=settings.parser_default_max_retries,
            retry_backoff_sec=settings.parser_default_retry_backoff_sec,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Не удалось получить preview: {exc}",
        ) from exc


@router.post("/products/preview-by-url", response_model=ProductUrlPreviewResponse)
def preview_product_by_url(payload: ProductAddByUrlRequest):
    """Validate URL and return preview fields for admin editing before saving."""
    preview = _fetch_preview(payload.url)
    return ProductUrlPreviewResponse(
        handle=preview.handle,
        title=preview.title or preview.handle,
        vendor=preview.vendor,
        product_type=None,
        product_url=preview.product_url,
        price=_normalize_preview_price(preview.price, preview.payload_source),
        currency=(preview.currency or "USD").upper(),
        image_urls=preview.image_urls,
    )


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
    image_repo = ParserImageAssetRepository(db)
    
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
    
    products_image_urls: list[str] = []
    for product in products:
        products_image_urls.extend(product.image_urls or [])
    assets = image_repo.get_by_source_urls(products_image_urls)
    url_to_id = {asset.source_url: asset.id for asset in assets}

    for product in products:
        if product.image_urls:
            product.image_asset_ids = [url_to_id[url] for url in product.image_urls if url in url_to_id]

    return ProductListResponse(
        items=[_build_product_response(p) for p in products],
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
    
    image_repo = ParserImageAssetRepository(db)
    assets = image_repo.get_by_source_urls(product.image_urls or [])
    by_url = {asset.source_url: asset.id for asset in assets}
    product.image_asset_ids = [by_url[url] for url in (product.image_urls or []) if url in by_url]
    return _build_product_response(product)


@router.post("/products/add-by-url", response_model=ProductResponse)
def add_product_by_url(payload: ProductAddByUrlRequest, db: Session = Depends(get_db)):
    """Validate URL against whitelist, fetch Shopify preview, and upsert product."""
    preview = _fetch_preview(payload.url)

    source = _resolve_or_create_source(db, preview.product_url)
    product_repo = ParserProductRepository(db)
    image_repo = ParserImageAssetRepository(db)
    existing = product_repo.get_by_source_and_handle(source.id, preview.handle)
    price = payload.price if payload.price is not None else _normalize_preview_price(preview.price, preview.payload_source)
    final_title = payload.title.strip() if payload.title else (preview.title or preview.handle)
    final_vendor = payload.vendor if payload.vendor is not None else preview.vendor
    final_product_type = payload.product_type.strip() if payload.product_type else None
    final_currency = (payload.currency or preview.currency or "USD").upper()
    resolved_image_urls = preview.image_urls or []
    assets = image_repo.ensure_assets(resolved_image_urls)
    resolved_image_asset_ids = [asset.id for asset in assets]
    final_image_count = payload.image_count if payload.image_count is not None else len(resolved_image_urls)

    if existing:
        existing.title = final_title or existing.title
        existing.vendor = final_vendor
        existing.product_type = final_product_type
        existing.url = preview.product_url
        existing.price = price
        existing.currency = final_currency or existing.currency
        if final_image_count is not None:
            existing.image_count = final_image_count
        existing.image_urls = resolved_image_urls
        existing.image_asset_ids = resolved_image_asset_ids
        existing.deleted_at = None
        db.commit()
        db.refresh(existing)
        return _build_product_response(existing)

    product = product_repo.create_product(
        source_id=source.id,
        handle=preview.handle,
        title=final_title,
        vendor=final_vendor,
        product_type=final_product_type,
        url=preview.product_url,
        price=price,
        currency=final_currency,
        image_count=final_image_count or 0,
        image_urls=resolved_image_urls,
        image_asset_ids=resolved_image_asset_ids,
        status=ProductStatus.AVAILABLE,
    )
    db.commit()
    db.refresh(product)
    return _build_product_response(product)


@router.post("/products/manual", response_model=ProductResponse)
def create_manual_product(payload: ProductManualCreateRequest, db: Session = Depends(get_db)):
    """Create manual product record for admin modal flow."""
    source_repo = ParserSourceRepository(db)
    source = source_repo.get_by_url("https://manual.local")
    if not source:
        source = source_repo.create_source(
            name="Manual Upload",
            url="https://manual.local",
            parser_type="custom",
            enabled=True,
        )

    product_repo = ParserProductRepository(db)
    handle_base = _slugify(payload.title)
    handle = handle_base

    while product_repo.get_by_source_and_handle(source.id, handle):
        handle = f"{handle_base}-{int(time.time())}"

    product = product_repo.create_product(
        source_id=source.id,
        handle=handle,
        title=payload.title,
        vendor=(payload.vendor or "Manual"),
        product_type=payload.product_type,
        url=f"https://manual.local/products/{handle}",
        price=payload.price,
        currency=payload.currency.upper(),
        image_count=payload.image_count,
        status=ProductStatus.AVAILABLE,
    )
    db.commit()
    db.refresh(product)
    return _build_product_response(product)


@router.post("/products/upload-image")
async def upload_product_image(file: UploadFile = File(...)):
    """Upload one image file for manual product flow."""
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Файл не передан")

    extension = Path(file.filename).suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Недопустимый формат изображения")

    _upload_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = _slugify(Path(file.filename).stem)
    unique_name = f"{safe_stem}-{int(time.time())}{extension}"
    target = _upload_dir / unique_name

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пустой файл")
    target.write_bytes(content)

    return {
        "ok": True,
        "file_name": unique_name,
        "stored_path": str(target),
    }
