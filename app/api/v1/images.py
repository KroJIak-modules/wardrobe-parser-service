"""Image gateway API endpoints."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.image_gateway_service import ImageGatewayService


router = APIRouter(tags=["images"])


@router.get("/images/{image_id}")
def get_image(image_id: int, request: Request, db: Session = Depends(get_db)):
    """Unified image endpoint used by frontend instead of direct source URLs."""
    service = ImageGatewayService(db)
    return service.get_image(image_id=image_id, request=request)


@router.post("/images/backfill-assets")
def backfill_image_assets(db: Session = Depends(get_db)):
    """Backfill image_asset rows and image_asset_ids for existing products."""
    service = ImageGatewayService(db)
    return service.backfill_image_assets()
