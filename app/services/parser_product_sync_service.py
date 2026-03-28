"""Product upsert/batch-sync helpers for parser jobs."""

from __future__ import annotations

from app.models import ProductStatus
from app.repositories import ParserImageAssetRepository, ParserProductRepository


class ParserProductSyncService:
    """Encapsulates per-source product synchronization logic."""

    def __init__(self, product_repo: ParserProductRepository, image_repo: ParserImageAssetRepository):
        self.product_repo = product_repo
        self.image_repo = image_repo

    @staticmethod
    def _to_float(value: str | None) -> float | None:
        if value is None:
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    def upsert_product_from_preview(self, source_id: int, preview) -> tuple[int, int]:
        existing = self.product_repo.get_by_source_and_handle(source_id, preview.handle)
        parsed_price = self._to_float(preview.price)
        preview_image_urls = preview.image_urls or []
        assets = self.image_repo.ensure_assets(preview_image_urls)
        preview_image_asset_ids = [asset.id for asset in assets]

        if existing is None:
            self.product_repo.create_product(
                source_id=source_id,
                handle=preview.handle,
                title=preview.title or preview.handle,
                url=preview.product_url,
                vendor=preview.vendor,
                product_type=preview.product_type,
                price=parsed_price,
                currency=preview.currency or "USD",
                image_count=len(preview_image_urls),
                image_urls=preview_image_urls,
                image_asset_ids=preview_image_asset_ids,
                status=ProductStatus.AVAILABLE,
            )
            return 1, 0

        changed = (
            existing.title != (preview.title or preview.handle)
            or existing.url != preview.product_url
            or existing.vendor != preview.vendor
            or existing.product_type != preview.product_type
            or existing.price != parsed_price
            or existing.currency != (preview.currency or "USD")
            or (existing.image_urls or []) != preview_image_urls
            or (existing.image_asset_ids or []) != preview_image_asset_ids
            or existing.image_count != len(preview_image_urls)
            or existing.status != ProductStatus.AVAILABLE
        )
        if not changed:
            return 0, 0

        self.product_repo.update(
            existing,
            title=preview.title or preview.handle,
            url=preview.product_url,
            vendor=preview.vendor,
            product_type=preview.product_type,
            price=parsed_price,
            currency=preview.currency or "USD",
            image_count=len(preview_image_urls),
            image_urls=preview_image_urls,
            image_asset_ids=preview_image_asset_ids,
            status=ProductStatus.AVAILABLE,
            deleted_at=None,
        )
        return 0, 1

    def sync_source_products(self, source_id: int, previews: list) -> tuple[int, int]:
        created_for_source = 0
        updated_for_source = 0
        for preview in previews:
            created_delta, updated_delta = self.upsert_product_from_preview(source_id, preview)
            created_for_source += created_delta
            updated_for_source += updated_delta
        return created_for_source, updated_for_source
