from app.services.weight_enrichment_service import WeightEnrichmentService
from app.services.weight_rules_client import WeightRule


def test_keyword_weight_uses_product_type_when_source_weight_missing() -> None:
    product = {
        'title': 'Brand Model Name',
        'handle': 'brand-model-name',
        'product_type': 'Jeans',
        'tags': [],
        'weight_grams': 0,
    }

    out = WeightEnrichmentService.apply_keyword_weight(product, [WeightRule(weight_grams=680, keywords=['jeans'])])

    assert out['weight_grams'] == 680
    assert out['weight_source'] == 'keyword_rule'
