"""Repositories for category tree and keyword rules."""

from typing import Optional

from sqlalchemy.orm import Session

from app.models import ParserCategory, ParserCategoryKeyword
from app.repositories.base import BaseRepository


class ParserCategoryRepository(BaseRepository[ParserCategory]):
    """Repository for parser categories."""

    def __init__(self, session: Session):
        super().__init__(session, ParserCategory)

    def get_all_active(self) -> list[ParserCategory]:
        return (
            self.query()
            .filter(ParserCategory.deleted_at.is_(None))
            # Keep explicit UI/menu order stable by creation order inside each parent.
            .order_by(ParserCategory.parent_id.asc().nullsfirst(), ParserCategory.id.asc())
            .all()
        )

    def get_fallback(self) -> Optional[ParserCategory]:
        return (
            self.query()
            .filter(ParserCategory.deleted_at.is_(None))
            .filter(ParserCategory.is_fallback == True)
            .first()
        )

    def get_by_slug(self, slug: str) -> Optional[ParserCategory]:
        return (
            self.query()
            .filter(ParserCategory.deleted_at.is_(None))
            .filter(ParserCategory.slug == slug)
            .first()
        )

    def get_children(self, parent_id: int) -> list[ParserCategory]:
        return (
            self.query()
            .filter(ParserCategory.deleted_at.is_(None))
            .filter(ParserCategory.parent_id == parent_id)
            .all()
        )


class ParserCategoryKeywordRepository(BaseRepository[ParserCategoryKeyword]):
    """Repository for category keywords."""

    def __init__(self, session: Session):
        super().__init__(session, ParserCategoryKeyword)

    def get_by_category(self, category_id: int) -> list[ParserCategoryKeyword]:
        return (
            self.query()
            .filter(ParserCategoryKeyword.category_id == category_id)
            .order_by(ParserCategoryKeyword.keyword.asc())
            .all()
        )

    def get_exact(self, category_id: int, keyword: str) -> Optional[ParserCategoryKeyword]:
        return (
            self.query()
            .filter(ParserCategoryKeyword.category_id == category_id)
            .filter(ParserCategoryKeyword.keyword == keyword)
            .first()
        )

    def get_grouped_keywords(self) -> dict[int, list[str]]:
        grouped: dict[int, list[str]] = {}
        rows = (
            self.query()
            .order_by(ParserCategoryKeyword.category_id.asc(), ParserCategoryKeyword.keyword.asc())
            .all()
        )
        for row in rows:
            grouped.setdefault(int(row.category_id), []).append(str(row.keyword))
        return grouped
