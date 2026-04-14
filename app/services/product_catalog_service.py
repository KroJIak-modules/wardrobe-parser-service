"""Service layer for product catalog API operations."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories import ParserImageAssetRepository, ParserProductRepository, ParserSourceRepository
from app.schemas.parser import (
    ProductAddByUrlRequest,
    ProductListResponse,
    ProductManualCreateRequest,
    ProductResponse,
    ProductUrlPreviewResponse,
)
from app.services.product_preview_service import ProductPreviewService
from app.services.product_read_service import ProductReadService
from app.services.product_write_service import ProductWriteService


class ProductCatalogService:
    """Encapsulates business logic used by product catalog endpoints."""

    def __init__(self, db: Optional[Session]):
        self.db = db
        self.product_repo = ParserProductRepository(db) if db is not None else None
        self.source_repo = ParserSourceRepository(db) if db is not None else None
        self.image_repo = ParserImageAssetRepository(db) if db is not None else None
        self.preview_service = ProductPreviewService(source_repo=self.source_repo)
        self.read_service = (
            ProductReadService(
                product_repo=self.product_repo,
                source_repo=self.source_repo,
                image_repo=self.image_repo,
            )
            if (
                self.product_repo is not None
                and self.source_repo is not None
                and self.image_repo is not None
            )
            else None
        )
        self._upload_dir = Path(settings.uploads_dir)
        self.write_service = ProductWriteService(
            db=self.db,
            product_repo=self.product_repo,
            source_repo=self.source_repo,
            image_repo=self.image_repo,
            preview_service=self.preview_service,
            read_service=self.read_service,
            upload_dir=self._upload_dir,
        )

    def _require_db(self) -> None:
        if (
            self.db is None
            or self.product_repo is None
            or self.source_repo is None
            or self.image_repo is None
            or self.read_service is None
            or self.write_service is None
        ):
            raise RuntimeError("Database session is required for this operation")

    def preview_product_by_url(self, payload: ProductAddByUrlRequest) -> ProductUrlPreviewResponse:
        preview = self.preview_service.fetch_preview(payload.url)
        resolved_currency = self.preview_service.require_preview_currency(preview.currency, product_url=preview.product_url)
        return ProductUrlPreviewResponse(
            handle=preview.handle,
            title=preview.title or preview.handle,
            vendor=preview.vendor,
            product_type=preview.product_type,
            product_url=preview.product_url,
            price=self.preview_service.normalize_preview_price(
                preview.price,
                preview.payload_source,
                resolved_currency,
            ),
            currency=resolved_currency,
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
        return self.read_service.list_products(
            source_id=source_id,
            vendor=vendor,
            product_type=product_type,
            status_value=status_value,
            price_min=price_min,
            price_max=price_max,
            search=search,
            limit=limit,
            offset=offset,
        )

    def get_product(self, product_id: int) -> ProductResponse:
        self._require_db()
        return self.read_service.get_product(product_id)

    def add_product_by_url(self, payload: ProductAddByUrlRequest) -> ProductResponse:
        self._require_db()
        return self.write_service.add_product_by_url(payload)

    def create_manual_product(self, payload: ProductManualCreateRequest) -> ProductResponse:
        self._require_db()
        return self.write_service.create_manual_product(payload)

    async def upload_product_image(self, file: UploadFile) -> dict:
        if self.write_service is None:
            raise RuntimeError("Write service is not initialized")
        return await self.write_service.upload_product_image(file)
