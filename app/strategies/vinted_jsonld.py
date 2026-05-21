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
        soup = BeautifulSoup(html, 'html.parser')
        item_id = self._extract_item_id(item_url)
        runtime_meta = self._extract_runtime_item_meta(html, item_id=item_id)
        try:
            payload = self._extract_product_ld_json(html)
        except Exception:
            payload = self._build_fallback_payload(soup, runtime_meta)
        dom_size, dom_color = self._extract_size_color_from_dom(soup)
        variant_title = self._build_variant_title(
            size=(runtime_meta.get('size') if isinstance(runtime_meta, dict) else None) or dom_size,
            color=(runtime_meta.get('color') if isinstance(runtime_meta, dict) else None) or dom_color,
        )
        product_type = self._extract_product_type(html)
        offers = payload.get('offers') if isinstance(payload.get('offers'), dict) else {}
        currency = str(offers.get('priceCurrency') or '').strip().upper()
        price = offers.get('price')
        availability = str(offers.get('availability') or '').strip().lower()
        available = 'instock' in availability or 'in_stock' in availability
        image_urls = list(runtime_meta.get('images') or []) or self._to_list_images(payload.get('image'))
        handle_match = re.search(r'/items/(\d+)', item_url)
        handle = f'item-{handle_match.group(1)}' if handle_match else ''
        brand = payload.get('brand') if isinstance(payload.get('brand'), dict) else {}
        vendor = str(brand.get('name') or '').strip()
        runtime_price = runtime_meta.get('price')
        runtime_total_price = runtime_meta.get('total_item_price')
        runtime_fee = runtime_meta.get('service_fee')
        runtime_currency = str(runtime_meta.get('currency') or '').strip().upper()
        runtime_available = runtime_meta.get('available')
        if runtime_currency and runtime_currency == currency:
            if runtime_price is not None:
                price = runtime_price
        if isinstance(runtime_available, bool):
            available = runtime_available
        variant = {
            'id': handle,
            'title': variant_title,
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
        out = {
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
            'status': 'available' if bool(available) else 'out_of_stock',
        }
        if runtime_total_price is not None:
            out['buyer_total_price'] = runtime_total_price
        if runtime_fee is not None:
            out['buyer_service_fee'] = runtime_fee
        return out

    @staticmethod
    def _extract_item_id(item_url: str) -> str:
        match = re.search(r'/items/(\d+)', item_url)
        return str(match.group(1)) if match else ''

    @staticmethod
    def _extract_runtime_item_meta(html: str, *, item_id: str) -> dict:
        if not item_id:
            return {}
        marker = f'\\"id\\":{item_id}'
        start = html.find(marker)
        if start < 0:
            return {}
        # Localized chunk around target item payload in hydration script.
        chunk = html[start:start + 220_000]
        if not chunk:
            return {}

        def _extract_money(key: str) -> tuple[float | None, str | None]:
            pattern = rf'\\"{re.escape(key)}\\":\{{\\"amount\\":\\"([0-9]+(?:\.[0-9]+)?)\\",\\"currency_code\\":\\"([A-Z]{{3}})\\"\}}'
            m = re.search(pattern, chunk)
            if not m:
                return None, None
            try:
                return float(m.group(1)), str(m.group(2)).strip().upper()
            except Exception:
                return None, None

        def _extract_photos_block() -> str:
            token = '\\"photos\\":['
            pos = chunk.find(token)
            if pos < 0:
                return ''
            i = pos + len(token) - 1  # points to '['
            depth = 0
            in_string = False
            escaped = False
            end = -1
            while i < len(chunk):
                ch = chunk[i]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == '\\':
                        escaped = True
                    elif ch == '"':
                        in_string = False
                else:
                    if ch == '"':
                        in_string = True
                    elif ch == '[':
                        depth += 1
                    elif ch == ']':
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
                i += 1
            if end < 0:
                return ''
            return chunk[pos + len(token):end]

        price, currency = _extract_money('price')
        service_fee, fee_currency = _extract_money('service_fee')
        total_price, total_currency = _extract_money('total_item_price')
        photos_block = _extract_photos_block()
        # Grab full-size images from each photo object (ignore thumbnail URLs).
        photo_urls = re.findall(r'\\"image_no\\":\d+.*?\\"url\\":\\"(https:[^"]+?/f\d+/[^"]+)\\"', photos_block, re.S)
        dedup: list[str] = []
        seen: set[str] = set()
        for url in photo_urls:
            clean = str(url).replace('\\/', '/').strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            dedup.append(clean)
        out: dict = {}
        if dedup:
            out['images'] = dedup
        if price is not None:
            out['price'] = price
        if total_price is not None:
            out['total_item_price'] = total_price
        if service_fee is not None:
            out['service_fee'] = service_fee
        # Prefer item/base currency if present.
        out['currency'] = currency or total_currency or fee_currency
        size_match = re.search(r'\\"size_title\\":\\"([^"]*)\\"', chunk)
        color_match = re.search(r'\\"color1\\":\\"([^"]*)\\"', chunk)
        if size_match:
            out['size'] = str(size_match.group(1) or '').replace('\\/', '/').strip()
        if color_match:
            out['color'] = str(color_match.group(1) or '').replace('\\/', '/').strip()
        title_match = re.search(r'\\"title\\":\\"([^"]+)\\"', chunk)
        if title_match:
            out['title'] = str(title_match.group(1) or '').replace('\\/', '/').strip()
        # sold/hidden/closed item should be treated as unavailable.
        closing_match = re.search(r'\\"item_closing_action\\":\\"([^"]*)\\"', chunk)
        if closing_match:
            closing = str(closing_match.group(1) or '').strip().lower()
            if closing:
                out['available'] = closing not in {'sold', 'hidden', 'deleted', 'removed'}
        return out

    @staticmethod
    def _build_fallback_payload(soup: BeautifulSoup, runtime_meta: dict) -> dict:
        def _meta_value(*keys: str) -> str:
            for key in keys:
                node = soup.find('meta', attrs={'property': key}) or soup.find('meta', attrs={'name': key})
                if node is None:
                    continue
                value = str(node.get('content') or '').strip()
                if value:
                    return value
            return ''

        title = (
            str(runtime_meta.get('title') or '').strip()
            or _meta_value('og:title', 'twitter:title')
            or (soup.find('h1').get_text(' ', strip=True) if soup.find('h1') else '')
        )
        description = _meta_value('og:description', 'description', 'twitter:description')
        currency = str(runtime_meta.get('currency') or '').strip().upper()
        price = runtime_meta.get('price')
        availability = "InStock" if bool(runtime_meta.get('available', True)) else "OutOfStock"
        return {
            '@type': 'Product',
            'name': title,
            'description': description,
            'brand': {'name': ''},
            'offers': {
                'priceCurrency': currency,
                'price': price,
                'availability': availability,
            },
            'image': list(runtime_meta.get('images') or []),
        }

    @staticmethod
    def _build_variant_title(*, size: object, color: object) -> str:
        size_text = str(size or '').strip()
        color_text = str(color or '').strip()
        if size_text and color_text:
            return f"{size_text} / {color_text}"
        if size_text:
            return size_text
        if color_text:
            return color_text
        return "Default"

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
    def _extract_size_color_from_dom(soup: BeautifulSoup) -> tuple[str, str]:
        size_text = ""
        color_text = ""
        for row in soup.select('[class*="details"] [class*="item"]'):
            text = row.get_text(' ', strip=True)
            if not text:
                continue
            low = text.lower()
            if not size_text and low.startswith('size'):
                size_text = text[4:].strip(" :.-")
            elif not color_text and (low.startswith('color') or low.startswith('colour')):
                color_text = text[5:].strip(" :.-") if low.startswith('color') else text[6:].strip(" :.-")
            if size_text and color_text:
                break
        return size_text, color_text

    @staticmethod
    def _to_list_images(value: object) -> list[str]:
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        return []
