import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup

from app.parsers.types import ParsedProduct


@dataclass
class SelectorConfig:
    listing_url: str
    item_selector: str
    name_selector: str
    link_selector: str
    price_selector: str | None = None
    image_selector: str | None = None
    category_selector: str | None = None
    description_selector: str | None = None
    external_id_attr: str | None = None


class SelectorParser:
    def __init__(self, config: SelectorConfig) -> None:
        self.config = config

    def parse(self, html: str) -> list[ParsedProduct]:
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(self.config.item_selector)
        parsed: list[ParsedProduct] = []
        for item in items:
            name_node = item.select_one(self.config.name_selector)
            link_node = item.select_one(self.config.link_selector)
            if not name_node or not link_node:
                continue
            name = name_node.get_text(strip=True)
            link = link_node.get("href") or ""
            external_id = self._extract_external_id(item, link)
            price = self._extract_price(item)
            currency = self._extract_currency(item)
            image_url = self._extract_attr(item, self.config.image_selector, "src")
            category = self._extract_text(item, self.config.category_selector)
            description = self._extract_text(item, self.config.description_selector)
            parsed.append(
                ParsedProduct(
                    external_id=external_id,
                    name=name,
                    category=category,
                    price=price,
                    currency=currency,
                    product_url=link,
                    image_url=image_url,
                    description=description,
                    raw_data=None,
                )
            )
        return parsed

    def _extract_text(self, item, selector: str | None) -> str | None:
        if not selector:
            return None
        node = item.select_one(selector)
        if not node:
            return None
        return node.get_text(strip=True)

    def _extract_attr(self, item, selector: str | None, attr: str) -> str | None:
        if not selector:
            return None
        node = item.select_one(selector)
        if not node:
            return None
        return node.get(attr)

    def _extract_external_id(self, item, fallback: str) -> str:
        if self.config.external_id_attr:
            value = item.get(self.config.external_id_attr)
            if value:
                return value
        return fallback

    def _extract_price(self, item) -> float | None:
        if not self.config.price_selector:
            return None
        node = item.select_one(self.config.price_selector)
        if not node:
            return None
        text = node.get_text(strip=True)
        cleaned = re.sub(r"[^0-9.,]", "", text)
        cleaned = cleaned.replace(",", ".")
        try:
            return float(Decimal(cleaned))
        except (InvalidOperation, ValueError):
            return None

    def _extract_currency(self, item) -> str | None:
        if not self.config.price_selector:
            return None
        node = item.select_one(self.config.price_selector)
        if not node:
            return None
        text = node.get_text(strip=True)
        if "$" in text:
            return "USD"
        if "EUR" in text or "€" in text:
            return "EUR"
        if "GBP" in text or "£" in text:
            return "GBP"
        return None
