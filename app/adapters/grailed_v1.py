from app.adapters.base import PassiveCatalogAdapter


class GrailedV1Adapter(PassiveCatalogAdapter):
    adapter_key = "grailed__v1"
    allowed_strategies = ("grailed_algolia_jsonld",)
    allowed_currencies = frozenset({"USD", "EUR", "GBP"})
