"""Write-side operations for product catalog endpoints."""

from __future__ import annotations

import re
import time
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.models import ProductStatus
from app.repositories import ParserImageAssetRepository, ParserProductRepository, ParserSourceRepository
from app.schemas.parser import ProductAddByUrlRequest, ProductManualCreateRequest, ProductResponse
from app.services.product_preview_service import ProductPreviewService
from app.services.product_read_service import ProductReadService


class ProductWriteService:
    """Encapsulates product write flows (upsert/manual/upload)."""

    def __init__(
        self,
        db: Session,
        product_repo: ParserProductRepository,
        source_repo: ParserSourceRepository,
        image_repo: ParserImageAssetRepository,
        preview_service: ProductPreviewService,
        read_service: ProductReadService,
        upload_dir: Path,
    ):
        self.db = db
        self.product_repo = product_repo
        self.source_repo = source_repo
        self.image_repo = image_repo
        self.preview_service = preview_service
        self.read_service = read_service
        self.upload_dir = upload_dir

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "product"

    def add_product_by_url(self, payload: ProductAddByUrlRequest) -> ProductResponse:
        preview = self.preview_service.fetch_preview(payload.url)

        source = self.preview_service.resolve_or_create_source(preview.product_url)
        existing = self.product_repo.get_by_source_and_handle(source.id, preview.handle)
        price = payload.price if payload.price is not None else self.preview_service.normalize_preview_price(
            preview.price,
            preview.payload_source,
        )
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
            return self.read_service.build_product_response(existing)

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
        return self.read_service.build_product_response(product)

    def create_manual_product(self, payload: ProductManualCreateRequest) -> ProductResponse:
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
        return self.read_service.build_product_response(product)

    async def upload_product_image(self, file: UploadFile) -> dict:
        if not file.filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Файл не передан")

        extension = Path(file.filename).suffix.lower()
        if extension not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Недопустимый формат изображения")

        self.upload_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = self._slugify(Path(file.filename).stem)
        unique_name = f"{safe_stem}-{int(time.time())}{extension}"
        target = self.upload_dir / unique_name

        content = await file.read()
        if not content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пустой файл")
        target.write_bytes(content)

        return {
            "ok": True,
            "file_name": unique_name,
            "stored_path": str(target),
        }
