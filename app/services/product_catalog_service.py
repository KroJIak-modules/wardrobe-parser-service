"""Service layer for product catalog API operations."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config.source_registry import list_sources
from app.core.config import settings
from app.models import ProductStatus
from app.parsers.shopify_parser import ShopifyParser
from app.repositories import ParserImageAssetRepository, ParserProductRepository, ParserSourceRepository
from app.schemas.parser import (
    ProductAddByUrlRequest,
    ProductListResponse,
    ProductManualCreateRequest,
    ProductResponse,
    ProductUrlPreviewResponse,
)


class ProductCatalogService:
    """Encapsulates business logic used by product catalog endpoints."""

    def __init__(self, db: Optional[Session]):
        self.db = db
        self.product_repo = ParserProductRepository(db) if db is not None else None
        self.source_repo = ParserSourceRepository(db) if db is not None else None
        self.image_repo = ParserImageAssetRepository(db) if db is not None else None
        self._upload_dir = Path("/app/uploads")

    def _require_db(self) -> None:
        if self.db is None or self.product_repo is None or self.source_repo is None or self.image_repo is None:
            raise RuntimeError("Database session is required for this operation")

    @staticmethod
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

    @staticmethod
    def _clean_host(url: str) -> str:
        host = urlparse(url).hostname
        return (host or "").lower().replace("www.", "")

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "product"

    @staticmethod
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

    def _allowed_shopify_hosts(self) -> list[str]:
        hosts: list[str] = []
        for source in list_sources(parser_type="shopify"):
            if not source.enabled:
                continue
            host = self._clean_host(source.base_url)
            if host:
                hosts.append(host)
        return hosts

    def _resolve_or_create_source(self, product_url: str):
        self._require_db()
        host = self._clean_host(product_url)

        for source_cfg in list_sources(parser_type="shopify"):
            cfg_host = self._clean_host(source_cfg.base_url)
            if host == cfg_host or host.endswith(f".{cfg_host}"):
                source = self.source_repo.get_by_url(source_cfg.base_url)
                if source:
                    return source
                return self.source_repo.create_source(
                    name=source_cfg.name,
                    url=source_cfg.base_url,
                    parser_type=source_cfg.parser_type,
                    enabled=source_cfg.enabled,
                )

        source = self.source_repo.get_by_url(f"https://{host}")
        if source:
            return source
        return self.source_repo.create_source(name=host, url=f"https://{host}", parser_type="shopify", enabled=True)

    def _fetch_preview(self, url: str):
        try:
            host = self._clean_host(url)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный URL") from exc

        allowed_hosts = self._allowed_shopify_hosts()
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

    def preview_product_by_url(self, payload: ProductAddByUrlRequest) -> ProductUrlPreviewResponse:
        preview = self._fetch_preview(payload.url)
        return ProductUrlPreviewResponse(
            handle=preview.handle,
            title=preview.title or preview.handle,
            vendor=preview.vendor,
            product_type=preview.product_type,
            product_url=preview.product_url,
            price=self._normalize_preview_price(preview.price, preview.payload_source),
            currency=(preview.currency or "USD").upper(),
            image_urls=preview.image_urls,
        )

    def list_products(
        self,
        *,
        source_id: Optional[int],
        vendor: Optional[str],
        product_type: Optional[str],
        status_value: Optional[str],
        price_min: Optional[float],
        price_max: Optional[float],
        search: Optional[str],
        limit: int,
        offset: int,
    ) -> ProductListResponse:
        self._require_db()
        vendors = [v.strip() for v in vendor.split(",")] if vendor else None
        product_types = [t.strip() for t in product_type.split(",")] if product_type else None
        source_ids = [source_id] if source_id else None

        products = self.product_repo.filter_products(
            source_ids=source_ids,
            vendors=vendors,
            product_types=product_types,
            status=status_value,
            price_min=price_min,
            price_max=price_max,
            search_text=search,
            skip=offset,
            limit=limit,
        )
        total = self.product_repo.count_filtered(
            source_ids=source_ids,
            vendors=vendors,
            product_types=product_types,
            status=status_value,
            price_min=price_min,
            price_max=price_max,
            search_text=search,
        )

        all_vendors = self.product_repo.get_distinct_vendors(source_id=source_id)
        all_types = self.product_repo.get_distinct_product_types(source_id=source_id)
        price_range = self.product_repo.get_price_range(source_id=source_id)

        sources = self.source_repo.get_all_active()
        sources_data = [
            {
                "id": s.id,
                "name": s.name,
                "count": self.product_repo.count_by_source(s.id),
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
        assets = self.image_repo.get_by_source_urls(products_image_urls)
        url_to_id = {asset.source_url: asset.id for asset in assets}

        for product in products:
            if product.image_urls:
                product.image_asset_ids = [url_to_id[url] for url in product.image_urls if url in url_to_id]

        return ProductListResponse(
            items=[self._build_product_response(p) for p in products],
            total=total,
            limit=limit,
            offset=offset,
            filters=filters,
        )

    def get_product(self, product_id: int) -> ProductResponse:
        self._require_db()
        product = self.product_repo.get_by_id(product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {product_id} not found",
            )

        assets = self.image_repo.get_by_source_urls(product.image_urls or [])
        by_url = {asset.source_url: asset.id for asset in assets}
        product.image_asset_ids = [by_url[url] for url in (product.image_urls or []) if url in by_url]
        return self._build_product_response(product)

    def add_product_by_url(self, payload: ProductAddByUrlRequest) -> ProductResponse:
        self._require_db()
        preview = self._fetch_preview(payload.url)

        source = self._resolve_or_create_source(preview.product_url)
        existing = self.product_repo.get_by_source_and_handle(source.id, preview.handle)
        price = payload.price if payload.price is not None else self._normalize_preview_price(preview.price, preview.payload_source)
        final_title = payload.title.strip() if payload.title else (preview.title or preview.handle)
        final_vendor = payload.vendor if payload.vendor is not None else preview.vendor
        final_product_type = payload.product_type.strip() if payload.product_type else None
        final_currency = (payload.currency or preview.currency or "USD").upper()
        resolved_image_urls = preview.image_urls or []
        assets = self.image_repo.ensure_assets(resolved_image_urls)
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
            self.db.commit()
            self.db.refresh(existing)
            return self._build_product_response(existing)

        product = self.product_repo.create_product(
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
        self.db.commit()
        self.db.refresh(product)
        return self._build_product_response(product)

    def create_manual_product(self, payload: ProductManualCreateRequest) -> ProductResponse:
        self._require_db()
        source = self.source_repo.get_by_url("https://manual.local")
        if not source:
            source = self.source_repo.create_source(
                name="Manual Upload",
                url="https://manual.local",
                parser_type="custom",
                enabled=True,
            )

        handle_base = self._slugify(payload.title)
        handle = handle_base
        while self.product_repo.get_by_source_and_handle(source.id, handle):
            handle = f"{handle_base}-{int(time.time())}"

        product = self.product_repo.create_product(
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
        self.db.commit()
        self.db.refresh(product)
        return self._build_product_response(product)

    async def upload_product_image(self, file: UploadFile) -> dict:
        if not file.filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Файл не передан")

        extension = Path(file.filename).suffix.lower()
        if extension not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Недопустимый формат изображения")

        self._upload_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = self._slugify(Path(file.filename).stem)
        unique_name = f"{safe_stem}-{int(time.time())}{extension}"
        target = self._upload_dir / unique_name

        content = await file.read()
        if not content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пустой файл")
        target.write_bytes(content)

        return {
            "ok": True,
            "file_name": unique_name,
            "stored_path": str(target),
        }
