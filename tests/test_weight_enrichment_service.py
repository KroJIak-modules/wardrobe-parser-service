from decimal import Decimal

from app.services.weight_enrichment_service import WeightEnrichmentService


def test_missing_or_zero_weight_is_marked_missing() -> None:
    assert WeightEnrichmentService.resolve({"weight_grams": None}).source_weight_grams is None
    assert WeightEnrichmentService.resolve({"weight_grams": 0}).weight_source == "missing"


def test_positive_source_weight_is_preserved() -> None:
    resolution = WeightEnrichmentService.resolve({"weight_grams": Decimal("910")})

    assert resolution.source_weight_grams == 910
    assert resolution.weight_source == "source"


def test_non_numeric_weight_is_ignored() -> None:
    resolution = WeightEnrichmentService.resolve({"weight_grams": "oops"})

    assert resolution.source_weight_grams is None
    assert resolution.weight_source == "missing"
