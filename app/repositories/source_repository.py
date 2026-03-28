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
        config: Optional[str] = None,
    ) -> ParserSource:
        """Create new source."""
        source = self.create(
            name=name,
            url=url,
            parser_type=parser_type,
            enabled=enabled,
            config=config,
        )
        self.flush()
        return source


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
