"""Read-side operations for product catalog endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status

from app.models import ProductStatus
from app.repositories import ParserImageAssetRepository, ParserProductRepository, ParserSourceRepository
from app.schemas.parser import ProductListResponse, ProductResponse


class ProductReadService:
    """Encapsulates read flows for product list/details and response mapping."""

    def __init__(
        self,
        product_repo: ParserProductRepository,
        source_repo: ParserSourceRepository,
        image_repo: ParserImageAssetRepository,
    ):
        self.product_repo = product_repo
        self.source_repo = source_repo
        self.image_repo = image_repo

    def build_product_response(self, product, *, source_profile=None) -> ProductResponse:
        _ = source_profile
        image_urls = product.image_urls or []
        image_ids = product.image_asset_ids or []
        variants = product.variants or []
        return ProductResponse(
            id=product.id,
            source_id=product.source_id,
            handle=product.handle,
            title=product.title,
            description=product.description,
            vendor=product.vendor,
            product_type=product.product_type,
            url=product.url,
            price=product.price,
            currency=product.currency,
            source_price=product.price,
            source_currency=product.currency,
            final_price=None,
            final_currency=None,
            pricing_manual_required=False,
            pricing_reason=None,
            pricing_components={},
            status=product.status,
            image_count=product.image_count,
            image_urls=image_urls,
            image_ids=image_ids,
            weight_grams=product.weight_grams,
            weight_source=product.weight_source,
            weight_match_keyword=product.weight_match_keyword,
            weight_value=product.weight_value,
            weight_unit=product.weight_unit,
            variants=variants,
            created_at=product.created_at,
            updated_at=product.updated_at,
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
        vendors = [v.strip() for v in vendor.split(",")] if vendor else None
        product_types = [t.strip() for t in product_type.split(",")] if product_type else None
        source_ids = [source_id] if source_id else None

        normalized_status = None
        if status_value:
            raw_status = str(status_value).strip().lower()
            if raw_status not in {ProductStatus.AVAILABLE, ProductStatus.OUT_OF_STOCK, ProductStatus.HIDDEN}:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Допустимые статусы: available, out_of_stock, hidden",
                )
            normalized_status = raw_status

        products = self.product_repo.filter_products(
            source_ids=source_ids,
            vendors=vendors,
            product_types=product_types,
            status=normalized_status,
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
            status=normalized_status,
            price_min=price_min,
            price_max=price_max,
            search_text=search,
        )

        all_vendors = self.product_repo.get_distinct_vendors(source_id=source_id)
        all_types = self.product_repo.get_distinct_product_types(source_id=source_id)
        price_range = self.product_repo.get_price_range(source_id=source_id)

        sources = self.source_repo.get_all_active()
        source_profile_map = {int(s.id): s for s in sources}
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
                {"name": ProductStatus.HIDDEN, "label": "Hidden"},
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
            items=[
                self.build_product_response(
                    p,
                    source_profile=source_profile_map.get(int(p.source_id)),
                )
                for p in products
            ],
            total=total,
            limit=limit,
            offset=offset,
            filters=filters,
        )

    def get_product(self, product_id: int) -> ProductResponse:
        product = self.product_repo.get_by_id(product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {product_id} not found",
            )

        assets = self.image_repo.get_by_source_urls(product.image_urls or [])
        by_url = {asset.source_url: asset.id for asset in assets}
        product.image_asset_ids = [by_url[url] for url in (product.image_urls or []) if url in by_url]
        source = self.source_repo.get_by_id(product.source_id)
        return self.build_product_response(product, source_profile=source)
