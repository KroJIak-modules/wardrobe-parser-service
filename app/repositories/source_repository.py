"""
ParserSource and fingerprint repositories.
"""

from typing import Optional, List
from sqlalchemy.orm import Session

from app.models import ParserSource, ParserProductFingerprint
from app.repositories.base import BaseRepository


class ParserSourceRepository(BaseRepository[ParserSource]):
    """Repository for ParserSource (Shopify stores, etc.)."""

    def __init__(self, session: Session):
        super().__init__(session, ParserSource)

    def get_by_name(self, name: str) -> Optional[ParserSource]:
        """Get source by name."""
        return (
            self.query()
            .filter(ParserSource.name == name)
            .filter(ParserSource.deleted_at.is_(None))
            .first()
        )

    def get_by_url(self, url: str) -> Optional[ParserSource]:
        """Get source by URL."""
        return (
            self.query()
            .filter(ParserSource.url == url)
            .filter(ParserSource.deleted_at.is_(None))
            .first()
        )

    def get_enabled(self, skip: int = 0, limit: int = 100) -> List[ParserSource]:
        """Get all enabled sources."""
        return (
            self.query()
            .filter(ParserSource.enabled == True)
            .filter(ParserSource.deleted_at.is_(None))
            .offset(skip)
            .limit(limit)
            .all()
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
        supplier_id: Optional[int] = None,
        seller_delivery_rub: Optional[float] = None,
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
            config=config,
        )
        if supplier_id is not None:
            payload["supplier_id"] = supplier_id
        if seller_delivery_rub is not None:
            payload["seller_delivery_rub"] = seller_delivery_rub
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


class ParserProductFingerprintRepository(BaseRepository[ParserProductFingerprint]):
    """Repository for product fingerprints (SHA256 hashes)."""

    def __init__(self, session: Session):
        super().__init__(session, ParserProductFingerprint)

    def get_by_product_id(self, product_id: int) -> Optional[ParserProductFingerprint]:
        """Get fingerprint for product."""
        return (
            self.query()
            .filter(ParserProductFingerprint.product_id == product_id)
            .filter(ParserProductFingerprint.deleted_at.is_(None))
            .first()
        )

    def create_fingerprint(
        self, source_id: int, product_id: int, fingerprint: str
    ) -> ParserProductFingerprint:
        """Create new fingerprint."""
        fp = self.create(
            source_id=source_id,
            product_id=product_id,
            fingerprint=fingerprint,
        )
        self.flush()
        return fp

    def update_fingerprint(
        self, product_id: int, new_fingerprint: str
    ) -> bool:
        """Update fingerprint for product."""
        fp = self.get_by_product_id(product_id)
        if fp:
            fp.fingerprint = new_fingerprint
            return True
        return False

    def get_fingerprints_for_source(
        self, source_id: int
    ) -> List[ParserProductFingerprint]:
        """Get all fingerprints for source."""
        return (
            self.query()
            .filter(ParserProductFingerprint.source_id == source_id)
            .filter(ParserProductFingerprint.deleted_at.is_(None))
            .all()
        )
