from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from app.services.shopify_http_client import ShopifyHttpClient


class ShopifyCatalogMetadataService:
    _HTML_CATEGORY_RE = re.compile(r'"category"\s*:\s*"([^"]+)"', flags=re.IGNORECASE)
    _TAG_GENDER_PREFIXES = ("women ", "woman ", "womens ", "men ", "mens ", "unisex ")
    _TAG_STOPWORDS = {
        "accessories",
        "accessory",
        "archive",
        "archives",
        "clothing",
        "collection",
        "collections",
        "drop",
        "fashion",
        "fashion archive",
        "men",
        "new",
        "new arrival",
        "ready stock",
        "sale",
        "stock",
        "summer",
        "unisex",
        "women",
        "winter",
    }
    _CATEGORY_HINTS = {
        "bag",
        "bags",
        "ballet",
        "belt",
        "belts",
        "blazer",
        "blazers",
        "boot",
        "boots",
        "bra",
        "bras",
        "brief",
        "briefs",
        "camisole",
        "camisoles",
        "cardigan",
        "cardigans",
        "coat",
        "coats",
        "corset",
        "corsets",
        "denim",
        "dress",
        "dresses",
        "earring",
        "earrings",
        "glass",
        "glasses",
        "gown",
        "gowns",
        "hat",
        "hats",
        "heel",
        "heels",
        "hoodie",
        "hoodies",
        "jacket",
        "jackets",
        "jean",
        "jeans",
        "jersey",
        "jerseys",
        "jewelry",
        "jumper",
        "jumpers",
        "knit",
        "knits",
        "legging",
        "leggings",
        "loafer",
        "loafers",
        "necklace",
        "necklaces",
        "outerwear",
        "pant",
        "pants",
        "parka",
        "parkas",
        "perfume",
        "perfumes",
        "ring",
        "rings",
        "robe",
        "robes",
        "sandals",
        "shirt",
        "shirts",
        "shoe",
        "shoes",
        "short",
        "shorts",
        "skirt",
        "skirts",
        "slipper",
        "slippers",
        "sneaker",
        "sneakers",
        "sock",
        "socks",
        "sunglasses",
        "sweater",
        "sweaters",
        "swimwear",
        "tee",
        "tees",
        "top",
        "tops",
        "trouser",
        "trousers",
        "underwear",
        "vest",
        "vests",
        "wallet",
        "wallets",
        "watch",
        "watches",
    }

    @classmethod
    def resolve_category(
        cls,
        payload: Mapping[str, object],
        *,
        product_url: str | None = None,
        timeout: int | None = None,
    ) -> str | None:
        for key in ("product_type", "type", "category", "productType"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value

        tag_category = cls._resolve_tag_category(payload.get("tags"))
        if tag_category:
            return tag_category

        if product_url and timeout is not None and int(timeout) > 0:
            return cls._resolve_html_category(product_url=product_url, timeout=timeout)
        return None

    @classmethod
    def _resolve_html_category(cls, *, product_url: str | None, timeout: int | None) -> str | None:
        url = str(product_url or "").strip()
        if not url or timeout is None or int(timeout) <= 0:
            return None
        try:
            response = ShopifyHttpClient.get_text(url, int(timeout))
        except Exception:
            return None
        if int(response.status_code) != 200:
            return None
        for match in cls._HTML_CATEGORY_RE.finditer(response.text):
            value = str(match.group(1) or "").replace("\\/", "/").strip()
            if value:
                return value
        return None

    @classmethod
    def _resolve_tag_category(cls, raw_tags: object) -> str | None:
        if isinstance(raw_tags, str):
            tags = [part.strip() for part in raw_tags.split(",")]
        elif isinstance(raw_tags, Sequence):
            tags = [str(part or "").strip() for part in raw_tags]
        else:
            return None

        for raw_tag in tags:
            normalized = cls._normalize_tag_candidate(raw_tag)
            if normalized:
                return normalized
        return None

    @classmethod
    def _normalize_tag_candidate(cls, raw_tag: str) -> str | None:
        value = " ".join(re.sub(r"[_-]+", " ", str(raw_tag or "").strip()).split())
        if not value:
            return None
        lowered = value.casefold()
        for prefix in cls._TAG_GENDER_PREFIXES:
            if lowered.startswith(prefix):
                value = value[len(prefix) :].strip()
                lowered = value.casefold()
                break
        if not value:
            return None
        if any(char.isdigit() for char in value):
            return None
        if lowered in cls._TAG_STOPWORDS:
            return None
        tokens = re.findall(r"[A-Za-z]+", lowered)
        if not tokens:
            return None
        if not any(token in cls._CATEGORY_HINTS for token in tokens):
            return None
        return value.title() if value == value.lower() else value
