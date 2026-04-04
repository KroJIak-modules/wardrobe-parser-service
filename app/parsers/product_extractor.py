"""Product data extraction from Shopify JSON payloads."""

from typing import Any


class ShopifyProductExtractor:
    """Extract and normalize product fields from Shopify API/JS payloads."""

    @staticmethod
    def extract_price(payload: dict[str, Any]) -> str | None:
        """Extract price from variants or root level."""
        variants = payload.get("variants")
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                price = ShopifyProductExtractor._safe_str(variant.get("price"))
                if price:
                    return price
        return ShopifyProductExtractor._safe_str(payload.get("price"))

    @staticmethod
    def extract_currency(payload: dict[str, Any]) -> str | None:
        """Extract currency from variants or root level."""
        variants = payload.get("variants")
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                currency = ShopifyProductExtractor._safe_str(variant.get("currency"))
                if currency:
                    return currency
        return ShopifyProductExtractor._safe_str(payload.get("currency"))

    @staticmethod
    def extract_image_urls(payload: dict[str, Any]) -> list[str]:
        """Extract and deduplicate image URLs."""
        candidates: list[str] = []

        # images array
        images = payload.get("images")
        if isinstance(images, list):
            for item in images:
                if isinstance(item, str):
                    value = item.strip()
                    if value:
                        candidates.append(value)
                elif isinstance(item, dict):
                    for key in ("src", "url", "originalSrc"):
                        raw = item.get(key)
                        if isinstance(raw, str) and raw.strip():
                            candidates.append(raw.strip())
                            break

        # featured_image, image
        for key in ("featured_image", "image"):
            raw_image = payload.get(key)
            if isinstance(raw_image, str) and raw_image.strip():
                candidates.append(raw_image.strip())
            elif isinstance(raw_image, dict):
                for dict_key in ("src", "url", "originalSrc"):
                    raw = raw_image.get(dict_key)
                    if isinstance(raw, str) and raw.strip():
                        candidates.append(raw.strip())
                        break

        # Deduplicate and order
        seen: set[str] = set()
        ordered: list[str] = []
        for url in candidates:
            if url not in seen:
                seen.add(url)
                ordered.append(url)

        return ordered

    @staticmethod
    def extract_availability(payload: dict[str, Any]) -> bool:
        """
        Determine if product is available based on variants.
        
        Returns True if:
        - At least one variant has available=True
        - Or product-level available is True (fallback)
        
        Returns False if:
        - All variants have available=False or no variants exist
        - And product-level available is False
        """
        variants = payload.get("variants")

        if isinstance(variants, list) and variants:
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                if variant.get("available") is True:
                    return True
                quantity_raw = variant.get("inventory_quantity")
                if isinstance(quantity_raw, (int, float)) and quantity_raw > 0:
                    return True
            # We had variants, but none are available and no positive inventory.
            return False

        # Fallback to product-level availability only when variants are absent.
        return payload.get("available", True)
    
    @staticmethod
    def extract_variants(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract variant information (size/color options with availability).
        
        Returns list of dicts with: title, option1, option2, option3, available, price, inventory_quantity
        """
        variants = payload.get("variants")
        result: list[dict[str, Any]] = []
        
        if not isinstance(variants, list):
            return result
        
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            
            # Extract variant info
            available_raw = variant.get("available")
            quantity_raw = variant.get("inventory_quantity")
            quantity = quantity_raw if isinstance(quantity_raw, int) else 0
            available = bool(available_raw is True or quantity > 0)
            variant_weight_grams = ShopifyProductExtractor._extract_variant_weight_grams(variant)

            variant_info = {
                "title": ShopifyProductExtractor._safe_str(variant.get("title")) or "Default",
                "option1": ShopifyProductExtractor._safe_str(variant.get("option1")),
                "option2": ShopifyProductExtractor._safe_str(variant.get("option2")),
                "option3": ShopifyProductExtractor._safe_str(variant.get("option3")),
                "available": available,
                "price": variant.get("price"),
                "compare_at_price": variant.get("compare_at_price"),
                "inventory_quantity": quantity,
                "sku": ShopifyProductExtractor._safe_str(variant.get("sku")),
                "weight_grams": variant_weight_grams,
            }
            result.append(variant_info)
        
        return result

    @staticmethod
    def extract_weight(payload: dict[str, Any]) -> dict[str, Any]:
        """
        Extract normalized product weight from Shopify payload.

        Returns:
        - weight_grams: float | None
        - weight_value: float | None
        - weight_unit: str | None
        """
        best: dict[str, Any] | None = None
        variants = payload.get("variants")
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                grams = ShopifyProductExtractor._extract_variant_weight_grams(variant)
                if grams is None or grams <= 0:
                    continue

                weight_value = ShopifyProductExtractor._safe_float(variant.get("weight"))
                weight_unit = ShopifyProductExtractor._safe_str(variant.get("weight_unit"))
                if weight_value is None or weight_value <= 0:
                    weight_value = grams
                    weight_unit = "g"

                candidate = {
                    "weight_grams": grams,
                    "weight_value": weight_value,
                    "weight_unit": (weight_unit or "g").lower(),
                }
                if best is None or candidate["weight_grams"] > best["weight_grams"]:
                    best = candidate

        if best is not None:
            return best

        # Rare fallback: product-level weight fields.
        root_weight = ShopifyProductExtractor._safe_float(payload.get("weight"))
        root_unit = ShopifyProductExtractor._safe_str(payload.get("weight_unit"))
        if root_weight and root_weight > 0 and root_unit:
            grams = ShopifyProductExtractor._convert_to_grams(root_weight, root_unit)
            if grams and grams > 0:
                return {
                    "weight_grams": grams,
                    "weight_value": root_weight,
                    "weight_unit": root_unit.lower(),
                }

        return {
            "weight_grams": None,
            "weight_value": None,
            "weight_unit": None,
        }

    @staticmethod
    def _safe_str(value: Any) -> str | None:
        """Safely convert value to string or return None."""
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip() or None
        if isinstance(value, (int, float)):
            return str(value)
        return None

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            stripped = value.strip().replace(",", ".")
            if not stripped:
                return None
            try:
                return float(stripped)
            except ValueError:
                return None
        return None

    @staticmethod
    def _convert_to_grams(value: float, unit: str) -> float | None:
        normalized = (unit or "").strip().lower()
        if normalized in {"g", "gram", "grams"}:
            return value
        if normalized in {"kg", "kilogram", "kilograms"}:
            return value * 1000.0
        if normalized in {"lb", "lbs", "pound", "pounds"}:
            return value * 453.59237
        if normalized in {"oz", "ounce", "ounces"}:
            return value * 28.349523125
        return None

    @staticmethod
    def _extract_variant_weight_grams(variant: dict[str, Any]) -> float | None:
        grams_raw = variant.get("grams")
        grams = ShopifyProductExtractor._safe_float(grams_raw)
        if grams is not None and grams > 0:
            return grams

        weight_raw = ShopifyProductExtractor._safe_float(variant.get("weight"))
        weight_unit = ShopifyProductExtractor._safe_str(variant.get("weight_unit"))
        if weight_raw is None or weight_raw <= 0 or not weight_unit:
            return None

        converted = ShopifyProductExtractor._convert_to_grams(weight_raw, weight_unit)
        if converted is None or converted <= 0:
            return None
        return converted
