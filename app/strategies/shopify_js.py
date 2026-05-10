from __future__ import annotations
import json
import re
from xml.etree import ElementTree

import requests
from app.adapters.contracts import StrategyContext


class ShopifyJsStrategy:
    name = 'shopify_js'

    def run(self, context: StrategyContext) -> list[dict]:
        cfg = context.source.source_config
        if cfg.get('use_fixture_payloads') is True:
            fixtures = cfg.get('strategy_payloads', {}).get(self.name, [])
            return fixtures if isinstance(fixtures, list) else []

        base_url = context.source.source_url.rstrip('/')
        timeout = int(cfg.get('timeouts', {}).get('product_sec', 10))
        product_urls = self._get_product_urls(base_url, timeout)
        out: list[dict] = []
        for url in product_urls:
            item = self._parse_product_page(url, timeout)
            if item:
                out.append(item)
        return out

    @staticmethod
    def _get_product_urls(base_url: str, timeout: int) -> list[str]:
        sitemap_url = f'{base_url}/sitemap_products_1.xml'
        response = requests.get(sitemap_url, timeout=timeout)
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        urls: list[str] = []
        for loc in root.findall('.//{*}url/{*}loc'):
            val = (loc.text or '').strip()
            if val and '/products/' in val:
                urls.append(val)
        return urls

    @staticmethod
    def _parse_product_page(url: str, timeout: int) -> dict | None:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        html = response.text
        match = re.search(r'var\s+meta\s*=\s*(\{.*?\});', html, re.DOTALL)
        title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        title = (title_match.group(1).strip() if title_match else '').split('|')[0].strip()
        if not match:
            return {'url': url, 'title': title, 'price': None, 'currency': 'USD', 'weight_grams': None, 'variants': []}
        try:
            meta = json.loads(match.group(1))
        except json.JSONDecodeError:
            return {'url': url, 'title': title, 'price': None, 'currency': 'USD', 'weight_grams': None, 'variants': []}

        product = meta.get('product') if isinstance(meta, dict) else {}
        variants = product.get('variants') if isinstance(product, dict) else []
        first_variant = variants[0] if isinstance(variants, list) and variants else {}
        image_url = ''
        featured = product.get('featured_image') if isinstance(product, dict) else {}
        if isinstance(featured, dict):
            image_url = str(featured.get('src') or '').strip()
        return {
            'url': url,
            'handle': str(product.get('handle') or '').strip() if isinstance(product, dict) else '',
            'title': str(product.get('title') or title).strip() if isinstance(product, dict) else title,
            'price': first_variant.get('price'),
            'currency': 'USD',
            'weight_grams': first_variant.get('grams'),
            'variants': variants if isinstance(variants, list) else [],
            'image_url': image_url,
        }
