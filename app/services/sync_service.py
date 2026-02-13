from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.product import Product
from app.repositories.product_repository import ProductRepository
from app.repositories.site_repository import SiteRepository


class SyncService:
    @staticmethod
    def send_pending_products(db: Session) -> int:
        items = ProductRepository.list_pending_sync(db, settings.sync_batch_size)
        if not items:
            return 0
        payload = {
            "items": [SyncService._map_product(item) for item in items],
        }
        headers = {"X-Service-Token": settings.service_token} if settings.service_token else {}
        response = requests.post(
            f"{settings.backend_base_url}/api/v1/parser/items",
            json=payload,
            headers=headers,
            timeout=settings.request_timeout_sec,
        )
        response.raise_for_status()
        now = datetime.now(timezone.utc)
        for item in items:
            item.pending_sync = False
            item.last_sent_at = now
        db.commit()
        return len(items)

    @staticmethod
    def send_site_statuses(db: Session) -> int:
        sites = SiteRepository.list_all(db)
        if not sites:
            return 0
        payload = [
            {
                "key": site.key,
                "name": site.name,
                "base_url": site.base_url,
                "is_active": site.is_active,
                "last_status": "ok" if site.last_error is None else "error",
                "last_status_at": site.last_success_at.isoformat() if site.last_success_at else None,
                "last_error": site.last_error,
                "last_error_at": site.last_error_at.isoformat() if site.last_error_at else None,
            }
            for site in sites
        ]
        headers = {"X-Service-Token": settings.service_token} if settings.service_token else {}
        response = requests.post(
            f"{settings.backend_base_url}/api/v1/sites/status",
            json=payload,
            headers=headers,
            timeout=settings.request_timeout_sec,
        )
        response.raise_for_status()
        return len(sites)

    @staticmethod
    def _map_product(product: Product) -> dict:
        return {
            "site_key": product.site.key,
            "site_name": product.site.name,
            "site_base_url": product.site.base_url,
            "external_id": product.external_id,
            "name": product.name,
            "category": product.category,
            "price": float(product.price) if product.price is not None else None,
            "currency": product.currency,
            "size": product.size,
            "additional_info": product.additional_info,
            "size_data": product.size_data,
            "image_urls": product.image_urls,
            "product_url": product.product_url,
            "image_url": product.image_url,
            "description": product.description,
        }
