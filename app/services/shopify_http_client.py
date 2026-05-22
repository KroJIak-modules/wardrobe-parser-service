from __future__ import annotations

from dataclasses import dataclass
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
    }
    XML_HEADERS = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "application/xml,text/xml,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": HEADERS["Accept-Language"],
        "Cache-Control": HEADERS["Cache-Control"],
        "Pragma": HEADERS["Pragma"],
    }

    @staticmethod
    def get_json(url: str, timeout: int, *, params: dict[str, object] | None = None) -> ShopifyHttpResult:
        response = requests.get(
            url,
            params=params,
            timeout=timeout,
            headers=ShopifyHttpClient.HEADERS,
            allow_redirects=True,
        )
        payload: Any | None = None
        try:
            payload = response.json()
        except Exception:
            payload = None
        return ShopifyHttpResult(status_code=response.status_code, text=response.text, payload=payload)

    @staticmethod
    def get_text(url: str, timeout: int) -> ShopifyHttpResult:
        response = requests.get(
            url,
            timeout=timeout,
            headers=ShopifyHttpClient.HEADERS,
            allow_redirects=True,
        )
        return ShopifyHttpResult(status_code=response.status_code, text=response.text, payload=None)

    @staticmethod
    def get_xml_root(url: str, timeout: int, *, request_retries: int) -> ElementTree.Element:
        last_error: Exception | None = None
        attempts = max(1, request_retries + 1)
        for _ in range(attempts):
            try:
                response = requests.get(
                    url,
                    timeout=timeout,
                    headers=ShopifyHttpClient.XML_HEADERS,
                    allow_redirects=True,
                )
                response.raise_for_status()
                return ElementTree.fromstring(response.text)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError(f'failed to fetch xml: {url}')
