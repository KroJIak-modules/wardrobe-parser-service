"""Service layer for category tree and keyword rule operations."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import ParserCategory
from app.repositories import ParserCategoryKeywordRepository, ParserCategoryRepository
from app.schemas.parser import (
    CategoryCreateRequest,
    CategoryKeywordRequest,
    CategoryTreeNodeResponse,
    CategoryUpdateRequest,
)


class CategoryTreeService:
    """Encapsulates category tree and keyword business logic."""

    def __init__(self, db: Session):
        self.db = db
        self.category_repo = ParserCategoryRepository(db)
        self.keyword_repo = ParserCategoryKeywordRepository(db)

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "category"

    def _ensure_fallback(self) -> ParserCategory:
        fallback = self.category_repo.get_fallback()
        if fallback:
            return fallback

        created = self.category_repo.create(
            name="Прочее",
            slug="prochee",
            parent_id=None,
            is_fallback=True,
        )
        self.category_repo.flush()
        return created

    def _purge_fallback_keywords(self, fallback: ParserCategory) -> None:
        stale = self.keyword_repo.get_by_category(fallback.id)
        if not stale:
            return
        for item in stale:
            self.db.delete(item)

    def _build_tree(self, categories: list[ParserCategory]) -> list[CategoryTreeNodeResponse]:
        by_parent: dict[int | None, list[ParserCategory]] = {}
        for category in categories:
            by_parent.setdefault(category.parent_id, []).append(category)

        for nodes in by_parent.values():
            nodes.sort(key=lambda c: (not c.is_fallback, c.name.lower()))

        def walk(node: ParserCategory, inherited: list[str]) -> CategoryTreeNodeResponse:
            own_keywords = [] if node.is_fallback else [item.keyword for item in self.keyword_repo.get_by_category(node.id)]
            effective = sorted(set([*inherited, *own_keywords]))
            children = [walk(child, effective) for child in by_parent.get(node.id, [])]
            return CategoryTreeNodeResponse(
                id=node.id,
                name=node.name,
                slug=node.slug,
                parent_id=node.parent_id,
                is_fallback=node.is_fallback,
                keywords=own_keywords,
                effective_keywords=effective,
                children=children,
            )

        roots = by_parent.get(None, [])
        return [walk(root, []) for root in roots]

    @staticmethod
    def _is_descendant(categories: list[ParserCategory], ancestor_id: int, candidate_id: int) -> bool:
        by_parent: dict[int | None, list[int]] = {}
        for item in categories:
            by_parent.setdefault(item.parent_id, []).append(item.id)

        stack = list(by_parent.get(ancestor_id, []))
        seen: set[int] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            if current == candidate_id:
                return True
            stack.extend(by_parent.get(current, []))
        return False

    def _find_node(self, tree: list[CategoryTreeNodeResponse], category_id: int) -> CategoryTreeNodeResponse | None:
        for node in tree:
            if node.id == category_id:
                return node
            found = self._find_node(node.children, category_id)
            if found:
                return found
        return None

    def _build_single_node_response(self, category: ParserCategory) -> CategoryTreeNodeResponse:
        own_keywords = [item.keyword for item in self.keyword_repo.get_by_category(category.id)]
        return CategoryTreeNodeResponse(
            id=category.id,
            name=category.name,
            slug=category.slug,
            parent_id=category.parent_id,
            is_fallback=category.is_fallback,
            keywords=own_keywords,
            effective_keywords=own_keywords,
            children=[],
        )

    def get_category_tree(self) -> list[CategoryTreeNodeResponse]:
        fallback = self._ensure_fallback()
        self._purge_fallback_keywords(fallback)
        self.db.commit()

        categories = self.category_repo.get_all_active()
        return self._build_tree(categories)

    def create_category(self, payload: CategoryCreateRequest) -> CategoryTreeNodeResponse:
        self._ensure_fallback()

        parent_id = payload.parent_id
        if parent_id is not None:
            parent = self.category_repo.get_by_id(parent_id)
            if not parent or parent.deleted_at is not None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Родительская категория не найдена")

        slug = self._slugify(payload.name)
        if self.category_repo.get_by_slug(slug):
            slug = f"{slug}-{int(datetime.now(timezone.utc).timestamp())}"

        category = self.category_repo.create(
            name=payload.name.strip(),
            slug=slug,
            parent_id=parent_id,
            is_fallback=False,
        )
        self.category_repo.flush()
        self.db.commit()

        categories = self.category_repo.get_all_active()
        tree = self._build_tree(categories)
        created_node = self._find_node(tree, category.id)
        if not created_node:
            return self._build_single_node_response(category)
        return created_node

    def update_category(self, category_id: int, payload: CategoryUpdateRequest) -> CategoryTreeNodeResponse:
        category = self.category_repo.get_by_id(category_id)
        if not category or category.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")

        if payload.name is not None:
            category.name = payload.name.strip()
            if not category.is_fallback:
                slug = self._slugify(category.name)
                maybe = self.category_repo.get_by_slug(slug)
                if maybe and maybe.id != category.id:
                    slug = f"{slug}-{int(datetime.now(timezone.utc).timestamp())}"
                category.slug = slug

        if "parent_id" in payload.model_fields_set:
            if payload.parent_id is None:
                category.parent_id = None
            else:
                if payload.parent_id == category.id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Категория не может быть своим родителем",
                    )
                parent = self.category_repo.get_by_id(payload.parent_id)
                if not parent or parent.deleted_at is not None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Новый родитель не найден")
                if self._is_descendant(self.category_repo.get_all_active(), category.id, payload.parent_id):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Нельзя переместить категорию внутрь своего потомка",
                    )
                category.parent_id = payload.parent_id

        self.db.commit()
        categories = self.category_repo.get_all_active()
        tree = self._build_tree(categories)
        updated_node = self._find_node(tree, category.id)
        if not updated_node:
            return self._build_single_node_response(category)
        return updated_node

    def delete_category(self, category_id: int) -> dict:
        category = self.category_repo.get_by_id(category_id)
        if not category or category.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
        if category.is_fallback:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Категорию 'Прочее' нельзя удалить")

        if self.category_repo.get_children(category_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Нельзя удалить категорию с дочерними категориями",
            )

        category.deleted_at = datetime.now(timezone.utc)
        self.db.commit()
        return {"ok": True}

    def add_category_keyword(self, category_id: int, payload: CategoryKeywordRequest) -> dict:
        category = self.category_repo.get_by_id(category_id)
        if not category or category.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
        if category.is_fallback:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="У системной категории не может быть ключевых слов",
            )

        keyword = payload.keyword.strip().lower()
        if not keyword:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ключевое слово не может быть пустым",
            )

        existing = self.keyword_repo.get_exact(category_id, keyword)
        if existing:
            return {"ok": True, "keyword": keyword, "duplicated": True}

        self.keyword_repo.create(category_id=category_id, keyword=keyword)
        self.db.commit()
        return {"ok": True, "keyword": keyword}

    def remove_category_keyword(self, category_id: int, keyword: str) -> dict:
        category = self.category_repo.get_by_id(category_id)
        if not category or category.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")

        normalized = keyword.strip().lower()
        entity = self.keyword_repo.get_exact(category_id, normalized)
        if not entity:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ключевое слово не найдено")

        self.db.delete(entity)
        self.db.commit()
        return {"ok": True}
