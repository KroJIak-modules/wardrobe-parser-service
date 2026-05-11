from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from app.adapters.contracts import StrategyContext
from app.services.run_logger import RunLogger


class StoreBacklashColormeStrategy:
    name = 'store_backlash_colorme'
    _ua = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    _ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

    def run(self, context: StrategyContext) -> list[dict]:
        logger = RunLogger(context.run_id)
        base_url = context.source.source_url.rstrip('/')
        timeout = int((context.source.source_config.get('timeouts') or {}).get('product_sec', 15))
        logger.strategy_event('progress', self.name, stage='discover_start', base_url=base_url, timeout=timeout)
        product_urls = self._candidate_urls_or_discover(context, base_url, timeout)
        logger.strategy_event('progress', self.name, stage='discover_done', discovered=len(product_urls))
        out: list[dict] = []
        for idx, url in enumerate(product_urls, start=1):
            try:
                out.append(self._fetch_one(url, timeout))
            except Exception as exc:
                if idx <= 5 or idx % 100 == 0:
                    logger.strategy_event('progress', self.name, stage='fetch_skip', index=idx, reason=str(exc))
                continue
            logger.strategy_event('progress', self.name, stage='fetch_progress', processed=f'{idx}/{len(product_urls)}', parsed=len(out))
        context.diagnostics.update(
            {
                'candidate_urls': len(product_urls),
                'mapped_products': len(out),
            }
        )
        logger.strategy_event('progress', self.name, stage='run_done', parsed=len(out), discovered=len(product_urls))
        return out

    def _candidate_urls_or_discover(self, context: StrategyContext, base_url: str, timeout: int) -> list[str]:
        candidates = [str(x).strip() for x in context.candidate_urls if str(x).strip()]
        if candidates:
            return candidates
        sitemap_url = f'{base_url}/sitemap.xml'
        response = requests.get(sitemap_url, timeout=timeout, headers={'User-Agent': self._ua})
        response.raise_for_status()
        root = ET.fromstring(response.text)
        locs = [node.text.strip() for node in root.findall('.//sm:loc', self._ns) if node.text]
        return [x for x in locs if self._parse_pid_from_url(x).isdigit()]

    def _fetch_one(self, url: str, timeout: int) -> dict:
        response = requests.get(url, timeout=timeout, headers={'User-Agent': self._ua})
        response.raise_for_status()
        html = response.content.decode('euc_jp', errors='ignore')
        payload = self._extract_colorme_payload(html)
        product = payload.get('product') if isinstance(payload.get('product'), dict) else {}
        variants_raw = product.get('variants') if isinstance(product.get('variants'), list) else []
        variants = self._map_variants(variants_raw)
        base_price = product.get('sales_price_including_tax')
        if base_price in (None, ''):
            base_price = product.get('sales_price')
        pid = self._parse_pid_from_url(url)
        return {
            'url': url,
            'handle': f'pid-{pid}' if pid else '',
            'title': self._clean_text(product.get('name')),
            'description': self._extract_description(html),
            'vendor': 'BACKLASH',
            'product_type': '',
            'price': base_price,
            'currency': 'JPY',
            'image_url': '',
            'images': self._extract_image_urls(html),
            'variants': variants,
            'tags': [],
        }

    @staticmethod
    def _extract_colorme_payload(html: str) -> dict:
        match = re.search(r'var\s+Colorme\s*=\s*(\{.*?\});', html, flags=re.S)
        if not match:
            raise RuntimeError('colorme_payload_not_found')
        return json.loads(match.group(1))

    @staticmethod
    def _parse_pid_from_url(url: str) -> str:
        query = parse_qs(urlparse(url).query)
        return (query.get('pid') or [''])[0].strip()

    @staticmethod
    def _extract_description(html: str) -> str:
        soup = BeautifulSoup(html, 'html.parser')
        node = soup.select_one('.product_exp')
        return node.get_text('\n', strip=True) if node else ''

    def _extract_image_urls(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, 'html.parser')
        urls: list[str] = []
        for img in soup.select('.product_image_thumb img, .product_image_main img'):
            src = (img.get('src') or '').strip()
            if not src:
                continue
            if src.startswith('//'):
                src = f'https:{src}'
            elif src.startswith('/'):
                src = f'https://store-backlash.jp{src}'
            low = src.lower()
            if low.endswith('/left.png') or low.endswith('/right.png'):
                continue
            if '/etc/left.png' in low or '/etc/right.png' in low:
                continue
            urls.append(src)
        uniq: list[str] = []
        seen: set[str] = set()
        for item in urls:
            if item in seen:
                continue
            seen.add(item)
            uniq.append(item)
        return uniq

    def _map_variants(self, variants: list[dict]) -> list[dict]:
        out: list[dict] = []
        for variant in variants:
            stock_num = int(variant.get('stock_num') or 0)
            option_price = variant.get('option_price_including_tax')
            if option_price in (None, ''):
                option_price = variant.get('option_price')
            out.append(
                {
                    'id': variant.get('id'),
                    'title': self._clean_text(variant.get('title')),
                    'option1': self._clean_text(variant.get('option1_value')),
                    'option2': self._clean_text(variant.get('option2_value')),
                    'option3': None,
                    'sku': variant.get('model_number') or None,
                    'available': stock_num > 0,
                    'inventory_quantity': stock_num,
                    'price': option_price,
                    'compare_at_price': None,
                    'currency_code': 'JPY',
                }
            )
        return out

    @staticmethod
    def _clean_text(value: object) -> str:
        text = str(value or '').strip()
        text = text.replace('※SOLD OUT', '').replace('SOLD OUT', '')
        text = re.sub(r'\s{2,}', ' ', text).strip(' \u3000-–|/')
        return text
