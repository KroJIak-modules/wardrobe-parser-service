from app.adapters.base import ShopifyCatalogAdapter


class StoreBacklashV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "store_backlash__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
    allowed_currencies = frozenset({"USD", "EUR", "GBP", "JPY"})
