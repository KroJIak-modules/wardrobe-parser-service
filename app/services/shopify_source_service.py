"""Service layer for Shopify sources management endpoints."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config.source_registry import list_sources
from app.models import ParserProduct
from app.repositories import ParserSourceRepository, ParserSupplierRepository
from app.schemas.shopify import (
    ShopifySourceSupplierRequest,
    ShopifySourceAdminResponse,
    ShopifySourceResponse,
    ShopifySourceToggleRequest,
)


class ShopifySourceService:
    """Encapsulates business logic for Shopify source listing and toggling."""

    def __init__(self, db: Session):
        self.db = db
        self.source_repo = ParserSourceRepository(db)
        self.supplier_repo = ParserSupplierRepository(db)

    @staticmethod
    def _normalize_currency(raw: str | None, *, default: str = "RUB") -> str:
        value = (raw or default).strip().upper()
        if value not in {"RUB", "USD", "EUR", "GBP"}:
            return default
        return value

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
                status_label=source.status_label,
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
        default_supplier = self.supplier_repo.get_default_supplier()

        for source in configured:
            db_source = self.source_repo.get_by_url(source.base_url)
            effective_enabled = db_source.enabled if db_source else source.enabled
            products_count = 0
            categories_count = 0

            if db_source:
                products_count, categories_count = self._collect_counts(db_source.id)
            supplier = db_source.supplier if db_source and db_source.supplier else default_supplier

            result.append(
                ShopifySourceAdminResponse(
                    key=source.key,
                    source_id=db_source.id if db_source else None,
                    name=source.name,
                    base_url=source.base_url,
                    parser_type=source.parser_type,
                    enabled=effective_enabled,
                    notes=source.notes,
                    status_label=source.status_label,
                    products_count=products_count,
                    categories_count=categories_count,
                    supplier_id=supplier.id,
                    supplier_key=supplier.key,
                    supplier_name=supplier.name,
                    promo_factor=float(db_source.promo_factor) if db_source else 1.0,
                    promo_only_no_discount=bool(db_source.promo_only_no_discount) if db_source else False,
                    buyout_surcharge_value=float(db_source.buyout_surcharge_value) if db_source else 0.0,
                    buyout_surcharge_currency=self._normalize_currency(
                        db_source.buyout_surcharge_currency if db_source else "RUB",
                        default="RUB",
                    ),
                )
            )

        return result

    def toggle_source(self, source_key: str, payload: ShopifySourceToggleRequest) -> ShopifySourceAdminResponse:
        configured = {item.key: item for item in list_sources(parser_type="shopify")}
        source_cfg = configured.get(source_key)
        if not source_cfg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

        default_supplier = self.supplier_repo.get_default_supplier()
        db_source = self.source_repo.get_by_url(source_cfg.base_url)
        if not db_source:
            db_source = self.source_repo.create_source(
                name=source_cfg.name,
                url=source_cfg.base_url,
                parser_type=source_cfg.parser_type,
                enabled=source_cfg.enabled,
                supplier_id=default_supplier.id,
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
            status_label=source_cfg.status_label,
            products_count=products_count,
            categories_count=categories_count,
            supplier_id=db_source.supplier.id if db_source.supplier else default_supplier.id,
            supplier_key=db_source.supplier.key if db_source.supplier else default_supplier.key,
            supplier_name=db_source.supplier.name if db_source.supplier else default_supplier.name,
            promo_factor=float(db_source.promo_factor),
            promo_only_no_discount=bool(db_source.promo_only_no_discount),
            buyout_surcharge_value=float(db_source.buyout_surcharge_value),
            buyout_surcharge_currency=self._normalize_currency(db_source.buyout_surcharge_currency, default="RUB"),
        )

    def assign_source_supplier(
        self,
        *,
        source_key: str,
        payload: ShopifySourceSupplierRequest,
    ) -> ShopifySourceAdminResponse:
        configured = {item.key: item for item in list_sources(parser_type="shopify")}
        source_cfg = configured.get(source_key)
        if not source_cfg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

        supplier = None
        if payload.supplier_id is not None:
            supplier = self.supplier_repo.get_by_id(payload.supplier_id)
            if supplier is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Поставщик не найден")

        db_source = self.source_repo.get_by_url(source_cfg.base_url)
        if not db_source:
            db_source = self.source_repo.create_source(
                name=source_cfg.name,
                url=source_cfg.base_url,
                parser_type=source_cfg.parser_type,
                enabled=source_cfg.enabled,
                supplier_id=supplier.id if supplier else self.supplier_repo.get_default_supplier().id,
            )

        if supplier is not None:
            db_source.supplier_id = supplier.id
        if payload.promo_factor is not None:
            db_source.promo_factor = float(payload.promo_factor)
        if payload.promo_only_no_discount is not None:
            db_source.promo_only_no_discount = bool(payload.promo_only_no_discount)
        if payload.buyout_surcharge_value is not None:
            db_source.buyout_surcharge_value = float(payload.buyout_surcharge_value)
        if payload.buyout_surcharge_currency is not None:
            db_source.buyout_surcharge_currency = self._normalize_currency(
                payload.buyout_surcharge_currency,
                default=self._normalize_currency(getattr(db_source, "buyout_surcharge_currency", None), default="RUB"),
            )
        self.db.commit()
        self.db.refresh(db_source)

        products_count, categories_count = self._collect_counts(db_source.id)
        supplier_data = db_source.supplier if db_source.supplier else supplier
        if supplier_data is None:
            supplier_data = self.supplier_repo.get_default_supplier()
        return ShopifySourceAdminResponse(
            key=source_cfg.key,
            source_id=db_source.id,
            name=source_cfg.name,
            base_url=source_cfg.base_url,
            parser_type=source_cfg.parser_type,
            enabled=db_source.enabled,
            notes=source_cfg.notes,
            status_label=source_cfg.status_label,
            products_count=products_count,
            categories_count=categories_count,
            supplier_id=supplier_data.id,
            supplier_key=supplier_data.key,
            supplier_name=supplier_data.name,
            promo_factor=float(db_source.promo_factor),
            promo_only_no_discount=bool(db_source.promo_only_no_discount),
            buyout_surcharge_value=float(db_source.buyout_surcharge_value),
            buyout_surcharge_currency=self._normalize_currency(db_source.buyout_surcharge_currency, default="RUB"),
        )
