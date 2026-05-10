from __future__ import annotations
import json
import re
from xml.etree import ElementTree

import requests
from app.adapters.contracts import StrategyContext


class BrowserExportStrategy:
    name = 'browser_export'

    def run(self, context: StrategyContext) -> list[dict]:
        cfg = context.source.source_config
        if cfg.get('use_fixture_payloads') is True:
            fixtures = cfg.get('strategy_payloads', {}).get(self.name, [])
            return fixtures if isinstance(fixtures, list) else []

        base_url = context.source.source_url.rstrip('/')
        timeout = int(cfg.get('timeouts', {}).get('product_sec', 10))
        sitemap_url = f'{base_url}/sitemap_products_1.xml'
        response = requests.get(sitemap_url, timeout=timeout)
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        product_urls = [(loc.text or '').strip() for loc in root.findall('.//{*}url/{*}loc') if (loc.text or '').strip()]

        out: list[dict] = []
        for url in product_urls:
            out.append(self._from_jsonld(url, timeout))
        return out

    @staticmethod
    def _from_jsonld(url: str, timeout: int) -> dict:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        html = response.text
        scripts = re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        product = None
        for raw in scripts:
            try:
                payload = json.loads(raw.strip())
            except json.JSONDecodeError:
                continue
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if isinstance(item, dict) and item.get('@type') == 'Product':
                    product = item
                    break
            if product:
                break
        if not product:
            return {'url': url, 'title': '', 'price': None, 'currency': 'USD', 'weight_grams': None, 'variants': []}

        offers = product.get('offers', {})
        if isinstance(offers, list):
            offer0 = offers[0] if offers else {}
        else:
            offer0 = offers if isinstance(offers, dict) else {}
        image = product.get('image')
        image_url = image[0] if isinstance(image, list) and image else (image if isinstance(image, str) else '')
        return {
            'url': url,
            'handle': '',
            'title': str(product.get('name') or '').strip(),
            'price': offer0.get('price'),
            'currency': str(offer0.get('priceCurrency') or 'USD'),
            'weight_grams': None,
            'variants': [{'title': 'default', 'available': True}],
            'image_url': str(image_url).strip(),
        }
