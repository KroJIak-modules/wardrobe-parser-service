"""Service layer for image gateway and backfill operations."""

from __future__ import annotations

from pathlib import Path
from fastapi import HTTPException, Request, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ParserProduct
from app.repositories import ParserImageAssetRepository
from app.services.media.image_proxy import build_etag, cache_headers, fetch_image_bytes
from app.services.media.image_security import check_rate_limit, ensure_allowed_url


class ImageGatewayService:
    """Encapsulates image gateway security and backfill logic."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = ParserImageAssetRepository(db)

    def get_image(self, image_id: int, request: Request) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        check_rate_limit(client_ip, per_minute_limit=settings.image_rate_limit_per_minute)

        asset = self.repo.get_by_id(image_id)
        if not asset or asset.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Изображение не найдено")

        etag = build_etag(asset.id, asset.created_at, asset.source_url)
        headers = cache_headers(
            etag=etag,
            created_at=asset.created_at,
            max_age_sec=settings.image_cache_max_age_sec,
        )
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

        if asset.storage_mode == "stored_file" and asset.stored_path:
            candidate = Path(asset.stored_path)
            if candidate.exists() and candidate.is_file():
                return FileResponse(candidate, headers=headers)

        if not asset.source_url:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник изображения отсутствует")

        normalized_source_url = ensure_allowed_url(asset.source_url)

        body, media_type = fetch_image_bytes(
            source_url=normalized_source_url,
            timeout_sec=settings.image_proxy_timeout_sec,
            max_bytes=settings.image_proxy_max_bytes,
        )
        return Response(content=body, media_type=media_type, headers=headers)

    def backfill_image_assets(self) -> dict:
        products = (
            self.db.query(ParserProduct)
            .filter(ParserProduct.deleted_at.is_(None))
            .all()
        )

        updated = 0
        for product in products:
            urls = product.image_urls or []
            if not urls:
                continue
            assets = self.repo.ensure_assets(urls)
            mapped_ids = [asset.id for asset in assets]
            if (product.image_asset_ids or []) != mapped_ids:
                product.image_asset_ids = mapped_ids
                product.image_count = len(urls)
                updated += 1

        self.db.commit()
        return {"ok": True, "updated_products": updated}
