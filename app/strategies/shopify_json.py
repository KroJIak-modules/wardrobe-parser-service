from __future__ import annotations
from collections import Counter
from collections.abc import Callable
from decimal import Decimal
import time

from app.adapters.contracts import StrategyContext
from app.adapters.base import BaseProductAdapter
from app.services.run_logger import RunLogger
from app.services.shopify_catalog_metadata_service import ShopifyCatalogMetadataService
from app.services.shopify_currency_resolver import ShopifyCurrencyResolver
from app.services.shopify_http_client import ShopifyHttpClient
from app.services.shopify_policies import ShopifyJsonQualityPolicy, ShopifyPolicyFactory
from app.services.shopify_weight_service import ShopifyWeightService


class ShopifyJsonStrategy:
    name = 'shopify_json'
    PAGE_LIMIT = 250

    def run(self, context: StrategyContext) -> list[dict]:
        cfg = context.source.source_config
        logger = RunLogger(context.run_id)
        if context.cancelled():
            return []

        base_url = context.source.source_url.rstrip('/')
        timeout = int(cfg.get('timeouts', {}).get('product_sec', 10))
        quality = ShopifyPolicyFactory.json_quality(cfg)
        sitemap_policy = ShopifyPolicyFactory.sitemap(cfg)
        currency_policy = ShopifyPolicyFactory.currency(cfg)
        storefront_currency = ''
        storefront_currency_source = 'disabled'
        preferred_currencies = list(currency_policy.preferred_currencies)
        request_mode = str(currency_policy.request_mode or 'prefer_list').strip().lower()
        fixed_currency = str(currency_policy.fixed_currency or '').strip().upper()
        fixed_country = str(currency_policy.fixed_country or '').strip().upper()
        request_without_currency = request_mode == 'fixed_ambient'
        if request_mode == 'fixed_param' and fixed_currency:
            effective_currency_priority = (fixed_currency,)
            storefront_currency = fixed_currency
            storefront_currency_source = 'shopify_market_fixed_param'
        elif request_without_currency:
            effective_currency_priority = ()
            if fixed_currency:
                storefront_currency = fixed_currency
                storefront_currency_source = 'shopify_market_fixed_ambient'
        elif preferred_currencies:
            effective_currency_priority = tuple(preferred_currencies)
            storefront_currency = preferred_currencies[0]
            storefront_currency_source = 'shopify_market_preferred_currencies'
        else:
            effective_currency_priority = ()
        logger.strategy_event('start', self.name, base_url=base_url, max_products=sitemap_policy.max_products)
        unique: dict[int, dict] = {}
        fail_types: Counter[str] = Counter()
        candidate_handles = {
            self._extract_handle_from_url(x)
            for x in (context.candidate_urls or ())
            if str(x).strip()
        }
        candidate_handles.discard('')

        # Candidate-only probe/sync: avoid full catalog scan for a single URL.
        # This makes probe-by-url deterministic and fast even when URL is gone.
        if context.candidate_only and candidate_handles and len(candidate_handles) <= 20:
            direct_items = self._collect_direct_candidates(
                base_url,
                timeout,
                handles=tuple(sorted(candidate_handles)),
                storefront_currency=storefront_currency,
                currency_priority=effective_currency_priority,
                request_without_currency=request_without_currency,
                fixed_country=fixed_country,
                logger=logger,
                fail_types=fail_types,
                should_cancel=context.cancelled,
            )
            for item in direct_items:
                pid = item.get('id')
                if isinstance(pid, int):
                    unique[pid] = item
            context.diagnostics.update(
                {
                    'pages_fetched': 0,
                    'page_limit': self.PAGE_LIMIT,
                    'max_products': sitemap_policy.max_products,
                    'storefront_currency': storefront_currency,
                    'storefront_currency_source': storefront_currency_source,
                    'request_mode': request_mode,
                    'fixed_currency': fixed_currency,
                    'fixed_country': fixed_country,
                    'request_without_currency': int(request_without_currency),
                    'base_items': len(direct_items),
                    'dedup_items': len(unique),
                    'candidate_direct_only': 1,
                }
            )
            out = [
                self._map_product(
                    item,
                    base_url,
                    timeout,
                    quality=quality,
                    allowed_currencies=('EUR', 'USD', 'GBP', 'JPY'),
                    storefront_currency=storefront_currency,
                    fail_types=fail_types,
                )
                for item in unique.values()
            ]
            context.diagnostics.update(
                {
                    'fail_antibot': int(fail_types.get('antibot', 0)),
                    'fail_network': int(fail_types.get('network', 0)),
                    'fail_data': int(fail_types.get('data', 0)),
                    'fail_http_other': int(fail_types.get('http_other', 0)),
                    'js_enrich_price': int(fail_types.get('js_enrich_price', 0)),
                    'js_enrich_images': int(fail_types.get('js_enrich_images', 0)),
                }
            )
            logger.strategy_event('done', self.name, parsed=len(out), candidate_direct_only=1)
            return out

        http_client = ShopifyHttpClient()
        try:
            base_items, pages_fetched = self._collect_base_pages(
                base_url,
                timeout,
                http_client=http_client,
                quality=quality,
                max_products=sitemap_policy.max_products,
                storefront_currency=storefront_currency,
                currency_priority=effective_currency_priority,
                logger=logger,
                fail_types=fail_types,
                candidate_urls=tuple(context.candidate_urls or ()),
                request_without_currency=request_without_currency,
                fixed_country=fixed_country,
                should_cancel=context.cancelled,
            )
        finally:
            http_client.close()
        for item in base_items:
            pid = item.get('id')
            if isinstance(pid, int):
                unique[pid] = item
        logger.strategy_event('progress', self.name, pages_fetched=pages_fetched, base_items=len(base_items), dedup_items=len(unique))
        context.diagnostics.update(
            {
                'pages_fetched': pages_fetched,
                'page_limit': self.PAGE_LIMIT,
                'max_products': sitemap_policy.max_products,
                'storefront_currency': storefront_currency,
                'storefront_currency_source': storefront_currency_source,
                'request_mode': request_mode,
                'fixed_currency': fixed_currency,
                'fixed_country': fixed_country,
                'request_without_currency': int(request_without_currency),
                'base_items': len(base_items),
                'dedup_items': len(unique),
            }
        )
        out = [
            self._map_product(
                item,
                base_url,
                timeout,
                quality=quality,
                allowed_currencies=('EUR', 'USD', 'GBP', 'JPY'),
                storefront_currency=storefront_currency,
                fail_types=fail_types,
            )
            for item in unique.values()
        ]
        context.diagnostics.update(
            {
                'fail_antibot': int(fail_types.get('antibot', 0)),
                'fail_network': int(fail_types.get('network', 0)),
                'fail_data': int(fail_types.get('data', 0)),
                'fail_http_other': int(fail_types.get('http_other', 0)),
                'js_enrich_price': int(fail_types.get('js_enrich_price', 0)),
                'js_enrich_images': int(fail_types.get('js_enrich_images', 0)),
            }
        )
        logger.strategy_event('done', self.name, parsed=len(out))
        return out

    def _collect_base_pages(
        self,
        base_url: str,
        timeout: int,
        *,
        http_client: ShopifyHttpClient,
        quality: ShopifyJsonQualityPolicy,
        max_products: int,
        storefront_currency: str,
        currency_priority: tuple[str, ...],
        logger: RunLogger,
        fail_types: Counter[str],
        candidate_urls: tuple[str, ...] = (),
        request_without_currency: bool = False,
        fixed_country: str = "",
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[list[dict], int]:
        out: list[dict] = []
        seen_signatures: set[str] = set()
        failed_pages: list[int] = []
        pages_fetched = 0
        # Do not cap to a hardcoded small number (e.g. 20 pages = 5000 items),
        # otherwise large catalogs are truncated. Bound by sitemap max_products.
        if max_products > 0:
            max_pages_cap = max(1, (int(max_products) + self.PAGE_LIMIT - 1) // self.PAGE_LIMIT)
        else:
            # Fallback safety cap when max_products is not set.
            max_pages_cap = 500
        page = 1
        candidate_handles = {self._extract_handle_from_url(x) for x in candidate_urls if str(x).strip()}
        candidate_handles.discard('')
        while page <= max_pages_cap:
            if should_cancel is not None and should_cancel():
                logger.strategy_event('progress', self.name, stage='feed_canceled', pages_fetched=pages_fetched)
                break
            effective_before = min(len(out), max_products) if max_products > 0 else len(out)
            pre_pct = (effective_before / max_products) * 100 if max_products > 0 else 0
            logger.strategy_event(
                'progress',
                self.name,
                stage='fetch_progress',
                processed=f'{effective_before}/{max_products}',
                pct=f'{pre_pct:.2f}',
                page=page,
                pages_fetched=pages_fetched,
            )
            items, state = self._fetch_products_page_with_retry(
                base_url,
                timeout,
                http_client=http_client,
                page=page,
                storefront_currency=storefront_currency,
                currency_priority=currency_priority,
                quality=quality,
                request_without_currency=request_without_currency,
                fixed_country=fixed_country,
            )
            if items is None:
                fail_types[state or 'http_other'] += 1
                if state == 'antibot':
                    time.sleep(quality.antibot_pause_sec)
                failed_pages.append(page)
                fail_effective = min(len(out), max_products) if max_products > 0 else len(out)
                fail_pct = (fail_effective / max_products) * 100 if max_products > 0 else 0
                logger.strategy_event(
                    'progress',
                    self.name,
                    stage='fetch_skip',
                    processed=f'{fail_effective}/{max_products}',
                    pct=f'{fail_pct:.2f}',
                    page=page,
                    reason=state or 'http_other',
                )
                page += 1
                continue
            pages_fetched += 1
            if not items:
                break
            signature = self._page_signature(items)
            if signature in seen_signatures:
                logger.strategy_event('page_loop_detected', self.name, page=page, pages_fetched=pages_fetched)
                break
            seen_signatures.add(signature)
            out.extend(items)
            effective_after = min(len(out), max_products) if max_products > 0 else len(out)
            post_pct = (effective_after / max_products) * 100 if max_products > 0 else 100
            logger.strategy_event(
                'progress',
                self.name,
                stage='fetch_progress',
                processed=f'{effective_after}/{max_products}',
                pct=f'{post_pct:.2f}',
                page=page,
                pages_fetched=pages_fetched,
                page_items=len(items),
            )
            if len(items) < self.PAGE_LIMIT:
                break
            if candidate_handles:
                collected_handles = {
                    str(item.get('handle') or '').strip()
                    for item in out
                    if isinstance(item, dict) and str(item.get('handle') or '').strip()
                }
                if candidate_handles.issubset(collected_handles):
                    logger.strategy_event(
                        'progress',
                        self.name,
                        stage='candidate_cover_reached',
                        candidate_total=len(candidate_handles),
                        page=page,
                        pages_fetched=pages_fetched,
                    )
                    break
            # Keep a consistent request cadence. A large catalogue is still fast
            # (250 products per request), while storefront WAFs no longer see a burst.
            if quality.page_interval_sec > 0:
                time.sleep(quality.page_interval_sec)
            page += 1
        if failed_pages:
            # Revisit only the pages the storefront refused. Do not fan out to
            # thousands of product .js endpoints: that both triggers WAFs and
            # makes a normal source run take far longer than the catalogue itself.
            if should_cancel is not None and should_cancel():
                return out, pages_fetched
            if quality.antibot_pause_sec > 0:
                time.sleep(quality.antibot_pause_sec)
            recovered = 0
            for page in failed_pages:
                items, _state = self._fetch_products_page_with_retry(
                    base_url,
                    timeout,
                    http_client=http_client,
                    page=page,
                    storefront_currency=storefront_currency,
                    currency_priority=currency_priority,
                    quality=quality,
                    request_without_currency=request_without_currency,
                    fixed_country=fixed_country,
                )
                if items:
                    out.extend(items)
                    recovered += 1
                elif _state:
                    fail_types[_state] += 1
                if quality.page_interval_sec > 0:
                    time.sleep(quality.page_interval_sec)
            logger.strategy_event('second_pass_done', self.name, recovered_pages=recovered, still_failed=len(failed_pages) - recovered)
        # Candidate sync must never publish items the saved links did not ask
        # for: the feed scan may only stop early, it may not widen the result.
        if candidate_handles:
            out = [
                item
                for item in out
                if isinstance(item, dict) and str(item.get('handle') or '').strip() in candidate_handles
            ]
        if max_products > 0 and out:
            out = self._prioritize_by_candidates(out, candidate_handles, max_products)
        return out, pages_fetched

    def _collect_direct_candidates(
        self,
        base_url: str,
        timeout: int,
        *,
        handles: tuple[str, ...],
        storefront_currency: str,
        currency_priority: tuple[str, ...],
        request_without_currency: bool,
        fixed_country: str,
        logger: RunLogger,
        fail_types: Counter[str],
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[dict]:
        out: list[dict] = []
        for handle in handles:
            if should_cancel is not None and should_cancel():
                logger.strategy_event('progress', self.name, stage='candidate_direct_canceled', collected=len(out))
                break
            item, state = self._fetch_product_by_handle(
                base_url,
                timeout,
                handle=handle,
                storefront_currency=storefront_currency,
                currency_priority=currency_priority,
                request_without_currency=request_without_currency,
                fixed_country=fixed_country,
            )
            if item is None:
                if state:
                    fail_types[state] += 1
                logger.strategy_event('progress', self.name, stage='candidate_direct_miss', handle=handle, reason=state or 'not_found')
                continue
            out.append(item)
            logger.strategy_event('progress', self.name, stage='candidate_direct_hit', handle=handle)
        return out

    @staticmethod
    def _prioritize_by_candidates(items: list[dict], candidate_handles: set[str], max_products: int) -> list[dict]:
        by_candidate: list[dict] = []
        by_other: list[dict] = []
        seen_handles: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            handle = str(item.get('handle') or '').strip()
            if not handle or handle in seen_handles:
                continue
            seen_handles.add(handle)
            if handle in candidate_handles:
                by_candidate.append(item)
            else:
                by_other.append(item)
        ordered = by_candidate + by_other
        return ordered[:max_products]

    @staticmethod
    def _extract_handle_from_url(url: str) -> str:
        parts = [p for p in str(url or '').strip().split('/') if p]
        for i, p in enumerate(parts):
            if p == 'products' and i + 1 < len(parts):
                return parts[i + 1].strip()
        return ''

    @staticmethod
    def _page_signature(items: list[dict]) -> str:
        first_id = items[0].get('id') if items and isinstance(items[0], dict) else ''
        last_id = items[-1].get('id') if items and isinstance(items[-1], dict) else ''
        return f'{len(items)}:{first_id}:{last_id}'

    def _fetch_products_page(
        self,
        base_url: str,
        timeout: int,
        *,
        http_client: ShopifyHttpClient,
        page: int,
        storefront_currency: str,
        currency_priority: tuple[str, ...],
        request_without_currency: bool = False,
        fixed_country: str = "",
    ) -> tuple[list[dict] | None, str | None]:
        if request_without_currency:
            currencies = [""]
        else:
            currencies = [x for x in currency_priority if x] or ([storefront_currency] if storefront_currency else [''])
        last_state: str | None = None
        for cur in currencies:
            try:
                params = {'limit': self.PAGE_LIMIT, 'page': page}
                params.update(self._shopify_market_params(currency=cur, fixed_country=fixed_country))
                response = http_client.get_json_with_session(f'{base_url}/products.json', params=params, timeout=timeout)
            except Exception:
                last_state = 'network'
                continue
            if response.status_code in {403, 429, 503}:
                return None, 'antibot'
            if response.status_code != 200:
                last_state = 'http_other'
                continue
            if not isinstance(response.payload, dict):
                last_state = 'data'
                continue
            items = response.payload.get('products', [])
            if not isinstance(items, list):
                last_state = 'data'
                continue
            return items, None
        return None, last_state or 'http_other'

    def _fetch_product_by_handle(
        self,
        base_url: str,
        timeout: int,
        *,
        handle: str,
        storefront_currency: str,
        currency_priority: tuple[str, ...],
        request_without_currency: bool = False,
        fixed_country: str = "",
    ) -> tuple[dict | None, str | None]:
        if not handle:
            return None, 'data'
        if request_without_currency:
            currencies = ['']
        else:
            currencies = [x for x in currency_priority if x] or ([storefront_currency] if storefront_currency else [''])
        last_state: str | None = None
        for cur in currencies:
            try:
                params: dict[str, str] = self._shopify_market_params(currency=cur, fixed_country=fixed_country)
                response = ShopifyHttpClient.get_json(
                    f'{base_url}/products/{handle}.js',
                    params=params,
                    timeout=timeout,
                )
            except Exception:
                last_state = 'network'
                continue
            if response.status_code in {403, 429, 503}:
                return None, 'antibot'
            if response.status_code == 404:
                last_state = 'http_other'
                continue
            if response.status_code != 200:
                last_state = 'http_other'
                continue
            if not isinstance(response.payload, dict):
                last_state = 'data'
                continue
            if not response.payload.get('id'):
                last_state = 'data'
                continue
            return self._normalize_js_product_payload(response.payload), None
        return None, last_state or 'http_other'

    @staticmethod
    def _normalize_js_product_payload(payload: dict) -> dict:
        product = dict(payload)
        raw_variants = product.get('variants') if isinstance(product.get('variants'), list) else []
        normalized_variants: list[dict] = []
        for variant in raw_variants:
            if not isinstance(variant, dict):
                continue
            normalized_variant = dict(variant)
            for field in ('price', 'compare_at_price'):
                value = normalized_variant.get(field)
                if isinstance(value, (int, float)):
                    normalized_variant[field] = f'{(Decimal(str(value)) / Decimal("100")):.2f}'
                    continue
                text = str(value or '').strip()
                if text.isdigit():
                    normalized_variant[field] = f'{(Decimal(text) / Decimal("100")):.2f}'
            normalized_variants.append(normalized_variant)
        product['variants'] = normalized_variants
        return product

    @staticmethod
    def _shopify_market_params(*, currency: str, fixed_country: str) -> dict[str, str]:
        params: dict[str, str] = {}
        if currency:
            params["currency"] = currency
        if fixed_country:
            params["country"] = fixed_country
        return params

    def _fetch_products_page_with_retry(
        self,
        base_url: str,
        timeout: int,
        *,
        http_client: ShopifyHttpClient,
        page: int,
        storefront_currency: str,
        currency_priority: tuple[str, ...],
        quality: ShopifyJsonQualityPolicy,
        request_without_currency: bool = False,
        fixed_country: str = "",
    ) -> tuple[list[dict] | None, str | None]:
        items, state = self._fetch_products_page(
            base_url,
            timeout,
            http_client=http_client,
            page=page,
            storefront_currency=storefront_currency,
            currency_priority=currency_priority,
            request_without_currency=request_without_currency,
            fixed_country=fixed_country,
        )
        if items is not None:
            return items, None
        for wait_s in quality.retry_backoff_sec:
            # A 403/429 is temporary storefront throttling. Retry the same
            # catalogue page after the configured cooling period instead of
            # abandoning it or fanning out into per-product requests.
            cooldown = max(wait_s, quality.antibot_pause_sec) if state == 'antibot' else wait_s
            time.sleep(cooldown)
            items, state = self._fetch_products_page(
                base_url,
                timeout,
                http_client=http_client,
                page=page,
                storefront_currency=storefront_currency,
                currency_priority=currency_priority,
                request_without_currency=request_without_currency,
                fixed_country=fixed_country,
            )
            if items is not None:
                return items, None
        return None, state

    @staticmethod
    def _map_product(
        item: dict,
        base_url: str,
        timeout: int,
        *,
        quality: ShopifyJsonQualityPolicy,
        allowed_currencies: tuple[str, ...],
        storefront_currency: str,
        fail_types: Counter[str],
    ) -> dict:
        handle = str(item.get('handle') or '').strip()
        variants = item.get('variants') or []
        price = ShopifyJsonStrategy._min_variant_price(variants if isinstance(variants, list) else [])
        currency = ShopifyJsonStrategy._resolve_currency(item.get('currency'), storefront_currency, allowed_currencies)
        if price is None and currency and handle and 'price' in quality.enrich_from_js_fields:
            js_price = ShopifyJsonStrategy._fallback_price_from_js(base_url, handle, currency, timeout)
            if js_price is not None:
                price = js_price
                fail_types['js_enrich_price'] += 1
        weight = ShopifyJsonStrategy._best_variant_weight(variants if isinstance(variants, list) else [])
        images = item.get('images') if isinstance(item.get('images'), list) else []
        image_url = ''
        if images:
            first = images[0]
            if isinstance(first, dict):
                image_url = ShopifyJsonStrategy._normalize_image_url(str(first.get('src') or '').strip(), base_url)
            elif isinstance(first, str):
                image_url = ShopifyJsonStrategy._normalize_image_url(first, base_url)
        if not image_url and handle and 'images' in quality.enrich_from_js_fields:
            js_images = ShopifyJsonStrategy._fallback_images_from_js(base_url, handle, timeout)
            if js_images:
                images = js_images
                image_url = ShopifyJsonStrategy._normalize_image_url(str(js_images[0]), base_url)
                fail_types['js_enrich_images'] += 1
        return {
            'url': f'{base_url}/products/{handle}' if handle else '',
            'handle': handle,
            'title': str(item.get('title') or '').strip(),
            'description': str(item.get('body_html') or item.get('description') or '').strip() or None,
            'published_at': str(item.get('published_at') or '').strip() or None,
            'designer': str(item.get('vendor') or '').strip(),
            # The catalog payload is the authoritative batch input. Fetching every
            # product page only to infer a missing category makes a source sync
            # network-bound and does not improve the published timestamp.
            'category': ShopifyCatalogMetadataService.resolve_category(item),
            'tags': BaseProductAdapter._normalize_tags(item.get('tags')),
            'price': price,
            'currency': currency,
            'source_weight_grams': weight,
            'variants': variants,
            'images': images,
            'image_url': image_url,
        }

    @staticmethod
    def _resolve_currency(raw_currency: object, storefront_currency: str, allowed_currencies: tuple[str, ...]) -> str:
        allowed = {ShopifyCurrencyResolver.normalize(x) for x in allowed_currencies}
        raw = ShopifyCurrencyResolver.normalize(raw_currency)
        if raw and raw in allowed:
            return raw
        storefront = ShopifyCurrencyResolver.normalize(storefront_currency)
        if storefront and storefront in allowed:
            return storefront
        return ''

    @staticmethod
    def _min_variant_price(variants: list[dict]) -> float | None:
        values: list[float] = []
        for v in variants:
            if not isinstance(v, dict):
                continue
            raw = v.get('price')
            try:
                val = float(raw)
            except Exception:
                continue
            if val > 0:
                values.append(val)
        return min(values) if values else None

    @staticmethod
    def _best_variant_weight(variants: list[dict]) -> int | None:
        return ShopifyWeightService.resolve_variant_weight_grams(
            [variant for variant in variants if isinstance(variant, dict)]
        )

    @staticmethod
    def _fallback_price_from_js(base_url: str, handle: str, currency: str, timeout: int) -> float | None:
        try:
            response = ShopifyHttpClient.get_json(f'{base_url}/products/{handle}.js', timeout)
            if response.status_code != 200:
                return None
            payload = response.payload if isinstance(response.payload, dict) else {}
            variants = payload.get('variants') or []
            minor_values: list[int] = []
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                raw = variant.get('price')
                try:
                    val = int(raw)
                except Exception:
                    continue
                if val > 0:
                    minor_values.append(val)
            if not minor_values:
                return None
            scale = ShopifyJsonStrategy._currency_scale(currency)
            return float(Decimal(min(minor_values)) / (Decimal(10) ** scale))
        except Exception:
            return None

    @staticmethod
    def _fallback_images_from_js(base_url: str, handle: str, timeout: int) -> list[str]:
        try:
            response = ShopifyHttpClient.get_json(f'{base_url}/products/{handle}.js', timeout)
            if response.status_code != 200:
                return []
            payload = response.payload if isinstance(response.payload, dict) else {}
            raw_images = payload.get('images') or []
            out: list[str] = []
            for raw in raw_images:
                if not isinstance(raw, str):
                    continue
                normalized = ShopifyJsonStrategy._normalize_image_url(raw, base_url)
                if normalized:
                    out.append(normalized)
            return out
        except Exception:
            return []

    @staticmethod
    def _normalize_image_url(value: str, base_url: str) -> str:
        raw = (value or '').strip()
        if not raw:
            return ''
        if raw.startswith('//'):
            return 'https:' + raw
        if raw.startswith('/'):
            return base_url.rstrip('/') + raw
        return raw

    @staticmethod
    def _currency_scale(currency: str) -> int:
        c = (currency or '').upper()
        if c in {'JPY', 'KRW', 'VND'}:
            return 0
        if c in {'BHD', 'IQD', 'JOD', 'KWD', 'LYD', 'OMR', 'TND'}:
            return 3
        return 2
