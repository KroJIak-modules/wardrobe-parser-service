from app.services.shopify_weight_service import ShopifyWeightService


def test_shopify_weight_service_uses_grams_field_when_present() -> None:
    assert ShopifyWeightService.resolve_variant_weight_grams(
        [
            {"title": "S", "grams": 520},
            {"title": "M", "grams": 540},
        ]
    ) == 520


def test_shopify_weight_service_converts_weight_unit_kg_to_grams() -> None:
    assert ShopifyWeightService.resolve_variant_weight_grams(
        [
            {"title": "OS", "weight": 0.454, "weight_unit": "kg"},
        ]
    ) == 454


def test_shopify_weight_service_accepts_integer_weight_without_unit_as_grams() -> None:
    assert ShopifyWeightService.resolve_variant_weight_grams(
        [
            {"title": "OS", "weight": 454},
        ]
    ) == 454


def test_shopify_weight_service_rejects_fractional_weight_without_unit() -> None:
    assert ShopifyWeightService.resolve_variant_weight_grams(
        [
            {"title": "OS", "weight": 0.454},
        ]
    ) is None
