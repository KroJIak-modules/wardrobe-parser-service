"""Service layer for Shopify sources management endpoints."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config.source_registry import list_sources
from app.models import ParserProduct
from app.repositories import ParserSourceRepository
from app.schemas.shopify import (
    ShopifySourceAdminResponse,
    ShopifySourceResponse,
    ShopifySourceToggleRequest,
)


class ShopifySourceService:
    """Encapsulates business logic for Shopify source listing and toggling."""

    def __init__(self, db: Session):
        self.db = db
        self.source_repo = ParserSourceRepository(db)

    @staticmethod
    def list_sources(only_enabled: bool = True) -> list[ShopifySourceResponse]:
        sources = list_sources(parser_type="shopify")
        if only_enabled:
            sources = [source for source in sources if source.enabled]

        return [
            ShopifySourceResponse(
                key=source.key,
                name=source.name,
                base_url=source.base_url,
                parser_type=source.parser_type,
                enabled=source.enabled,
                notes=source.notes,
            )
            for source in sources
        ]

    def _collect_counts(self, source_id: int) -> tuple[int, int]:
        products_count = (
            self.db.query(func.count(ParserProduct.id))
            .filter(ParserProduct.deleted_at.is_(None))
            .filter(ParserProduct.source_id == source_id)
            .scalar()
            or 0
        )
        categories_count = (
            self.db.query(func.count(func.distinct(ParserProduct.product_type)))
            .filter(ParserProduct.deleted_at.is_(None))
            .filter(ParserProduct.source_id == source_id)
            .filter(ParserProduct.product_type.isnot(None))
            .scalar()
            or 0
        )
        return int(products_count), int(categories_count)

    def list_sources_admin(self) -> list[ShopifySourceAdminResponse]:
        configured = list_sources(parser_type="shopify")
        result: list[ShopifySourceAdminResponse] = []

        for source in configured:
            db_source = self.source_repo.get_by_url(source.base_url)
            effective_enabled = db_source.enabled if db_source else source.enabled
            products_count = 0
            categories_count = 0

            if db_source:
                products_count, categories_count = self._collect_counts(db_source.id)

            result.append(
                ShopifySourceAdminResponse(
                    key=source.key,
                    source_id=db_source.id if db_source else None,
                    name=source.name,
                    base_url=source.base_url,
                    parser_type=source.parser_type,
                    enabled=effective_enabled,
                    notes=source.notes,
                    products_count=products_count,
                    categories_count=categories_count,
                )
            )

        return result

    def toggle_source(self, source_key: str, payload: ShopifySourceToggleRequest) -> ShopifySourceAdminResponse:
        configured = {item.key: item for item in list_sources(parser_type="shopify")}
        source_cfg = configured.get(source_key)
        if not source_cfg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

        db_source = self.source_repo.get_by_url(source_cfg.base_url)
        if not db_source:
            db_source = self.source_repo.create_source(
                name=source_cfg.name,
                url=source_cfg.base_url,
                parser_type=source_cfg.parser_type,
                enabled=source_cfg.enabled,
            )

        db_source.enabled = payload.enabled
        self.db.commit()
        self.db.refresh(db_source)

        products_count, categories_count = self._collect_counts(db_source.id)
        return ShopifySourceAdminResponse(
            key=source_cfg.key,
            source_id=db_source.id,
            name=source_cfg.name,
            base_url=source_cfg.base_url,
            parser_type=source_cfg.parser_type,
            enabled=db_source.enabled,
            notes=source_cfg.notes,
            products_count=products_count,
            categories_count=categories_count,
        )
