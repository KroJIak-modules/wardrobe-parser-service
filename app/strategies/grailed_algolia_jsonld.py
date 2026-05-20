from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from app.adapters.contracts import StrategyContext
from app.services.run_logger import RunLogger


class GrailedAlgoliaJsonLdStrategy:
    name = 'grailed_algolia_jsonld'
    _ua = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'

    def run(self, context: StrategyContext) -> list[dict]:
        logger = RunLogger(context.run_id)
        base_url = context.source.source_url.rstrip('/')
        timeout = int((context.source.source_config.get('timeouts') or {}).get('product_sec', 20))
        search_text = str((context.source.source_config.get('grailed') or {}).get('search_text') or 'leather jacket').strip()

        logger.strategy_event('progress', self.name, stage='discover_start', base_url=base_url, search_text=search_text)
        item_urls = self._candidate_urls_or_discover(context, base_url, search_text, timeout, logger)
        logger.strategy_event('progress', self.name, stage='discover_done', discovered=len(item_urls))

        workers = int(context.source.source_config.get('grailed_algolia_jsonld_workers') or 1)
        workers = max(1, workers)
        logger.strategy_event('progress', self.name, stage='fetch_start', total=len(item_urls), workers=workers)

        out: list[dict] = []
        total = len(item_urls)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_ctx: dict = {}
            for idx, item_url in enumerate(item_urls, start=1):
                future = pool.submit(self._fetch_one, item_url, timeout, logger)
                future_to_ctx[future] = (idx, item_url)
            processed = 0
            for future in as_completed(future_to_ctx):
                idx, item_url = future_to_ctx[future]
                processed += 1
                try:
                    out.append(future.result())
                except Exception as exc:
                    logger.strategy_event('progress', self.name, stage='fetch_skip', index=idx, url=item_url, reason=str(exc))
                logger.strategy_event('progress', self.name, stage='fetch_progress', processed=f'{processed}/{total}', parsed=len(out))

        context.diagnostics.update({'candidate_urls': total, 'mapped_products': len(out), 'workers': workers})
        return out

    def _candidate_urls_or_discover(
        self,
        context: StrategyContext,
        base_url: str,
        search_text: str,
        timeout: int,
        logger: RunLogger,
    ) -> list[str]:
        candidates = [str(x).strip() for x in context.candidate_urls if str(x).strip()]
        if candidates:
            return candidates

        app_id, api_key = self._extract_algolia_creds(base_url, timeout)
        logger.strategy_event('progress', self.name, stage='algolia_creds_ok', app_id=app_id)
        hits = self._query_algolia(app_id, api_key, search_text, timeout)
        logger.strategy_event('progress', self.name, stage='algolia_hits', count=len(hits))

        out: list[str] = []
        seen: set[str] = set()
        for hit in hits:
            item_url = self._hit_to_url(hit, base_url)
            if not item_url or item_url in seen:
                continue
            seen.add(item_url)
            out.append(item_url)
        return out

    def _extract_algolia_creds(self, base_url: str, timeout: int) -> tuple[str, str]:
        html = requests.get(base_url, timeout=timeout, headers={'User-Agent': self._ua}).text
        next_data_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, flags=re.S)
        if not next_data_match:
            raise RuntimeError('next_data_not_found')
        payload = json.loads(next_data_match.group(1))

        text = json.dumps(payload)
        app_match = re.search(r'"appId"\s*:\s*"([A-Z0-9]+)"', text)
        key_match = re.search(r'"publicSearchKey"\s*:\s*"([a-z0-9]+)"', text)
        if not app_match or not key_match:
            raise RuntimeError('algolia_creds_not_found')
        return app_match.group(1), key_match.group(1)

    def _query_algolia(self, app_id: str, api_key: str, search_text: str, timeout: int) -> list[dict]:
        url = f'https://{app_id}-dsn.algolia.net/1/indexes/Listing_production/query'
        params = f'query={quote(search_text)}&hitsPerPage=30&page=0'
        response = requests.post(
            url,
            headers={
                'User-Agent': self._ua,
                'X-Algolia-Application-Id': app_id,
                'X-Algolia-API-Key': api_key,
                'Content-Type': 'application/json',
            },
            json={'params': params},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        hits = payload.get('hits')
        return hits if isinstance(hits, list) else []

    @staticmethod
    def _hit_to_url(hit: dict, base_url: str) -> str:
        if not isinstance(hit, dict):
            return ''
        slug = str(hit.get('slug') or '').strip()
        if slug:
            return urljoin(base_url, f'/listings/{slug}')
        listing_id = hit.get('id')
        if listing_id is None:
            return ''
        return urljoin(base_url, f'/listings/{listing_id}')

    def _fetch_one(self, item_url: str, timeout: int, logger: RunLogger) -> dict:
        response = requests.get(item_url, timeout=timeout, headers={'User-Agent': self._ua}, allow_redirects=True)
        response.raise_for_status()
        final_url = response.url
        payload = self._extract_product_ld_json(response.text)
        next_data_images = self._extract_images_from_next_data(response.text)

        offers = payload.get('offers') if isinstance(payload.get('offers'), dict) else {}
        currency = str(offers.get('priceCurrency') or '').strip().upper()
        price = offers.get('price')
        availability = str(offers.get('availability') or '').strip().lower()
        available = 'instock' in availability or 'in_stock' in availability
        image_urls = next_data_images or self._to_list_images(payload.get('image'))
        handle = final_url.rstrip('/').split('/')[-1]
        brand = payload.get('brand') if isinstance(payload.get('brand'), dict) else {}
        vendor = str(brand.get('name') or '').strip()

        logger.strategy_event('progress', self.name, stage='item_parsed', handle=handle, images=len(image_urls))
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
            'url': final_url,
            'handle': handle,
            'title': payload.get('name'),
            'description': payload.get('description'),
            'vendor': vendor,
            'product_type': self._extract_product_type(response.text),
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
        crumbs = [x.get_text(' ', strip=True) for x in soup.select('a[href*="/designers/"]')]
        return crumbs[0] if crumbs else None

    @staticmethod
    def _to_list_images(value: object) -> list[str]:
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        return []

    @staticmethod
    def _extract_images_from_next_data(html: str) -> list[str]:
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, flags=re.S)
        if not match:
            return []
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []
        listing = (
            (payload.get('props') or {})
            .get('pageProps', {})
            .get('listing', {})
        )
        photos = listing.get('photos') if isinstance(listing, dict) else None
        if not isinstance(photos, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for photo in photos:
            if not isinstance(photo, dict):
                continue
            # Grailed stores image URL under `url`; use exact value to avoid quality regressions.
            url = str(photo.get('url') or '').strip()
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(url)
        return out
