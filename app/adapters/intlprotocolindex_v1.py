from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import requests

from app.adapters.contracts import SiteAdapter, SourceContext


class IntlprotocolindexV1Adapter(SiteAdapter):
    adapter_key = "intlprotocolindex__v1"
    allowed_strategies = ("intl_protocol_index_cafe24",)

    def discover_visible_catalog(self, context: SourceContext) -> list[str]:
        base_url = context.source_url.rstrip("/")
        timeout = int((context.source_config.get("timeouts") or {}).get("product_sec", 12))
        response = requests.get(f"{base_url}/sitemap.xml", timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        root = ET.fromstring(response.text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [n.text.strip() for n in root.findall(".//sm:loc", ns) if n.text]
        return [u for u in urls if "/product/" in u]

    def normalize_product(self, raw_product: dict) -> dict:
        url = str(raw_product.get("url") or "").strip()
        title = str(raw_product.get("title") or "").strip()
        handle = self._extract_handle(url)
        price = self._to_decimal(raw_product.get("price"))
        currency = str(raw_product.get("currency") or "USD").strip().upper() or "USD"
        variants = raw_product.get("variants")
        if not isinstance(variants, list) or not variants:
            variants = [{"title": "Default", "available": bool(price and price > Decimal("0"))}]
        return {
            "url": url,
            "handle": handle,
            "title": title,
            "description": str(raw_product.get("description") or "").strip() or None,
            "vendor": str(raw_product.get("vendor") or "").strip(),
            "product_type": str(raw_product.get("product_type") or "").strip(),
            "tags": raw_product.get("tags") if isinstance(raw_product.get("tags"), list) else [],
            "price": price,
            "currency": currency,
            "weight_grams": self._to_decimal(raw_product.get("weight_grams")),
            "image_url": self._first_image(raw_product),
            "variants": variants,
        }

    def validate_product(self, normalized_product: dict) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if not normalized_product.get("url"):
            reasons.append("missing_url")
        if not normalized_product.get("handle"):
            reasons.append("missing_handle")
        if not normalized_product.get("title"):
            reasons.append("missing_title")
        price = normalized_product.get("price")
        if price is None or price <= Decimal("0"):
            reasons.append("missing_price")
        currency = normalized_product.get("currency")
        if not currency or len(str(currency)) != 3:
            reasons.append("missing_currency")
        weight_grams = normalized_product.get("weight_grams")
        weight_source = str(normalized_product.get("weight_source") or "").strip().lower()
        if weight_source == "missing" or weight_grams is None or weight_grams <= Decimal("0"):
            reasons.append("missing_weight")
        variants = normalized_product.get("variants")
        if not isinstance(variants, list) or not variants:
            reasons.append("missing_variants")
        return (len(reasons) == 0, reasons)

    @staticmethod
    def _extract_handle(url: str) -> str:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if "product" in parts:
            idx = parts.index("product")
            if idx + 1 < len(parts):
                return parts[idx + 1].strip().lower()
        return parts[-1].strip().lower() if parts else ""

    @staticmethod
    def _to_decimal(value: object) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _first_image(raw_product: dict) -> str:
        base_url = str(raw_product.get("url") or "").strip()
        image_url = IntlprotocolindexV1Adapter._normalize_image_url(str(raw_product.get("image_url") or "").strip(), base_url)
        if image_url:
            return image_url
        images = raw_product.get("images")
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                return IntlprotocolindexV1Adapter._normalize_image_url(str(first.get("src") or "").strip(), base_url)
            return IntlprotocolindexV1Adapter._normalize_image_url(str(first).strip(), base_url)
        return ""

    @staticmethod
    def _normalize_image_url(value: str, product_url: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        if raw.startswith("//"):
            return "https:" + raw
        if raw.startswith("/"):
            parsed = urlparse(product_url)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}{raw}"
        return raw
