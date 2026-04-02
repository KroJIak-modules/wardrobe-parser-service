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

            variant_info = {
                "title": ShopifyProductExtractor._safe_str(variant.get("title")) or "Default",
                "option1": ShopifyProductExtractor._safe_str(variant.get("option1")),
                "option2": ShopifyProductExtractor._safe_str(variant.get("option2")),
                "option3": ShopifyProductExtractor._safe_str(variant.get("option3")),
                "available": available,
                "price": variant.get("price"),
                "inventory_quantity": quantity,
                "sku": ShopifyProductExtractor._safe_str(variant.get("sku")),
            }
            result.append(variant_info)
        
        return result
    
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
