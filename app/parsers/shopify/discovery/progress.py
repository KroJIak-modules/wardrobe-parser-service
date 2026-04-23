"""Progress utilities for Shopify discovery."""

from __future__ import annotations

import time
from typing import Callable

from app.parsers.shopify_url_utils import append_discovered_url


class DiscoveryProgressEmitter:
    """Unified progress emitter for discovery stage."""

    def __init__(
        self,
        *,
        max_products: int,
        discovered_urls: list[str],
        discovered_set: set[str],
        on_progress: Callable[[], None] | None,
        on_detail_progress: Callable[[dict], None] | None,
    ) -> None:
        self.max_products = max_products
        self.discovered_urls = discovered_urls
        self.discovered_set = discovered_set
        self._on_progress = on_progress
        self._on_detail_progress = on_detail_progress
        self._appended_since_ping = 0

    def ping(self) -> None:
        if self._on_progress:
            self._on_progress()
        if self._on_detail_progress:
            self._on_detail_progress(
                {
                    "stage": "discovering_urls",
                    "products_processed": len(self.discovered_urls),
                }
            )

    def append_url(self, url: str) -> bool:
        before = len(self.discovered_urls)
        append_discovered_url(
            url,
            discovered_urls=self.discovered_urls,
            discovered_set=self.discovered_set,
            max_products=self.max_products,
        )
        added = len(self.discovered_urls) > before
        self._appended_since_ping += 1
        if self._appended_since_ping >= 100:
            self._appended_since_ping = 0
            self.ping()
        return added


def deadline_reached(deadline_monotonic: float | None) -> bool:
    return deadline_monotonic is not None and time.monotonic() >= deadline_monotonic
