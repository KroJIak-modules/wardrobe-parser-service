from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.core.config import settings
from app.parsers.http_client import HttpClient
from app.parsers.types import ParsedProduct


@dataclass
class Collection:
    name: str
    url: str


class NoFaithStudiosParser:
    def __init__(self) -> None:
        self.base_url = settings.nofaithstudios_base_url.rstrip("/")
        self.client = HttpClient("nofaithstudios")

    def parse(self) -> list[ParsedProduct]:
        collections = self._fetch_collections()
        products: dict[str, ParsedProduct] = {}
        for collection in collections:
            for item in self._parse_collection(collection):
                existing = products.get(item.external_id)
                if existing:
                    self._append_category(existing, collection.name)
                    continue
                self._append_category(item, collection.name)
                products[item.external_id] = item
        return list(products.values())

    def _fetch_collections(self) -> list[Collection]:
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        menu = soup.select_one("ul.list-menu.list-menu--inline")
        if not menu:
            return []
        collections: list[Collection] = []
        for link in menu.select("a[href^='/collections/']"):
            name = link.get_text(strip=True)
            href = link.get("href")
            if not href:
                continue
            url = urljoin(self.base_url, href)
            collections.append(Collection(name=name, url=url))
        return collections

    def _parse_collection(self, collection: Collection) -> list[ParsedProduct]:
        items: list[ParsedProduct] = []
        page = 1
        while True:
            page_url = self._with_page(collection.url, page)
            html = self._get_html(page_url)
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select("div.card-wrapper.product-card-wrapper")
            if not cards:
                break
            for card in cards:
                parsed = self._parse_card(card, collection.name)
                if parsed:
                    items.append(parsed)
            page += 1
        return items

    def _parse_card(self, card, category: str) -> ParsedProduct | None:
        link = card.select_one("a.full-unstyled-link[href^='/products/']")
        if not link:
            return None
        name = link.get_text(strip=True)
        href = link.get("href") or ""
        product_url = urljoin(self.base_url, href)
        external_id = self._external_id_from_url(product_url)
        price_text = self._extract_price_text(card)
        price = self._parse_price(price_text)
        currency = self._parse_currency(price_text)
        image_url = self._extract_image(card)

        details = self._fetch_product_details(product_url)
        images = details.get("images")
        if images:
            image_url = images[0]
        description = details.get("description")
        return ParsedProduct(
            external_id=external_id,
            name=name,
            category=category,
            price=price,
            currency=currency,
            size=self._format_sizes(details.get("sizes")),
            additional_info=self._format_additional_info(details),
            size_data=details.get("sizes"),
            image_urls=details.get("images") or ([image_url] if image_url else []),
            product_url=product_url,
            image_url=image_url,
            description=description,
        )

    def _fetch_product_details(self, product_url: str) -> dict:
        html = self._get_html(product_url)
        soup = BeautifulSoup(html, "html.parser")
        description = self._extract_description(soup)
        details_text = self._extract_accordion_text(soup)
        sizes = self._extract_sizes(soup)
        images = self._extract_images(soup)
        return {
            "description": description,
            "details": details_text,
            "sizes": sizes,
            "images": images,
        }

    def _format_sizes(self, sizes: list[dict] | None) -> str | None:
        if not sizes:
            return None
        parts: list[str] = []
        for item in sizes:
            value = item.get("value")
            if not value:
                continue
            if item.get("available"):
                parts.append(value)
            else:
                parts.append(f"{value} (sold out)")
        return ", ".join(parts) if parts else None

    def _format_additional_info(self, details: dict) -> str | None:
        blocks: list[str] = []
        description = details.get("description")
        if description:
            blocks.append(description)
        accordion = details.get("details")
        if accordion:
            blocks.append(accordion)
        return "\n\n".join(blocks) if blocks else None

    def _extract_description(self, soup: BeautifulSoup) -> str | None:
        block = soup.select_one("div.product__description")
        if not block:
            return None
        return block.get_text(" ", strip=True)

    def _extract_accordion_text(self, soup: BeautifulSoup) -> str | None:
        sections: list[str] = []
        for details in soup.select("div.product__accordion details"):
            title = details.select_one("summary h2")
            content = details.select_one("div.accordion__content")
            title_text = title.get_text(strip=True) if title else ""
            content_text = content.get_text(" ", strip=True) if content else ""
            if title_text or content_text:
                sections.append("\n".join([title_text, content_text]).strip())
        if not sections:
            return None
        return "\n\n".join(sections)

    def _extract_sizes(self, soup: BeautifulSoup) -> list[dict]:
        sizes: list[dict] = []
        for fieldset in soup.select("variant-selects fieldset"):
            legend = fieldset.select_one("legend")
            if legend and legend.get_text(strip=True).upper() != "SIZE":
                continue
            inputs = fieldset.select("input[type='radio']")
            for input_node in inputs:
                value = (input_node.get("value") or "").strip()
                if not value:
                    continue
                disabled = input_node.has_attr("disabled") or "disabled" in (input_node.get("class") or [])
                sizes.append({"value": value, "available": not disabled})
        return sizes

    def _extract_images(self, soup: BeautifulSoup) -> list[str]:
        urls: list[str] = []
        for img in soup.select("ul.product__media-list img"):
            src = img.get("src")
            if not src:
                continue
            if src.startswith("//"):
                src = f"https:{src}"
            urls.append(src)
        return urls

    def _extract_image(self, card) -> str | None:
        img = card.select_one("img")
        if not img:
            return None
        src = img.get("src")
        if not src:
            return None
        if src.startswith("//"):
            return f"https:{src}"
        return src

    def _extract_price_text(self, card) -> str:
        price = card.select_one("span.price-item--sale.price-item--last")
        if not price:
            price = card.select_one("span.price-item--regular")
        return price.get_text(strip=True) if price else ""

    def _parse_price(self, text: str) -> float | None:
        if not text:
            return None
        cleaned = re.sub(r"[^0-9,\.]+", "", text)
        cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _parse_currency(self, text: str) -> str | None:
        if "EUR" in text or "€" in text:
            return "EUR"
        if "USD" in text or "$" in text:
            return "USD"
        if "GBP" in text or "£" in text:
            return "GBP"
        return None

    def _external_id_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "products":
            return parts[1]
        return parsed.path

    def _append_category(self, product: ParsedProduct, category: str) -> None:
        if not product.category:
            product.category = category
            return
        parts = [item.strip() for item in product.category.split(",") if item.strip()]
        if category not in parts:
            parts.append(category)
        product.category = ", ".join(parts)

    def _with_page(self, base_url: str, page: int) -> str:
        parsed = urlparse(base_url)
        query = f"page={page}"
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))

    def _get_html(self, url: str) -> str:
        response = self.client.get(url, timeout_sec=settings.request_timeout_sec)
        response.raise_for_status()
        return response.text
