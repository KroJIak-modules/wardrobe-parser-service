from app.adapters.base import PassiveCatalogAdapter


class VintedV1Adapter(PassiveCatalogAdapter):
    adapter_key = "vinted__v1"
    allowed_strategies = ("vinted_jsonld",)
    allowed_currencies = frozenset({"USD", "EUR", "GBP"})
