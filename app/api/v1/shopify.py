"""Shopify parser diagnostic endpoints."""

from fastapi import APIRouter

from app.config.source_registry import list_sources
from app.schemas.shopify import ShopifyDiscoveryRequest, ShopifyDiscoveryResponse, ShopifySourceResponse
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
