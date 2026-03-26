"""API endpoints for recursive category tree and keyword rules."""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import ParserCategory, ParserCategoryKeyword
from app.repositories import ParserCategoryRepository, ParserCategoryKeywordRepository
from app.schemas.parser import (
    CategoryCreateRequest,
    CategoryKeywordRequest,
    CategoryTreeNodeResponse,
    CategoryUpdateRequest,
)

router = APIRouter(tags=["categories"])


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "category"


def _ensure_fallback(repo: ParserCategoryRepository) -> ParserCategory:
    fallback = repo.get_fallback()
    if fallback:
        return fallback
    created = repo.create(
        name="Прочее",
        slug="prochee",
        parent_id=None,
        is_fallback=True,
    )
    repo.flush()
    return created


def _build_tree(
    categories: list[ParserCategory],
    keyword_repo: ParserCategoryKeywordRepository,
) -> list[CategoryTreeNodeResponse]:
    by_parent: dict[int | None, list[ParserCategory]] = {}
    for category in categories:
        by_parent.setdefault(category.parent_id, []).append(category)

    for nodes in by_parent.values():
        nodes.sort(key=lambda c: (not c.is_fallback, c.name.lower()))

    def walk(node: ParserCategory, inherited: list[str]) -> CategoryTreeNodeResponse:
        own_keywords = [item.keyword for item in keyword_repo.get_by_category(node.id)]
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


def _find_node(tree: list[CategoryTreeNodeResponse], category_id: int) -> CategoryTreeNodeResponse | None:
    for node in tree:
        if node.id == category_id:
            return node
        found = _find_node(node.children, category_id)
        if found:
            return found
    return None


@router.get("/categories/tree", response_model=list[CategoryTreeNodeResponse])
def get_category_tree(db: Session = Depends(get_db)):
    category_repo = ParserCategoryRepository(db)
    keyword_repo = ParserCategoryKeywordRepository(db)

    _ensure_fallback(category_repo)
    db.commit()

    categories = category_repo.get_all_active()
    return _build_tree(categories, keyword_repo)


@router.post("/categories", response_model=CategoryTreeNodeResponse)
def create_category(payload: CategoryCreateRequest, db: Session = Depends(get_db)):
    category_repo = ParserCategoryRepository(db)
    keyword_repo = ParserCategoryKeywordRepository(db)

    _ensure_fallback(category_repo)

    parent_id = payload.parent_id
    if parent_id is not None:
        parent = category_repo.get_by_id(parent_id)
        if not parent or parent.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Родительская категория не найдена")

    slug = _slugify(payload.name)
    if category_repo.get_by_slug(slug):
        slug = f"{slug}-{int(datetime.now(timezone.utc).timestamp())}"

    category = category_repo.create(
        name=payload.name.strip(),
        slug=slug,
        parent_id=parent_id,
        is_fallback=False,
    )
    category_repo.flush()
    db.commit()
    categories = category_repo.get_all_active()
    tree = _build_tree(categories, keyword_repo)
    created_node = _find_node(tree, category.id)
    if not created_node:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Не удалось построить дерево категорий")
    return created_node


@router.patch("/categories/{category_id}", response_model=CategoryTreeNodeResponse)
def update_category(category_id: int, payload: CategoryUpdateRequest, db: Session = Depends(get_db)):
    category_repo = ParserCategoryRepository(db)
    keyword_repo = ParserCategoryKeywordRepository(db)

    category = category_repo.get_by_id(category_id)
    if not category or category.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")

    if payload.name is not None:
        category.name = payload.name.strip()
        if not category.is_fallback:
            slug = _slugify(category.name)
            maybe = category_repo.get_by_slug(slug)
            if maybe and maybe.id != category.id:
                slug = f"{slug}-{int(datetime.now(timezone.utc).timestamp())}"
            category.slug = slug

    if "parent_id" in payload.model_fields_set:
        if payload.parent_id is None:
            category.parent_id = None
        else:
            if payload.parent_id == category.id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Категория не может быть своим родителем")
            parent = category_repo.get_by_id(payload.parent_id)
            if not parent or parent.deleted_at is not None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Новый родитель не найден")
            if _is_descendant(category_repo.get_all_active(), category.id, payload.parent_id):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя переместить категорию внутрь своего потомка")
            category.parent_id = payload.parent_id

    db.commit()
    categories = category_repo.get_all_active()
    tree = _build_tree(categories, keyword_repo)
    updated_node = _find_node(tree, category.id)
    if not updated_node:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Не удалось построить дерево категорий")
    return updated_node


@router.delete("/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    category_repo = ParserCategoryRepository(db)

    category = category_repo.get_by_id(category_id)
    if not category or category.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
    if category.is_fallback:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Категорию 'Прочее' нельзя удалить")

    if category_repo.get_children(category_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Нельзя удалить категорию с дочерними категориями",
        )

    category.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.post("/categories/{category_id}/keywords")
def add_category_keyword(category_id: int, payload: CategoryKeywordRequest, db: Session = Depends(get_db)):
    category_repo = ParserCategoryRepository(db)
    keyword_repo = ParserCategoryKeywordRepository(db)

    category = category_repo.get_by_id(category_id)
    if not category or category.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")

    keyword = payload.keyword.strip().lower()
    if not keyword:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ключевое слово не может быть пустым")

    existing = keyword_repo.get_exact(category_id, keyword)
    if existing:
        return {"ok": True, "keyword": keyword, "duplicated": True}

    keyword_repo.create(category_id=category_id, keyword=keyword)
    db.commit()
    return {"ok": True, "keyword": keyword}


@router.delete("/categories/{category_id}/keywords/{keyword}")
def remove_category_keyword(category_id: int, keyword: str, db: Session = Depends(get_db)):
    category_repo = ParserCategoryRepository(db)
    keyword_repo = ParserCategoryKeywordRepository(db)

    category = category_repo.get_by_id(category_id)
    if not category or category.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")

    normalized = keyword.strip().lower()
    entity = keyword_repo.get_exact(category_id, normalized)
    if not entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ключевое слово не найдено")

    db.delete(entity)
    db.commit()
    return {"ok": True}
