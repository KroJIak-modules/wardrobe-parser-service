"""Product upsert/batch-sync helpers for parser jobs."""

from __future__ import annotations

from typing import Any
from typing import Callable, Optional

from app.models import ProductStatus
from app.repositories import ParserImageAssetRepository, ParserProductRepository


class ParserProductSyncService:
    """Encapsulates per-source product synchronization logic."""

    IMAGE_ASSET_BATCH_SIZE = 500

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

    def _upsert_product_from_preview(
        self,
        *,
        source_id: int,
        preview,
        existing_by_handle: dict[str, Any],
        existing_by_url: dict[str, Any],
        image_asset_cache: dict[str, Any],
    ) -> tuple[int, int]:
        existing = existing_by_handle.get(preview.handle)
        if existing is None:
            existing = existing_by_url.get(preview.product_url)

        parsed_price = self._to_float(preview.price)
        preview_image_urls = preview.image_urls or []
        assets = [image_asset_cache[url] for url in preview_image_urls if url in image_asset_cache]
        preview_image_asset_ids = [asset.id for asset in assets]
        preview_variants = preview.variants or []
        status = ProductStatus.AVAILABLE if preview.available else ProductStatus.OUT_OF_STOCK

        if existing is None:
            created = self.product_repo.create_product(
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
                variants=preview_variants,
                status=status,
            )
            existing_by_handle[created.handle] = created
            existing_by_url[created.url] = created
            return 1, 0

        changed = (
            existing.source_id != source_id
            or existing.handle != preview.handle
            or existing.title != (preview.title or preview.handle)
            or existing.url != preview.product_url
            or existing.vendor != preview.vendor
            or existing.product_type != preview.product_type
            or existing.price != parsed_price
            or existing.currency != (preview.currency or "USD")
            or (existing.image_urls or []) != preview_image_urls
            or (existing.image_asset_ids or []) != preview_image_asset_ids
            or existing.image_count != len(preview_image_urls)
            or (existing.variants or []) != preview_variants
            or existing.status != status
        )
        if not changed:
            existing_by_handle[existing.handle] = existing
            existing_by_url[existing.url] = existing
            return 0, 0

        self.product_repo.update(
            existing,
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
            variants=preview_variants,
            status=status,
            deleted_at=None,
        )
        existing_by_handle[existing.handle] = existing
        existing_by_url[existing.url] = existing
        return 0, 1

    def _prepare_image_asset_cache(self, previews: list) -> dict[str, Any]:
        """Preload image assets for the whole source in DB-friendly batches."""
        all_urls = list(
            dict.fromkeys(
                url
                for preview in previews
                for url in (preview.image_urls or [])
                if url
            )
        )
        if not all_urls:
            return {}

        asset_cache: dict[str, Any] = {}
        for start in range(0, len(all_urls), self.IMAGE_ASSET_BATCH_SIZE):
            batch_urls = all_urls[start : start + self.IMAGE_ASSET_BATCH_SIZE]
            for asset in self.image_repo.ensure_assets(batch_urls):
                asset_cache[asset.source_url] = asset
        return asset_cache

    def sync_source_products(
        self,
        source_id: int,
        previews: list,
        on_product_processed: Optional[Callable[[str | None, int, int], None]] = None,
    ) -> tuple[int, int]:
        existing_products = self.product_repo.get_by_source(
            source_id,
            skip=0,
            limit=100000,
            active_only=True,
        )
        existing_by_handle = {product.handle: product for product in existing_products if product.handle}
        existing_by_url = {product.url: product for product in existing_products if product.url}
        image_asset_cache = self._prepare_image_asset_cache(previews)
        created_for_source = 0
        updated_for_source = 0
        total_previews = len(previews)
        for index, preview in enumerate(previews, start=1):
            created_delta, updated_delta = self._upsert_product_from_preview(
                source_id=source_id,
                preview=preview,
                existing_by_handle=existing_by_handle,
                existing_by_url=existing_by_url,
                image_asset_cache=image_asset_cache,
            )
            created_for_source += created_delta
            updated_for_source += updated_delta
            if on_product_processed:
                on_product_processed(preview.title, index, total_previews)
        return created_for_source, updated_for_source
