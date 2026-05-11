from __future__ import annotations

import json
import re
from html import unescape
from typing import Iterable

from app.services.shopify_http_client import ShopifyHttpClient


class ShopifyCurrencyResolver:
    @staticmethod
    def normalize(value: object) -> str:
        raw = str(value or '').strip().upper()
        if raw == 'GBR':
            return 'GBP'
        return raw

    @staticmethod
    def resolve_storefront_currency(base_url: str, timeout: int, allowed_currencies: Iterable[str]) -> tuple[str, str]:
        allowed = {ShopifyCurrencyResolver.normalize(x) for x in allowed_currencies if ShopifyCurrencyResolver.normalize(x)}
        if not allowed:
            return '', 'not_configured'
        try:
            response = ShopifyHttpClient.get_text(base_url.rstrip('/') + '/', timeout)
        except Exception:
            return '', 'network'
        if response.status_code != 200:
            return '', f'http_{response.status_code}'
        candidates = ShopifyCurrencyResolver._extract_candidates(response.text)
        for value, source in candidates:
            normalized = ShopifyCurrencyResolver.normalize(value)
            if normalized in allowed:
                return normalized, source
        return '', 'not_found'

    @staticmethod
    def _extract_candidates(html: str) -> list[tuple[str, str]]:
        text = html or ''
        candidates: list[tuple[str, str]] = []
        patterns = [
            (r'Shopify\.currency\s*=\s*\{[^}]*["\']active["\']\s*:\s*["\']([A-Za-z]{3})["\']', 'shopify_currency_active'),
            (r'["\']currencyCode["\']\s*:\s*["\']([A-Za-z]{3})["\']', 'currency_code'),
            (r'["\']priceCurrency["\']\s*:\s*["\']([A-Za-z]{3})["\']', 'json_ld_price_currency'),
            (r'property=["\']og:price:currency["\']\s+content=["\']([A-Za-z]{3})["\']', 'og_price_currency'),
        ]
        for pattern, source in patterns:
            for match in re.finditer(pattern, text, flags=re.I | re.S):
                candidates.append((match.group(1), source))
        candidates.extend(ShopifyCurrencyResolver._extract_json_ld_currencies(text))
        return candidates

    @staticmethod
    def _extract_json_ld_currencies(html: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        blocks = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, flags=re.I | re.S)
        for block in blocks:
            try:
                data = json.loads(unescape(block).strip())
            except Exception:
                continue
            ShopifyCurrencyResolver._collect_price_currencies(data, out)
        return out

    @staticmethod
    def _collect_price_currencies(value: object, out: list[tuple[str, str]]) -> None:
        if isinstance(value, dict):
            raw = value.get('priceCurrency') or value.get('currencyCode')
            if raw:
                out.append((str(raw), 'json_ld_price_currency'))
            for child in value.values():
                ShopifyCurrencyResolver._collect_price_currencies(child, out)
        elif isinstance(value, list):
            for child in value:
                ShopifyCurrencyResolver._collect_price_currencies(child, out)
