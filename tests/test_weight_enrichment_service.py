from decimal import Decimal

from app.services.weight_enrichment_service import WeightEnrichmentService
from app.services.weight_rules_client import WeightRule


def test_keyword_weight_uses_category_when_source_weight_missing() -> None:
    product = {
        'title': 'Brand Model Name',
        'handle': 'brand-model-name',
        'category': 'Jeans',
        'tags': [],
        'weight_grams': 0,
    }

    out = WeightEnrichmentService.apply_keyword_weight(product, [WeightRule(weight_grams=680, keywords=['jeans'])])

    assert out['source_weight_grams'] is None
    assert out['resolved_weight_grams'] == 680
    assert out['weight_grams'] == 680
    assert out['weight_source'] == 'keyword_rule'


def test_source_weight_wins_over_keyword_rule() -> None:
    product = {
        'title': 'Heavy Jeans',
        'handle': 'heavy-jeans',
        'category': 'Jeans',
        'tags': ['denim'],
        'weight_grams': Decimal('910'),
    }

    out = WeightEnrichmentService.apply_keyword_weight(product, [WeightRule(weight_grams=680, keywords=['jeans'])])

    assert out['source_weight_grams'] == 910
    assert out['resolved_weight_grams'] == 910
    assert out['weight_grams'] == 910
    assert out['weight_source'] == 'source'


def test_rule_with_more_keyword_matches_wins() -> None:
    product = {
        'title': 'Black cargo pants',
        'handle': 'black-cargo-pants',
        'category': 'Pants',
        'tags': ['cargo', 'black'],
        'weight_grams': 0,
    }

    out = WeightEnrichmentService.apply_keyword_weight(
        product,
        [
            WeightRule(weight_grams=500, keywords=['pants']),
            WeightRule(weight_grams=740, keywords=['cargo', 'pants']),
        ],
    )

    assert out['resolved_weight_grams'] == 740
    assert out['weight_source'] == 'keyword_rule'
