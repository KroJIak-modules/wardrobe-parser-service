"""Service helpers for product URL preview and source resolution."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException, status

from app.config.source_registry import list_sources
from app.core.config import settings
from app.parsers.shopify_parser import ShopifyParser
from app.repositories import ParserSourceRepository


class ProductPreviewService:
    """Encapsulates preview fetching, host whitelist checks and source resolution."""

    def __init__(self, source_repo: Optional[ParserSourceRepository]):
        self.source_repo = source_repo

    @staticmethod
    def clean_host(url: str) -> str:
        host = urlparse(url).hostname
        return (host or "").lower().replace("www.", "")

    @staticmethod
    def normalize_preview_price(raw_price: str | None, payload_source: str | None) -> float | None:
        if raw_price is None:
            return None
        try:
            parsed = float(raw_price)
        except ValueError:
            return None

        # Shopify .js often returns integer cents while .json returns decimal currency units.
        if payload_source == "js" and parsed >= 1000 and parsed.is_integer():
            return parsed / 100
        return parsed

    def allowed_shopify_hosts(self) -> list[str]:
        hosts: list[str] = []
        for source in list_sources(parser_type="shopify"):
            if not source.enabled:
                continue
            host = self.clean_host(source.base_url)
            if host:
                hosts.append(host)
        return hosts

    def fetch_preview(self, url: str):
        try:
            host = self.clean_host(url)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный URL") from exc

        allowed_hosts = self.allowed_shopify_hosts()
        if not any(host == item or host.endswith(f".{item}") for item in allowed_hosts):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Домен не входит в whitelist")

        try:
            return ShopifyParser.preview_product_url(
                url,
                timeout_sec=settings.parser_default_timeout_sec,
                max_retries=settings.parser_default_max_retries,
                retry_backoff_sec=settings.parser_default_retry_backoff_sec,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Не удалось получить preview: {exc}",
            ) from exc

    def resolve_or_create_source(self, product_url: str):
        if self.source_repo is None:
            raise RuntimeError("Source repository is required for source resolution")

        host = self.clean_host(product_url)

        for source_cfg in list_sources(parser_type="shopify"):
            cfg_host = self.clean_host(source_cfg.base_url)
            if host == cfg_host or host.endswith(f".{cfg_host}"):
                source = self.source_repo.get_by_url(source_cfg.base_url)
                if source:
                    return source
                return self.source_repo.create_source(
                    name=source_cfg.name,
                    url=source_cfg.base_url,
                    parser_type=source_cfg.parser_type,
                    enabled=source_cfg.enabled,
                )

        source = self.source_repo.get_by_url(f"https://{host}")
        if source:
            return source
        return self.source_repo.create_source(name=host, url=f"https://{host}", parser_type="shopify", enabled=True)
