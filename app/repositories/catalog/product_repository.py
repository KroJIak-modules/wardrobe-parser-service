"""ParserProduct repository for product catalog queries."""

from typing import Any, Optional, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import ParserProduct, ProductStatus
from app.repositories.base import BaseRepository
from app.repositories.catalog.product_filters import build_filtered_query


_NO_BRAND_FILTER = "__NO_BRAND__"


class ParserProductRepository(BaseRepository[ParserProduct]):
    """Repository for ParserProduct entity with advanced filtering."""

    def __init__(self, session: Session):
        super().__init__(session, ParserProduct)

    def create_product(
        self,
        source_id: int,
        handle: str,
        title: str,
        url: str,
        vendor: Optional[str] = None,
        product_type: Optional[str] = None,
        price: Optional[float] = None,
        currency: str = "USD",
        image_count: int = 0,
        image_urls: Optional[List[str]] = None,
        image_asset_ids: Optional[List[int]] = None,
        variants: Optional[List[dict[str, Any]]] = None,
        weight_grams: Optional[float] = None,
        weight_source: Optional[str] = None,
        weight_match_keyword: Optional[str] = None,
        weight_value: Optional[float] = None,
        weight_unit: Optional[str] = None,
        status: str = ProductStatus.AVAILABLE,
    ) -> ParserProduct:
        """Create new product."""
        product = self.create(
            source_id=source_id,
            handle=handle,
            title=title,
            url=url,
            vendor=vendor,
            product_type=product_type,
            price=price,
            currency=currency,
            image_count=image_count,
            image_urls=image_urls or [],
            image_asset_ids=image_asset_ids or [],
            variants=variants or [],
            weight_grams=weight_grams,
            weight_source=weight_source,
            weight_match_keyword=weight_match_keyword,
            weight_value=weight_value,
            weight_unit=weight_unit,
            status=status,
        )
        self.flush()
        return product

    def get_by_url(self, url: str) -> Optional[ParserProduct]:
        """Get product by URL."""
        return self.query().filter(ParserProduct.url == url).first()

    def get_by_source_and_handle(
        self, source_id: int, handle: str
    ) -> Optional[ParserProduct]:
        """Get product by source and handle."""
        return (
            self.query()
            .filter(ParserProduct.source_id == source_id)
            .filter(ParserProduct.handle == handle)
            .filter(ParserProduct.deleted_at.is_(None))
            .first()
        )

    def get_by_source(
        self,
        source_id: int,
        skip: int = 0,
        limit: int = 100,
        active_only: bool = True,
    ) -> List[ParserProduct]:
        """Get all products for source."""
        q = self.query().filter(ParserProduct.source_id == source_id)
        if active_only:
            q = q.filter(ParserProduct.deleted_at.is_(None))
        return q.offset(skip).limit(limit).all()

    def count_by_source(self, source_id: int, active_only: bool = True) -> int:
        """Count products for source."""
        q = self.query().filter(ParserProduct.source_id == source_id)
        if active_only:
            q = q.filter(ParserProduct.deleted_at.is_(None))
        return q.count()

    def filter_products(
        self,
        source_ids: Optional[List[int]] = None,
        vendors: Optional[List[str]] = None,
        product_types: Optional[List[str]] = None,
        status: Optional[str] = None,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        search_text: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[ParserProduct]:
        """Advanced filtering for product lists."""
        q = build_filtered_query(
            self.query(),
            source_ids=source_ids,
            vendors=vendors,
            product_types=product_types,
            status=status,
            price_min=price_min,
            price_max=price_max,
            search_text=search_text,
            no_brand_filter=_NO_BRAND_FILTER,
        )

        return q.offset(skip).limit(limit).all()

    def count_filtered(
        self,
        source_ids: Optional[List[int]] = None,
        vendors: Optional[List[str]] = None,
        product_types: Optional[List[str]] = None,
        status: Optional[str] = None,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        search_text: Optional[str] = None,
    ) -> int:
        """Count products matching filters (without pagination)."""
        q = build_filtered_query(
            self.query(),
            source_ids=source_ids,
            vendors=vendors,
            product_types=product_types,
            status=status,
            price_min=price_min,
            price_max=price_max,
            search_text=search_text,
            no_brand_filter=_NO_BRAND_FILTER,
        )

        return q.count()

    def get_distinct_vendors(self, source_id: Optional[int] = None) -> List[str]:
        """Get list of distinct vendors."""
        q = self.session.query(
            ParserProduct.vendor
        ).filter(ParserProduct.deleted_at.is_(None))

        if source_id:
            q = q.filter(ParserProduct.source_id == source_id)

        return [v[0] for v in q.distinct().all() if v[0]]

    def get_distinct_product_types(
        self, source_id: Optional[int] = None
    ) -> List[str]:
        """Get list of distinct product types."""
        q = self.session.query(
            ParserProduct.product_type
        ).filter(ParserProduct.deleted_at.is_(None))

        if source_id:
            q = q.filter(ParserProduct.source_id == source_id)

        return [t[0] for t in q.distinct().all() if t[0]]

    def get_price_range(self, source_id: Optional[int] = None) -> Dict:
        """Get min/max price for products."""
        q = self.session.query(
            func.min(ParserProduct.price).label("min_price"),
            func.max(ParserProduct.price).label("max_price"),
        ).filter(ParserProduct.deleted_at.is_(None))

        if source_id:
            q = q.filter(ParserProduct.source_id == source_id)

        result = q.first()
        return {
            "min_price": result[0] if result else None,
            "max_price": result[1] if result else None,
        }

    def get_by_ids(self, product_ids: List[int]) -> List[ParserProduct]:
        """Get multiple products by IDs."""
        return (
            self.query()
            .filter(ParserProduct.id.in_(product_ids))
            .filter(ParserProduct.deleted_at.is_(None))
            .all()
        )
