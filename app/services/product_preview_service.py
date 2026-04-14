"""Service helpers for product URL preview and source resolution."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException, status

from app.config.source_registry import list_sources
from app.core.config import settings
from app.parsers.shopify.parser import ShopifyParser
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
    def normalize_preview_money(
        raw_value: str | int | float | None,
        payload_source: str | None,
        currency: str | None = None,
    ) -> float | None:
        if raw_value is None:
            return None
        normalized_text: str | None = None
        if isinstance(raw_value, str):
            normalized_text = raw_value.strip().replace(",", ".")
            if not normalized_text:
                return None
        try:
            parsed = float(normalized_text if normalized_text is not None else raw_value)
        except (TypeError, ValueError):
            return None

        payload_tag = (payload_source or "").strip().lower()
        normalized_currency = (currency or "").strip().upper()
        # Shopify .js payloads often return integer cents.
        if (
            payload_tag == "js"
            and parsed.is_integer()
            and normalized_currency not in {"JPY", "KRW"}
        ):
            return parsed / settings.preview_js_price_cents_divisor
        return parsed

    @staticmethod
    def require_preview_currency(raw_currency: str | None, *, product_url: str | None = None) -> str:
        normalized_currency = (raw_currency or "").strip().upper()
        if len(normalized_currency) != 3:
            if product_url:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Не удалось определить валюту товара: {product_url}",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Не удалось определить валюту товара",
            )
        return normalized_currency

    @classmethod
    def normalize_preview_price(
        cls,
        raw_price: str | int | float | None,
        payload_source: str | None,
        currency: str | None = None,
    ) -> float | None:
        return cls.normalize_preview_money(raw_price, payload_source, currency)

    @classmethod
    def normalize_preview_variants(
        cls,
        variants: list[dict] | None,
        payload_source: str | None,
        currency: str | None = None,
    ) -> list[dict]:
        normalized: list[dict] = []
        for variant in variants or []:
            if not isinstance(variant, dict):
                normalized.append(variant)
                continue
            item = dict(variant)
            price_value = cls.normalize_preview_money(item.get("price"), payload_source, currency)
            if price_value is not None:
                item["price"] = int(price_value) if float(price_value).is_integer() else round(float(price_value), 2)
            compare_at = cls.normalize_preview_money(item.get("compare_at_price"), payload_source, currency)
            if compare_at is not None:
                item["compare_at_price"] = int(compare_at) if float(compare_at).is_integer() else round(float(compare_at), 2)
            normalized.append(item)
        return normalized

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
