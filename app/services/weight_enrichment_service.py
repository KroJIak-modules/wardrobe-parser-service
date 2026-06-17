from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from app.schemas.source_product import WeightSource


@dataclass(frozen=True, slots=True)
class WeightResolution:
    source_weight_grams: int | None
    weight_source: WeightSource


class WeightEnrichmentService:
    @classmethod
    def resolve(cls, product: Mapping[str, object]) -> WeightResolution:
        source_weight = cls._coerce_positive_weight(product.get("weight_grams"))
        if source_weight is not None:
            return WeightResolution(
                source_weight_grams=source_weight,
                weight_source="source",
            )

        return WeightResolution(
            source_weight_grams=None,
            weight_source="missing",
        )

    @staticmethod
    def _coerce_positive_weight(value: object) -> int | None:
        try:
            if value is None:
                return None
            if isinstance(value, Decimal):
                numeric = value
            else:
                numeric = Decimal(str(value))
            if numeric <= 0:
                return None
            return int(numeric)
        except Exception:
            return None
