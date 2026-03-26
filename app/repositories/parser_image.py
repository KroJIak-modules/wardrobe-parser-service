"""Repository for image assets."""

from typing import Iterable

from sqlalchemy.orm import Session

from app.models import ImageAsset
from app.repositories.base import BaseRepository


class ParserImageAssetRepository(BaseRepository[ImageAsset]):
    """Repository for image assets used by image gateway endpoint."""

    def __init__(self, session: Session):
        super().__init__(session, ImageAsset)

    def get_by_source_url(self, source_url: str) -> ImageAsset | None:
        return (
            self.query()
            .filter(ImageAsset.deleted_at.is_(None))
            .filter(ImageAsset.source_url == source_url)
            .first()
        )

    def get_by_source_urls(self, source_urls: Iterable[str]) -> list[ImageAsset]:
        urls = [item for item in source_urls if item]
        if not urls:
            return []
        return (
            self.query()
            .filter(ImageAsset.deleted_at.is_(None))
            .filter(ImageAsset.source_url.in_(urls))
            .all()
        )

    def ensure_assets(self, source_urls: list[str]) -> list[ImageAsset]:
        """Ensure image assets exist and return them in source_urls order."""
        normalized = [item.strip() for item in source_urls if item and item.strip()]
        if not normalized:
            return []

        existing = self.get_by_source_urls(normalized)
        by_url = {item.source_url: item for item in existing}

        for url in normalized:
            if url in by_url:
                continue
            created = self.create(
                source_url=url,
                storage_mode="proxy",
            )
            self.flush()
            by_url[url] = created

        ordered: list[ImageAsset] = []
        for url in normalized:
            asset = by_url.get(url)
            if asset:
                ordered.append(asset)
        return ordered
