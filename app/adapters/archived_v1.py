from app.adapters.base import ShopifyCatalogAdapter


class ArchivedV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "archived__v1"
    allowed_strategies = ("shopify_json", "shopify_js")

    def normalize_product(self, raw_product: dict):
        draft = super().normalize_product(raw_product)
        title = str(draft.get("title") or "").strip()
        designer = str(draft.get("designer") or "").strip()
        category = str(draft.get("category") or "").strip()
        product_type = str(raw_product.get("product_type") or "").strip()
        if category and self._normalize_compare(title) == self._normalize_compare(designer):
            draft["title"] = category
        elif title and product_type:
            draft["title"] = f"{title} | {product_type}"
        elif product_type:
            draft["title"] = product_type
        else:
            draft["title"] = title
        return draft

    @staticmethod
    def _normalize_compare(value: str | None) -> str:
        text = str(value or "").strip().casefold()
        return "".join(character for character in text if character.isalnum())
