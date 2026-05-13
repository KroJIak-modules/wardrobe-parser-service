from __future__ import annotations

from urllib.parse import unquote, urlparse
import requests
from app.core.exceptions import StorefrontBlockedError
from app.services.shopify_http_client import ShopifyHttpClient
from app.services.shopify_policies import ShopifySitemapPolicy


class ShopifySitemapDiscovery:
    @staticmethod
    def _ensure_storefront_not_blocked(base_url: str, timeout: int) -> None:
        response = requests.get(base_url.rstrip('/') + '/', timeout=timeout, headers=ShopifyHttpClient.HEADERS, allow_redirects=True)
        final_url = str(response.url or '').lower()
        body = (response.text or '').lower()
        is_password_gate = final_url.endswith('/password') or '/password' in final_url
        if not is_password_gate:
            # Avoid false positives from storefront scripts/translations that may contain these words.
            # Treat as password gate only when password-template/form markers are present.
            has_password_marker = any(
                marker in body
                for marker in (
                    'action="/password"',
                    "action='/password'",
                    'name="password"',
                    "name='password'",
                    'id="password"',
                    "id='password'",
                    'templates/password',
                    'shopify-section-password',
                )
            )
            has_password_phrase = ('storefront password' in body) or ('enter using password' in body)
            is_password_gate = has_password_marker and has_password_phrase
        if is_password_gate:
            raise StorefrontBlockedError('storefront_password_gate')

    @staticmethod
    def discover_product_urls(base_url: str, timeout: int, policy: ShopifySitemapPolicy) -> list[str]:
        normalized_base_url = base_url.rstrip('/')
        ShopifySitemapDiscovery._ensure_storefront_not_blocked(normalized_base_url, timeout)
        base_host = (urlparse(normalized_base_url).netloc or '').lower()
        index_root = ShopifyHttpClient.get_xml_root(f'{normalized_base_url}/sitemap.xml', timeout, request_retries=policy.request_retries)

        product_sitemaps: list[str] = []
        for loc in index_root.findall('.//{*}sitemap/{*}loc'):
            sitemap_url = (loc.text or '').strip()
            if 'sitemap_products_' not in sitemap_url:
                continue
            parsed = urlparse(sitemap_url)
            if (parsed.netloc or '').lower() != base_host:
                continue
            path = (parsed.path or '').strip('/')
            file_name = path.rsplit('/', 1)[-1]
            if not policy.include_locale_sitemaps and path != file_name:
                continue
            if not file_name.startswith('sitemap_products_'):
                continue
            if sitemap_url not in product_sitemaps:
                product_sitemaps.append(sitemap_url)

        urls: list[str] = []
        seen_handles: set[str] = set()
        for sitemap_url in product_sitemaps:
            sitemap_root = ShopifyHttpClient.get_xml_root(sitemap_url, timeout, request_retries=policy.request_retries)
            for loc in sitemap_root.findall('.//{*}url/{*}loc'):
                product_url = (loc.text or '').strip()
                if '/products/' not in product_url:
                    continue
                handle = ShopifySitemapDiscovery.extract_handle(product_url)
                if not handle or handle in seen_handles:
                    continue
                seen_handles.add(handle)
                urls.append(f'{normalized_base_url}/products/{handle}')
                if len(urls) >= policy.max_products:
                    return urls
        return urls

    @staticmethod
    def extract_handle(url: str) -> str:
        parsed = urlparse(str(url or '').strip())
        chunks = [chunk for chunk in (parsed.path or '').strip('/').split('/') if chunk]
        for idx, chunk in enumerate(chunks):
            if chunk == 'products' and idx + 1 < len(chunks):
                return unquote(chunks[idx + 1]).strip()
        return unquote(chunks[-1]).strip() if chunks else ''
