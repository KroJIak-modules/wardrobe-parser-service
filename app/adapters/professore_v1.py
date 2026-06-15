from app.adapters.base import ShopifyCatalogAdapter


class ProfessoreV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "professore__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
