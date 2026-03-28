"""Service layer for image gateway and backfill operations."""

from __future__ import annotations

import socket
from collections import defaultdict, deque
from datetime import datetime, timezone
from email.utils import format_datetime
from ipaddress import ip_address
from pathlib import Path
from threading import Lock
from time import monotonic
from urllib.parse import urlparse

import requests
from fastapi import HTTPException, Request, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ParserProduct
from app.repositories import ParserImageAssetRepository

_RATE_LIMITER_LOCK = Lock()
_RATE_LIMITER_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


class ImageGatewayService:
    """Encapsulates image gateway security and backfill logic."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = ParserImageAssetRepository(db)

    @staticmethod
    def _ensure_allowed_url(source_url: str) -> None:
        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Недопустимая схема URL изображения")

        host = parsed.hostname
        if not host:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный URL источника изображения")

        try:
            addresses = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Не удалось разрешить хост изображения") from exc

        for entry in addresses:
            resolved_ip = ip_address(entry[4][0])
            if (
                resolved_ip.is_private
                or resolved_ip.is_loopback
                or resolved_ip.is_link_local
                or resolved_ip.is_multicast
                or resolved_ip.is_reserved
            ):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Запрещенный адрес источника изображения")

    @staticmethod
    def _check_rate_limit(client_ip: str) -> None:
        now = monotonic()
        window_start = now - 60.0
        limit = settings.image_rate_limit_per_minute

        with _RATE_LIMITER_LOCK:
            bucket = _RATE_LIMITER_BUCKETS[client_ip]
            while bucket and bucket[0] < window_start:
                bucket.popleft()
            if len(bucket) >= limit:
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Слишком много запросов")
            bucket.append(now)

    @staticmethod
    def _build_etag(image_id: int, created_at: datetime | None, source_url: str | None) -> str:
        created_ts = "0"
        if created_at is not None:
            dt = created_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            created_ts = str(int(dt.timestamp()))
        src_len = str(len(source_url or ""))
        return f'W/"img-{image_id}-{created_ts}-{src_len}"'

    @staticmethod
    def _cache_headers(etag: str, created_at: datetime | None) -> dict[str, str]:
        headers = {
            "Cache-Control": f"public, max-age={settings.image_cache_max_age_sec}",
            "ETag": etag,
        }
        if created_at is not None:
            dt = created_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            headers["Last-Modified"] = format_datetime(dt, usegmt=True)
        return headers

    def get_image(self, image_id: int, request: Request) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        self._check_rate_limit(client_ip)

        asset = self.repo.get_by_id(image_id)
        if not asset or asset.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Изображение не найдено")

        etag = self._build_etag(asset.id, asset.created_at, asset.source_url)
        headers = self._cache_headers(etag, asset.created_at)
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

        if asset.storage_mode == "stored_file" and asset.stored_path:
            candidate = Path(asset.stored_path)
            if candidate.exists() and candidate.is_file():
                return FileResponse(candidate, headers=headers)

        if not asset.source_url:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник изображения отсутствует")

        self._ensure_allowed_url(asset.source_url)

        try:
            upstream = requests.get(asset.source_url, timeout=settings.image_proxy_timeout_sec, stream=True)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Ошибка загрузки изображения: {exc}") from exc

        if upstream.status_code >= 400:
            upstream.close()
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Источник изображения недоступен")

        content_type = upstream.headers.get("Content-Type", "image/jpeg")
        if not content_type.lower().startswith("image/"):
            upstream.close()
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Источник вернул не изображение")

        content_length_header = upstream.headers.get("Content-Length")
        if content_length_header is not None:
            try:
                content_length = int(content_length_header)
            except ValueError:
                content_length = -1
            if content_length > settings.image_proxy_max_bytes:
                upstream.close()
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Изображение слишком большое",
                )

        chunks: list[bytes] = []
        total_size = 0
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total_size += len(chunk)
                if total_size > settings.image_proxy_max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Изображение слишком большое",
                    )
                chunks.append(chunk)
        finally:
            upstream.close()

        media_type = upstream.headers.get("Content-Type", "image/jpeg")
        return Response(content=b"".join(chunks), media_type=media_type, headers=headers)

    def backfill_image_assets(self) -> dict:
        products = (
            self.db.query(ParserProduct)
            .filter(ParserProduct.deleted_at.is_(None))
            .all()
        )

        updated = 0
        for product in products:
            urls = product.image_urls or []
            if not urls:
                continue
            assets = self.repo.ensure_assets(urls)
            mapped_ids = [asset.id for asset in assets]
            if (product.image_asset_ids or []) != mapped_ids:
                product.image_asset_ids = mapped_ids
                product.image_count = len(urls)
                updated += 1

        self.db.commit()
        return {"ok": True, "updated_products": updated}
