from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories.product_repository import ProductRepository
from app.repositories.site_repository import SiteRepository
from app.schemas.common import CursorPage
from app.schemas.parser import ParseResponse, ParserStatus
from app.schemas.product import ProductResponse
from app.services.parser_service import ParserService

router = APIRouter()


@router.get("/status", response_model=list[ParserStatus], summary="Get parsers status")
def get_statuses(db: Session = Depends(get_db)) -> list[ParserStatus]:
    sites = SiteRepository.list_all(db)
    return [
        ParserStatus(
            site_key=site.key,
            is_active=site.is_active,
            last_run_at=site.last_run_at.isoformat() if site.last_run_at else None,
            last_success_at=site.last_success_at.isoformat() if site.last_success_at else None,
            last_error=site.last_error,
            last_error_at=site.last_error_at.isoformat() if site.last_error_at else None,
        )
        for site in sites
    ]


@router.get("/status/{site_key}", response_model=ParserStatus, summary="Get parser status")
def get_status(site_key: str, db: Session = Depends(get_db)) -> ParserStatus:
    site = SiteRepository.get_by_key(db, site_key)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return ParserStatus(
        site_key=site.key,
        is_active=site.is_active,
        last_run_at=site.last_run_at.isoformat() if site.last_run_at else None,
        last_success_at=site.last_success_at.isoformat() if site.last_success_at else None,
        last_error=site.last_error,
        last_error_at=site.last_error_at.isoformat() if site.last_error_at else None,
    )


@router.post("/parse/{site_key}", response_model=ParseResponse, summary="Parse site")
def parse_site(site_key: str, db: Session = Depends(get_db)) -> ParseResponse:
    created, updated = ParserService.parse_site(db, site_key)
    return ParseResponse(created=created, updated=updated)


@router.get("/items/{site_key}", response_model=CursorPage[ProductResponse], summary="Get parsed items")
def list_items(
    site_key: str,
    cursor_id: int | None = Query(default=None, description="Cursor id"),
    limit: int = Query(default=50, ge=1, le=200),
    filter_key: str | None = Query(default=None, description="Field to filter"),
    filter_value: str | None = Query(default=None, description="Filter value"),
    db: Session = Depends(get_db),
) -> CursorPage[ProductResponse]:
    site = SiteRepository.get_by_key(db, site_key)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    items, next_cursor = ProductRepository.list_by_site(
        db,
        site.id,
        cursor_id,
        limit,
        filter_key,
        filter_value,
    )
    return CursorPage(
        items=[ProductResponse.model_validate(item) for item in items],
        next_cursor=next_cursor,
    )
