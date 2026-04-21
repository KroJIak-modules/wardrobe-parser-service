"""Repository for parser sources."""

from typing import Optional, List
from sqlalchemy.orm import Session

from app.models import ParserSource
from app.repositories.base import BaseRepository


class ParserSourceRepository(BaseRepository[ParserSource]):
    """Repository for ParserSource (Shopify stores, etc.)."""

    def __init__(self, session: Session):
        super().__init__(session, ParserSource)

    def get_by_url(self, url: str) -> Optional[ParserSource]:
        """Get source by URL."""
        return (
            self.query()
            .filter(ParserSource.url == url)
            .filter(ParserSource.deleted_at.is_(None))
            .first()
        )

    def get_all_active(self) -> List[ParserSource]:
        """Get all active (not deleted) sources."""
        return (
            self.query()
            .filter(ParserSource.deleted_at.is_(None))
            .all()
        )

    def create_source(
        self,
        name: str,
        url: str,
        parser_type: str = "shopify",
        enabled: bool = True,
        sync_enabled: bool = True,
        hide_auto_added_products: bool = False,
        supplier_id: Optional[int] = None,
        promo_factor: Optional[float] = None,
        promo_only_no_discount: Optional[bool] = None,
        buyout_surcharge_value: Optional[float] = None,
        buyout_surcharge_currency: Optional[str] = None,
        config: Optional[str] = None,
    ) -> ParserSource:
        """Create new source."""
        payload = dict(
            name=name,
            url=url,
            parser_type=parser_type,
            enabled=enabled,
            sync_enabled=sync_enabled,
            hide_auto_added_products=hide_auto_added_products,
            config=config,
        )
        if supplier_id is not None:
            payload["supplier_id"] = supplier_id
        if promo_factor is not None:
            payload["promo_factor"] = promo_factor
        if promo_only_no_discount is not None:
            payload["promo_only_no_discount"] = promo_only_no_discount
        if buyout_surcharge_value is not None:
            payload["buyout_surcharge_value"] = buyout_surcharge_value
        if buyout_surcharge_currency is not None:
            payload["buyout_surcharge_currency"] = buyout_surcharge_currency
        source = self.create(**payload)
        self.flush()
        return source

    def count_by_supplier_id(self, supplier_id: int) -> int:
        return (
            self.query()
            .filter(ParserSource.supplier_id == supplier_id)
            .filter(ParserSource.deleted_at.is_(None))
            .count()
        )
