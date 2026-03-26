"""Shopify parser diagnostic endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config.source_registry import list_sources
from app.core.database import get_db
from app.models import ParserProduct
from app.repositories import ParserSourceRepository
from app.schemas.shopify import (
    ShopifyDiscoveryRequest,
    ShopifyDiscoveryResponse,
    ShopifySourceResponse,
    ShopifySourceAdminResponse,
    ShopifySourceToggleRequest,
)
from app.services.shopify_discovery_service import ShopifyDiscoveryService


router = APIRouter(prefix="/shopify", tags=["shopify"])


@router.post("/discovery", response_model=ShopifyDiscoveryResponse, summary="Shopify discovery диагностика")
def discover_shopify_products(payload: ShopifyDiscoveryRequest) -> ShopifyDiscoveryResponse:
    """Run Shopify discovery against one source domain."""
    return ShopifyDiscoveryService.discover(payload)


@router.get("/sources", response_model=list[ShopifySourceResponse], summary="Список источников Shopify")
def list_shopify_sources(only_enabled: bool = True) -> list[ShopifySourceResponse]:
    """List configured sources from sources file."""
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


@router.get("/sources-admin", response_model=list[ShopifySourceAdminResponse], summary="Источники для админки")
def list_shopify_sources_admin(db: Session = Depends(get_db)) -> list[ShopifySourceAdminResponse]:
    """Return sources with persisted enabled flag and product/category statistics."""
    source_repo = ParserSourceRepository(db)
    configured = list_sources(parser_type="shopify")
    result: list[ShopifySourceAdminResponse] = []

    for source in configured:
      db_source = source_repo.get_by_url(source.base_url)
      effective_enabled = db_source.enabled if db_source else source.enabled
      products_count = 0
      categories_count = 0

      if db_source:
          products_count = (
              db.query(func.count(ParserProduct.id))
              .filter(ParserProduct.deleted_at.is_(None))
              .filter(ParserProduct.source_id == db_source.id)
              .scalar()
              or 0
          )
          categories_count = (
              db.query(func.count(func.distinct(ParserProduct.product_type)))
              .filter(ParserProduct.deleted_at.is_(None))
              .filter(ParserProduct.source_id == db_source.id)
              .filter(ParserProduct.product_type.isnot(None))
              .scalar()
              or 0
          )

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


@router.patch("/sources/{source_key}/enabled", response_model=ShopifySourceAdminResponse, summary="Toggle source enabled")
def toggle_shopify_source(
    source_key: str,
    payload: ShopifySourceToggleRequest,
    db: Session = Depends(get_db),
) -> ShopifySourceAdminResponse:
    """Persist source enabled/disabled flag in DB and return updated admin view row."""
    configured = {item.key: item for item in list_sources(parser_type="shopify")}
    source_cfg = configured.get(source_key)
    if not source_cfg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    source_repo = ParserSourceRepository(db)
    db_source = source_repo.get_by_url(source_cfg.base_url)
    if not db_source:
        db_source = source_repo.create_source(
            name=source_cfg.name,
            url=source_cfg.base_url,
            parser_type=source_cfg.parser_type,
            enabled=source_cfg.enabled,
        )

    db_source.enabled = payload.enabled
    db.commit()
    db.refresh(db_source)

    products_count = (
        db.query(func.count(ParserProduct.id))
        .filter(ParserProduct.deleted_at.is_(None))
        .filter(ParserProduct.source_id == db_source.id)
        .scalar()
        or 0
    )
    categories_count = (
        db.query(func.count(func.distinct(ParserProduct.product_type)))
        .filter(ParserProduct.deleted_at.is_(None))
        .filter(ParserProduct.source_id == db_source.id)
        .filter(ParserProduct.product_type.isnot(None))
        .scalar()
        or 0
    )

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
