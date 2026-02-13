from datetime import datetime, timezone
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.models.product import Product
from app.parsers.registry import ParserRegistry
from app.parsers.types import ParsedProduct
from app.repositories.product_repository import ProductRepository
from app.repositories.site_repository import SiteRepository


class ParserService:
    @staticmethod
    def parse_site(db: Session, site_key: str) -> tuple[int, int]:
        registry = ParserRegistry()
        parser = registry.get(site_key)
        if parser is None:
            raise ValidationError("Parser not found")
        site = SiteRepository.get_by_key(db, site_key)
        if site is None:
            site = SiteRepository.create(
                db,
                key=site_key,
                name=site_key,
                base_url=settings.example_site_url if site_key == "example" else None,
            )
        now = datetime.now(timezone.utc)
        SiteRepository.update(db, site, last_run_at=now)
        try:
            parsed_items = parser.parse()
            created, updated = ParserService._upsert_products(db, site.id, parsed_items, now)
            SiteRepository.update(db, site, last_success_at=now, last_error=None, last_error_at=None)
            db.commit()
            logging.info(
                "Parsed site: site_key=%s created=%s updated=%s",
                site_key,
                created,
                updated,
            )
            return created, updated
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            fresh_site = SiteRepository.get_by_key(db, site_key)
            if fresh_site is None:
                fresh_site = SiteRepository.create(db, key=site_key, name=site_key)
            SiteRepository.update(db, fresh_site, last_error=str(exc), last_error_at=now)
            db.commit()
            raise

    @staticmethod
    def _upsert_products(
        db: Session,
        site_id: int,
        items: list[ParsedProduct],
        parsed_at: datetime,
    ) -> tuple[int, int]:
        created = 0
        updated = 0
        for item in items:
            existing = ProductRepository.get_by_external_id(db, site_id, item.external_id)
            payload = {
                "site_id": site_id,
                "external_id": item.external_id,
                "name": item.name,
                "category": item.category,
                "price": item.price,
                "currency": item.currency,
                "size": item.size,
                "additional_info": item.additional_info,
                "size_data": item.size_data,
                "image_urls": item.image_urls,
                "product_url": item.product_url,
                "image_url": item.image_url,
                "description": item.description,
                "parsed_at": parsed_at,
                "pending_sync": True,
            }
            if existing is None:
                ProductRepository.create(db, **payload)
                created += 1
            else:
                ProductRepository.update(db, existing, **payload)
                updated += 1
        return created, updated
