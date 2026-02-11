from pathlib import Path

import requests

from app.core.config import settings
from app.parsers.selector_parser import SelectorConfig, SelectorParser
from app.parsers.types import ParsedProduct

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "example_site.html"


class ExampleParser:
    def __init__(self) -> None:
        self.config = SelectorConfig(
            listing_url=settings.example_site_url,
            item_selector=".product-card",
            name_selector=".product-card__name",
            link_selector=".product-card__link",
            price_selector=".product-card__price",
            image_selector=".product-card__image",
            category_selector=".product-card__category",
            description_selector=".product-card__description",
            external_id_attr="data-external-id",
        )
        self.selector = SelectorParser(self.config)

    def parse(self) -> list[ParsedProduct]:
        html = self._load_html()
        return self.selector.parse(html)

    def _load_html(self) -> str:
        if settings.example_site_use_fixture and _FIXTURE_PATH.exists():
            return _FIXTURE_PATH.read_text(encoding="utf-8")
        response = requests.get(self.config.listing_url, timeout=settings.request_timeout_sec)
        response.raise_for_status()
        return response.text
