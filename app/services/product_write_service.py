"""Write-side operations for product catalog endpoints."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ProductStatus
from app.repositories import ParserImageAssetRepository, ParserProductRepository, ParserSourceRepository
from app.schemas.parser import ProductAddByUrlRequest, ProductManualCreateRequest, ProductResponse
from app.services.product_preview_service import ProductPreviewService
from app.services.product_read_service import ProductReadService
from app.services.product_status_service import resolve_product_status
from app.services.settings.weight_rule_service import WeightRuleService


class ProductWriteService:
    """Encapsulates product write flows (upsert/manual/upload)."""

    def __init__(
        self,
        db: Optional[Session],
        product_repo: Optional[ParserProductRepository],
        source_repo: Optional[ParserSourceRepository],
        image_repo: Optional[ParserImageAssetRepository],
        preview_service: ProductPreviewService,
        read_service: Optional[ProductReadService],
        upload_dir: Path,
    ):
        self.db = db
        self.product_repo = product_repo
        self.source_repo = source_repo
        self.image_repo = image_repo
        self.preview_service = preview_service
        self.read_service = read_service
        self.upload_dir = upload_dir

    def _require_db_dependencies(self) -> None:
        if (
            self.db is None
            or self.product_repo is None
            or self.source_repo is None
            or self.image_repo is None
            or self.read_service is None
        ):
            raise RuntimeError("Database dependencies are required for this operation")

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "product"

    def add_product_by_url(self, payload: ProductAddByUrlRequest) -> ProductResponse:
        self._require_db_dependencies()
        preview = self.preview_service.fetch_preview(payload.url)
        resolved_currency = self.preview_service.require_preview_currency(preview.currency, product_url=preview.product_url)

        source = self.preview_service.resolve_or_create_source(preview.product_url)
        existing = self.product_repo.get_by_source_and_handle(source.id, preview.handle)
        price = payload.price if payload.price is not None else self.preview_service.normalize_preview_price(
            preview.price,
            preview.payload_source,
            resolved_currency,
        )
        variants = self.preview_service.normalize_preview_variants(
            preview.variants,
            preview.payload_source,
            resolved_currency,
        )
        resolved_status = resolve_product_status(
            variants=variants,
            preview_available=preview.available,
            existing_status=getattr(existing, "status", None),
        )
        final_title = payload.title.strip() if payload.title else (preview.title or preview.handle)
        final_vendor = payload.vendor if payload.vendor is not None else preview.vendor
        final_product_type = payload.product_type.strip() if payload.product_type else None
        final_currency = (payload.currency or resolved_currency).upper()
        resolved_image_urls = preview.image_urls or []
        assets = self.image_repo.ensure_assets(resolved_image_urls)
        resolved_image_asset_ids = [asset.id for asset in assets]
        final_image_count = payload.image_count if payload.image_count is not None else len(resolved_image_urls)
        final_weight_grams = preview.weight_grams
        final_weight_source = preview.weight_source or ("missing" if preview.weight_grams is None else "source")
        final_weight_match_keyword = preview.weight_match_keyword
        final_weight_value = preview.weight_value
        final_weight_unit = preview.weight_unit
        if final_weight_grams is None:
            matched = WeightRuleService(self.db).match_weight_by_keywords(
                title=final_title,
                vendor=final_vendor,
                product_type=final_product_type,
                handle=preview.handle,
            )
            if matched.weight_grams is not None:
                final_weight_grams = matched.weight_grams
                final_weight_source = "keyword"
                final_weight_match_keyword = matched.matched_keyword
                final_weight_value = matched.weight_grams
                final_weight_unit = "g"

        if existing:
            existing.title = final_title or existing.title
            existing.description = preview.description
            existing.vendor = final_vendor
            existing.product_type = final_product_type
            existing.url = preview.product_url
            existing.price = price
            existing.currency = final_currency or existing.currency
            if final_image_count is not None:
                existing.image_count = final_image_count
            existing.image_urls = resolved_image_urls
            existing.image_asset_ids = resolved_image_asset_ids
            existing.variants = variants
            existing.status = resolved_status
            existing.weight_grams = final_weight_grams
            existing.weight_source = final_weight_source
            existing.weight_match_keyword = final_weight_match_keyword
            existing.weight_value = final_weight_value
            existing.weight_unit = final_weight_unit
            existing.deleted_at = None
            self.db.commit()
            self.db.refresh(existing)
            return self.read_service.build_product_response(existing, source_profile=source)

        product = self.product_repo.create_product(
            source_id=source.id,
            handle=preview.handle,
            title=final_title,
            description=preview.description,
            vendor=final_vendor,
            product_type=final_product_type,
            url=preview.product_url,
            price=price,
            currency=final_currency,
            image_count=final_image_count or 0,
            image_urls=resolved_image_urls,
            image_asset_ids=resolved_image_asset_ids,
            variants=variants,
            weight_grams=final_weight_grams,
            weight_source=final_weight_source,
            weight_match_keyword=final_weight_match_keyword,
            weight_value=final_weight_value,
            weight_unit=final_weight_unit,
            status=resolved_status,
        )
        self.db.commit()
        self.db.refresh(product)
        return self.read_service.build_product_response(product, source_profile=source)

    def create_manual_product(self, payload: ProductManualCreateRequest) -> ProductResponse:
        self._require_db_dependencies()
        source = self.source_repo.get_by_url(settings.manual_source_url)
        if not source:
            source = self.source_repo.create_source(
                name=settings.manual_source_name,
                url=settings.manual_source_url,
                parser_type=settings.manual_source_parser_type,
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
            vendor=(payload.vendor or settings.manual_product_vendor_default),
            product_type=payload.product_type,
            url=f"{settings.manual_source_url.rstrip('/')}/products/{handle}",
            price=payload.price,
            currency=payload.currency.upper(),
            image_count=payload.image_count,
            weight_source="missing",
            status=ProductStatus.AVAILABLE,
        )
        self.db.commit()
        self.db.refresh(product)
        return self.read_service.build_product_response(product, source_profile=source)

    async def upload_product_image(self, file: UploadFile) -> dict:
        if not file.filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Файл не передан")

        extension = Path(file.filename).suffix.lower()
        allowed_extensions = {
            item.strip().lower()
            for item in settings.uploads_allowed_extensions.split(",")
            if item.strip()
        }
        if extension not in allowed_extensions:
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
