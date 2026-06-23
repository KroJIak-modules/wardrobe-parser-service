from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Iterable
from urllib.parse import urlparse

from app.adapters.contracts import AdapterProductDraft, AdapterVariantDraft, SiteAdapter, SourceContext
from app.services.shopify_policies import ShopifyPolicyFactory
from app.services.shopify_sitemap_discovery import ShopifySitemapDiscovery


class BaseProductAdapter(SiteAdapter):
    allowed_currencies: frozenset[str] | None = None
    default_currency_code: str | None = None
    default_variant_available: bool = False
    default_variant_title: str = "Default"

    def discover_visible_catalog(self, context: SourceContext) -> list[str]:
        return []

    def normalize_product(self, raw_product: dict) -> AdapterProductDraft:
        url = str(raw_product.get("url") or "").strip()
        description_html = self._coerce_optional_text(
            raw_product.get("description_html") or raw_product.get("description") or raw_product.get("body_html")
        )
        draft: AdapterProductDraft = {
            "url": url,
            "handle": self._derive_handle(raw_product=raw_product, url=url),
            "title": str(raw_product.get("title") or "").strip(),
            "description_html": description_html,
            "designer": self._coerce_optional_text(raw_product.get("designer")),
            "category": self._coerce_optional_text(raw_product.get("category")),
            "tags": self._normalize_tags(raw_product.get("tags")),
            "source_weight_grams": self._to_decimal(raw_product.get("source_weight_grams")),
            "images": self._normalize_images(raw_product=raw_product, product_url=url),
            "variants": self._normalize_variants(raw_product),
        }
        buyer_total = self._to_decimal(raw_product.get("buyer_total_price_amount"))
        if buyer_total is None:
            buyer_total = self._to_decimal(raw_product.get("buyer_total_price"))
        if buyer_total is not None:
            draft["buyer_total_price_amount"] = buyer_total
        buyer_fee = self._to_decimal(raw_product.get("buyer_service_fee_amount"))
        if buyer_fee is None:
            buyer_fee = self._to_decimal(raw_product.get("buyer_service_fee"))
        if buyer_fee is not None:
            draft["buyer_service_fee_amount"] = buyer_fee
        return draft

    def validate_product(self, normalized_product: AdapterProductDraft) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if not normalized_product.get("url"):
            reasons.append("missing_url")
        if not normalized_product.get("handle"):
            reasons.append("missing_handle")
        if not normalized_product.get("title"):
            reasons.append("missing_title")

        variants = normalized_product.get("variants") if isinstance(normalized_product.get("variants"), list) else []
        if not variants:
            reasons.append("missing_variants")
        if not self._has_positive_variant_price(variants):
            reasons.append("missing_price")

        variant_currencies = self._variant_currency_codes(variants)
        if not variant_currencies:
            reasons.append("missing_currency")
        elif self.allowed_currencies and not any(code in self.allowed_currencies for code in variant_currencies):
            reasons.append("unsupported_currency")

        return (len(reasons) == 0, reasons)

    def _derive_handle(self, *, raw_product: dict, url: str) -> str:
        handle = str(raw_product.get("handle") or "").strip()
        if handle:
            return handle
        return self._extract_handle(url)

    @staticmethod
    def _extract_handle(url: str) -> str:
        return ""

    def _normalize_variants(self, raw_product: dict) -> list[AdapterVariantDraft]:
        raw_variants = raw_product.get("variants")
        if not isinstance(raw_variants, list) or not raw_variants:
            fallback = self._fallback_variant(raw_product)
            return [fallback] if fallback is not None else []

        out: list[AdapterVariantDraft] = []
        fallback_currency = self._normalize_currency(
            raw_product.get("currency_code") or raw_product.get("currency") or self.default_currency_code
        )
        for raw_variant in raw_variants:
            if not isinstance(raw_variant, dict):
                continue
            item: AdapterVariantDraft = {
                "id": self._coerce_optional_text(raw_variant.get("id")),
                "title": self._variant_title(raw_variant),
                "sku": self._coerce_optional_text(raw_variant.get("sku")),
                "price_amount": self._to_decimal(raw_variant.get("price_amount") or raw_variant.get("price")),
                "currency_code": self._normalize_currency(
                    raw_variant.get("currency_code") or raw_variant.get("currency") or fallback_currency
                )
                or None,
                "available": bool(raw_variant.get("available", self.default_variant_available)),
            }
            for option_key in ("option1", "option2", "option3"):
                if option_key in raw_variant:
                    item[option_key] = self._coerce_optional_text(raw_variant.get(option_key))
            compare_at = self._to_decimal(
                raw_variant.get("compare_at_price_amount") or raw_variant.get("compare_at_price")
            )
            if compare_at is not None:
                item["compare_at_price_amount"] = compare_at
            out.append(item)
        if out:
            return out
        fallback = self._fallback_variant(raw_product)
        return [fallback] if fallback is not None else []

    def _fallback_variant(self, raw_product: dict) -> AdapterVariantDraft | None:
        price_amount = self._to_decimal(raw_product.get("price_amount") or raw_product.get("price"))
        currency_code = self._normalize_currency(
            raw_product.get("currency_code") or raw_product.get("currency") or self.default_currency_code
        )
        return {
            "id": None,
            "title": self.default_variant_title,
            "sku": None,
            "price_amount": price_amount,
            "currency_code": currency_code or None,
            "available": self.default_variant_available,
        }

    def _variant_title(self, raw_variant: dict) -> str | None:
        title = self._coerce_optional_text(raw_variant.get("title"))
        if title:
            return title
        option_values = [
            self._coerce_optional_text(raw_variant.get("option1")),
            self._coerce_optional_text(raw_variant.get("option2")),
            self._coerce_optional_text(raw_variant.get("option3")),
        ]
        option_title = " / ".join([value for value in option_values if value])
        return option_title or self.default_variant_title

    @staticmethod
    def _normalize_tags(raw_tags: object) -> list[str]:
        if isinstance(raw_tags, str):
            candidates = raw_tags.split(",")
        elif isinstance(raw_tags, (list, tuple, set, frozenset)):
            candidates = raw_tags
        elif raw_tags in (None, ""):
            return []
        else:
            candidates = [raw_tags]

        out: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            text = str(item or "").strip()
            if text:
                if text in seen:
                    continue
                seen.add(text)
                out.append(text)
        return out

    @classmethod
    def _normalize_images(cls, *, raw_product: dict, product_url: str) -> list[str]:
        out: list[str] = []
        primary = cls._normalize_image_url(str(raw_product.get("image_url") or "").strip(), product_url)
        if primary:
            out.append(primary)
        images = raw_product.get("images")
        if isinstance(images, list):
            for raw_image in images:
                candidate = ""
                if isinstance(raw_image, dict):
                    candidate = cls._normalize_image_url(
                        str(raw_image.get("src") or raw_image.get("url") or "").strip(),
                        product_url,
                    )
                else:
                    candidate = cls._normalize_image_url(str(raw_image or "").strip(), product_url)
                if candidate:
                    out.append(candidate)
        deduped: list[str] = []
        seen: set[str] = set()
        for image_url in out:
            if image_url in seen:
                continue
            seen.add(image_url)
            deduped.append(image_url)
        return deduped

    @staticmethod
    def _normalize_image_url(value: str, product_url: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        if raw.startswith("//"):
            return "https:" + raw
        if raw.startswith("/"):
            parsed = urlparse(product_url)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}{raw}"
        return raw

    @staticmethod
    def _coerce_optional_text(value: object) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _to_decimal(value: object) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _normalize_currency(value: object) -> str:
        text = str(value or "").strip().upper()
        return text if len(text) == 3 else ""

    @staticmethod
    def _variant_currency_codes(variants: Iterable[AdapterVariantDraft]) -> set[str]:
        out: set[str] = set()
        for variant in variants:
            code = str(variant.get("currency_code") or "").strip().upper()
            if len(code) == 3:
                out.add(code)
        return out

    @staticmethod
    def _has_positive_variant_price(variants: Iterable[AdapterVariantDraft]) -> bool:
        for variant in variants:
            price_amount = variant.get("price_amount")
            if price_amount is not None and price_amount > Decimal("0"):
                return True
        return False


class PassiveCatalogAdapter(BaseProductAdapter):
    pass


class ShopifyCatalogAdapter(BaseProductAdapter):
    default_variant_available = True

    def discover_visible_catalog(self, context: SourceContext) -> list[str]:
        base_url = context.source_url.rstrip("/")
        timeout = int((context.source_config.get("timeouts") or {}).get("product_sec", 10))
        policy = ShopifyPolicyFactory.sitemap(context.source_config)
        return sorted(ShopifySitemapDiscovery.discover_product_urls(base_url, timeout, policy))

    @staticmethod
    def _extract_handle(url: str) -> str:
        return ShopifySitemapDiscovery.extract_handle(url)
