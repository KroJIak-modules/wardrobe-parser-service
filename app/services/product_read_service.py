"""Read-side operations for product catalog endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status

from app.models import ProductStatus
from app.repositories import ParserImageAssetRepository, ParserProductRepository, ParserSourceRepository
from app.schemas.parser import ProductListResponse, ProductResponse
from app.services.settings.pricing_service import PricingSettingsService


class ProductReadService:
    """Encapsulates read flows for product list/details and response mapping."""

    def __init__(
        self,
        product_repo: ParserProductRepository,
        source_repo: ParserSourceRepository,
        image_repo: ParserImageAssetRepository,
        pricing_settings_service: PricingSettingsService,
    ):
        self.product_repo = product_repo
        self.source_repo = source_repo
        self.image_repo = image_repo
        self.pricing_settings_service = pricing_settings_service

    def build_product_response(self, product, *, pricing_settings=None, source_profile=None) -> ProductResponse:
        settings = pricing_settings or self.pricing_settings_service.get_settings()
        source_supplier_id = int(source_profile.supplier_id) if source_profile and source_profile.supplier_id is not None else None
        source_seller_delivery_rub = (
            float(source_profile.seller_delivery_rub)
            if source_profile is not None and getattr(source_profile, "seller_delivery_rub", None) is not None
            else None
        )
        source_promo_factor = (
            float(source_profile.promo_factor)
            if source_profile is not None and getattr(source_profile, "promo_factor", None) is not None
            else None
        )
        source_promo_only_no_discount = (
            bool(source_profile.promo_only_no_discount)
            if source_profile is not None and getattr(source_profile, "promo_only_no_discount", None) is not None
            else None
        )
        source_buyout_surcharge_value = (
            float(source_profile.buyout_surcharge_value)
            if source_profile is not None and getattr(source_profile, "buyout_surcharge_value", None) is not None
            else None
        )
        source_buyout_surcharge_currency = (
            str(source_profile.buyout_surcharge_currency)
            if source_profile is not None and getattr(source_profile, "buyout_surcharge_currency", None) is not None
            else None
        )
        pricing = self.pricing_settings_service.calculate_for_product(
            source_price=product.price,
            source_currency=product.currency,
            weight_grams=product.weight_grams,
            supplier_id=source_supplier_id,
            seller_delivery_rub=source_seller_delivery_rub,
            promo_factor=source_promo_factor,
            promo_only_no_discount=source_promo_only_no_discount,
            buyout_surcharge_value=source_buyout_surcharge_value,
            buyout_surcharge_currency=source_buyout_surcharge_currency,
            variants=product.variants or [],
            settings=settings,
        )
        image_urls = product.image_urls or []
        image_ids = product.image_asset_ids or []
        variants = product.variants or []
        display_price = pricing.final_price_rub if pricing.final_price_rub is not None else product.price
        display_currency = "RUB" if pricing.final_price_rub is not None else product.currency
        return ProductResponse(
            id=product.id,
            source_id=product.source_id,
            handle=product.handle,
            title=product.title,
            vendor=product.vendor,
            product_type=product.product_type,
            url=product.url,
            price=display_price,
            currency=display_currency,
            source_price=product.price,
            source_currency=product.currency,
            final_price=pricing.final_price_rub,
            final_currency="RUB",
            pricing_manual_required=pricing.manual_required,
            pricing_reason=pricing.reason,
            pricing_components=pricing.components,
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
        pricing_settings = self.pricing_settings_service.get_settings()
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
            items=[
                self.build_product_response(
                    p,
                    pricing_settings=pricing_settings,
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
        pricing_settings = self.pricing_settings_service.get_settings()
        source = self.source_repo.get_by_id(product.source_id)
        return self.build_product_response(product, pricing_settings=pricing_settings, source_profile=source)
