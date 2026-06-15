from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal
from urllib.parse import urlparse

import requests

from app.adapters.base import BaseProductAdapter
from app.adapters.contracts import AdapterVariantDraft, SourceContext


class IntlprotocolindexV1Adapter(BaseProductAdapter):
    adapter_key = "intlprotocolindex__v1"
    allowed_strategies = ("intl_protocol_index_cafe24",)
    default_currency_code = "USD"

    def discover_visible_catalog(self, context: SourceContext) -> list[str]:
        base_url = context.source_url.rstrip("/")
        timeout = int((context.source_config.get("timeouts") or {}).get("product_sec", 12))
        response = requests.get(f"{base_url}/sitemap.xml", timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        root = ET.fromstring(response.text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [node.text.strip() for node in root.findall(".//sm:loc", ns) if node.text]
        return [url for url in urls if "/product/" in url]

    def _extract_handle(self, url: str) -> str:
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        if "product" in parts:
            index = parts.index("product")
            if index + 1 < len(parts):
                return parts[index + 1].strip().lower()
        return parts[-1].strip().lower() if parts else ""

    def _fallback_variant(self, raw_product: dict) -> AdapterVariantDraft | None:
        price_amount = self._to_decimal(raw_product.get("price_amount") or raw_product.get("price"))
        return {
            "id": None,
            "title": self.default_variant_title,
            "sku": None,
            "price_amount": price_amount,
            "currency_code": "USD",
            "available": bool(price_amount is not None and price_amount > Decimal("0")),
        }
