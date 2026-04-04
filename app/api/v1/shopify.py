"""Shopify parser diagnostic endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.shopify import (
    ShopifyDiscoveryRequest,
    ShopifyDiscoveryResponse,
    ShopifySourceResponse,
    ShopifySourceAdminResponse,
    ShopifySourceSupplierRequest,
    ShopifySourceToggleRequest,
)
from app.services.shopify_discovery_service import ShopifyDiscoveryService
from app.services.shopify_source_service import ShopifySourceService


router = APIRouter(prefix="/shopify", tags=["shopify"])


@router.post("/discovery", response_model=ShopifyDiscoveryResponse, summary="Shopify discovery диагностика")
def discover_shopify_products(payload: ShopifyDiscoveryRequest) -> ShopifyDiscoveryResponse:
    """Run Shopify discovery against one source domain."""
    return ShopifyDiscoveryService.discover(payload)


@router.get("/sources", response_model=list[ShopifySourceResponse], summary="Список источников Shopify")
def list_shopify_sources(only_enabled: bool = True) -> list[ShopifySourceResponse]:
    """List configured sources from sources file."""
    return ShopifySourceService.list_sources(only_enabled=only_enabled)


@router.get("/sources-admin", response_model=list[ShopifySourceAdminResponse], summary="Источники для админки")
def list_shopify_sources_admin(db: Session = Depends(get_db)) -> list[ShopifySourceAdminResponse]:
    """Return sources with persisted enabled flag and product/category statistics."""
    service = ShopifySourceService(db)
    return service.list_sources_admin()


@router.patch("/sources/{source_key}/enabled", response_model=ShopifySourceAdminResponse, summary="Toggle source enabled")
def toggle_shopify_source(
    source_key: str,
    payload: ShopifySourceToggleRequest,
    db: Session = Depends(get_db),
) -> ShopifySourceAdminResponse:
    """Persist source enabled/disabled flag in DB and return updated admin view row."""
    service = ShopifySourceService(db)
    return service.toggle_source(source_key=source_key, payload=payload)


@router.patch("/sources/{source_key}/supplier", response_model=ShopifySourceAdminResponse, summary="Assign source supplier")
def assign_shopify_source_supplier(
    source_key: str,
    payload: ShopifySourceSupplierRequest,
    db: Session = Depends(get_db),
) -> ShopifySourceAdminResponse:
    """Persist supplier mapping for source and return updated row."""
    service = ShopifySourceService(db)
    return service.assign_source_supplier(source_key=source_key, payload=payload)
