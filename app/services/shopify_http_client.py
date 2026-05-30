from __future__ import annotations

from dataclasses import dataclass
import random
import time
from typing import Any
from xml.etree import ElementTree

import requests


@dataclass(frozen=True)
class ShopifyHttpResult:
    status_code: int
    text: str
    payload: Any | None


class ShopifyHttpClient:
    # A realistic browser profile significantly reduces false 403/anti-bot responses
    # on storefront endpoints such as /sitemap.xml and /products/*.js.
    # Keep profile browser-like to reduce WAF false positives on public storefront resources.
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "DNT": "1",
        "Sec-CH-UA": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Linux"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    XML_HEADERS = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "application/xml,text/xml,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": HEADERS["Accept-Language"],
        "Cache-Control": HEADERS["Cache-Control"],
        "Pragma": HEADERS["Pragma"],
    }

    RETRYABLE_STATUS_CODES = {403, 408, 409, 425, 429, 500, 502, 503, 504}
    DEFAULT_RETRY_BACKOFF_SEC = (0.8, 1.8, 3.2, 5.0)

    @staticmethod
    def _request_with_retry(
        *,
        method: str,
        url: str,
        timeout: int,
        headers: dict[str, str],
        params: dict[str, object] | None = None,
        request_retries: int = 0,
    ) -> requests.Response:
        attempts = max(1, int(request_retries) + 1)
        backoffs = ShopifyHttpClient.DEFAULT_RETRY_BACKOFF_SEC
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    params=params,
                    timeout=timeout,
                    headers=headers,
                    allow_redirects=True,
                )
                if response.status_code not in ShopifyHttpClient.RETRYABLE_STATUS_CODES:
                    return response
                # Retry only if we still have attempts.
                if attempt >= attempts - 1:
                    return response
            except requests.RequestException as exc:
                last_exc = exc
                if attempt >= attempts - 1:
                    raise
            wait_s = backoffs[min(attempt, len(backoffs) - 1)]
            wait_s += random.uniform(0.05, 0.35)
            time.sleep(wait_s)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"request failed without response: {url}")

    @staticmethod
    def get_response(
        url: str,
        timeout: int,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, object] | None = None,
        request_retries: int = 0,
    ) -> requests.Response:
        return ShopifyHttpClient._request_with_retry(
            method="GET",
            url=url,
            params=params,
            timeout=timeout,
            headers=headers or ShopifyHttpClient.HEADERS,
            request_retries=request_retries,
        )

    @staticmethod
    def get_json(
        url: str,
        timeout: int,
        *,
        params: dict[str, object] | None = None,
        request_retries: int = 0,
    ) -> ShopifyHttpResult:
        response = ShopifyHttpClient.get_response(url, timeout, params=params, request_retries=request_retries)
        payload: Any | None = None
        try:
            payload = response.json()
        except Exception:
            payload = None
        return ShopifyHttpResult(status_code=response.status_code, text=response.text, payload=payload)

    @staticmethod
    def get_text(url: str, timeout: int, *, request_retries: int = 0) -> ShopifyHttpResult:
        response = ShopifyHttpClient.get_response(url, timeout, request_retries=request_retries)
        return ShopifyHttpResult(status_code=response.status_code, text=response.text, payload=None)

    @staticmethod
    def get_xml_root(url: str, timeout: int, *, request_retries: int) -> ElementTree.Element:
        response = ShopifyHttpClient.get_response(
            url,
            timeout,
            headers=ShopifyHttpClient.XML_HEADERS,
            request_retries=request_retries,
        )
        response.raise_for_status()
        return ElementTree.fromstring(response.text)
