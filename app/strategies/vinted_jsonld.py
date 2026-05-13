from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.adapters.contracts import StrategyContext
from app.services.run_logger import RunLogger


class VintedJsonLdStrategy:
    name = 'vinted_jsonld'
    _ua = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'

    def run(self, context: StrategyContext) -> list[dict]:
        logger = RunLogger(context.run_id)
        base_url = context.source.source_url.rstrip('/')
        timeout = int((context.source.source_config.get('timeouts') or {}).get('product_sec', 15))
        search_text = str((context.source.source_config.get('vinted') or {}).get('search_text') or 'nike').strip()
        logger.strategy_event('progress', self.name, stage='discover_start', base_url=base_url, search_text=search_text)
        item_urls = self._candidate_urls_or_discover(context, base_url, search_text, timeout)
        logger.strategy_event('progress', self.name, stage='discover_done', discovered=len(item_urls))
        workers = int(context.source.source_config.get('vinted_jsonld_workers') or 1)
        workers = max(1, workers)
        logger.strategy_event('progress', self.name, stage='fetch_start', total=len(item_urls), workers=workers)
        out: list[dict] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_idx: dict = {}
            for idx, item_url in enumerate(item_urls, start=1):
                future = pool.submit(self._fetch_one, item_url, timeout)
                future_to_idx[future] = idx
            processed = 0
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                processed += 1
                try:
                    out.append(future.result())
                except Exception as exc:
                    logger.strategy_event('progress', self.name, stage='fetch_skip', index=idx, reason=str(exc))
                logger.strategy_event('progress', self.name, stage='fetch_progress', processed=f'{processed}/{len(item_urls)}', parsed=len(out))
        context.diagnostics.update({'candidate_urls': len(item_urls), 'mapped_products': len(out), 'workers': workers})
        return out

    def _candidate_urls_or_discover(
        self,
        context: StrategyContext,
        base_url: str,
        search_text: str,
        timeout: int,
    ) -> list[str]:
        candidates = [str(x).strip() for x in context.candidate_urls if str(x).strip()]
        if candidates:
            return candidates
        catalog_url = f'{base_url}/catalog?search_text={search_text}'
        html = requests.get(catalog_url, timeout=timeout, headers={'User-Agent': self._ua}).text
        raw_matches = re.findall(r'/items/\d+[^"\s<]*', html)
        seen: set[str] = set()
        out: list[str] = []
        for raw in raw_matches:
            item_url = urljoin(base_url, raw)
            if item_url in seen:
                continue
            seen.add(item_url)
            out.append(item_url)
        return out

    def _fetch_one(self, item_url: str, timeout: int) -> dict:
        response = requests.get(item_url, timeout=timeout, headers={'User-Agent': self._ua})
        response.raise_for_status()
        html = response.text
        payload = self._extract_product_ld_json(html)
        product_type = self._extract_product_type(html)
        offers = payload.get('offers') if isinstance(payload.get('offers'), dict) else {}
        currency = str(offers.get('priceCurrency') or '').strip().upper()
        price = offers.get('price')
        availability = str(offers.get('availability') or '').strip().lower()
        available = 'instock' in availability or 'in_stock' in availability
        image_urls = self._to_list_images(payload.get('image'))
        handle_match = re.search(r'/items/(\d+)', item_url)
        handle = f'item-{handle_match.group(1)}' if handle_match else ''
        brand = payload.get('brand') if isinstance(payload.get('brand'), dict) else {}
        vendor = str(brand.get('name') or '').strip()
        variant = {
            'id': handle,
            'title': payload.get('name'),
            'option1': None,
            'option2': None,
            'option3': None,
            'sku': None,
            'available': bool(available),
            'inventory_quantity': None,
            'price': price,
            'compare_at_price': None,
            'currency_code': currency or None,
        }
        return {
            'url': item_url,
            'handle': handle,
            'title': payload.get('name'),
            'description': payload.get('description'),
            'vendor': vendor,
            'product_type': product_type,
            'price': price,
            'currency': currency or None,
            'image_url': image_urls[0] if image_urls else '',
            'images': image_urls,
            'variants': [variant],
            'tags': [],
        }

    @staticmethod
    def _extract_product_ld_json(html: str) -> dict:
        soup = BeautifulSoup(html, 'html.parser')
        for node in soup.find_all('script', attrs={'type': 'application/ld+json'}):
            text = (node.string or node.get_text() or '').strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get('@type') == 'Product':
                return payload
        raise RuntimeError('product_jsonld_not_found')

    @staticmethod
    def _extract_product_type(html: str) -> str | None:
        soup = BeautifulSoup(html, 'html.parser')
        catalog_crumbs: list[str] = []
        for a in soup.select('a[href*="/catalog/"]'):
            text = a.get_text(' ', strip=True)
            href = str(a.get('href') or '')
            if not text or 'brand/' in href:
                continue
            low = text.lower()
            if low in {'men', 'women', 'kids', 'clothing', 'accessories', 'shoes'}:
                continue
            catalog_crumbs.append(text)
        return catalog_crumbs[-1] if catalog_crumbs else None

    @staticmethod
    def _to_list_images(value: object) -> list[str]:
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        return []
