from __future__ import annotations

from collections.abc import Mapping, Sequence


class ShopifyWeightService:
    _GRAM_UNITS = {"g", "gram", "grams"}
    _KILOGRAM_UNITS = {"kg", "kgs", "kilogram", "kilograms"}
    _OUNCE_UNITS = {"oz", "ounce", "ounces"}
    _POUND_UNITS = {"lb", "lbs", "pound", "pounds"}

    @classmethod
    def resolve_variant_weight_grams(cls, variants: Sequence[Mapping[str, object]]) -> int | None:
        values: list[int] = []
        for variant in variants:
            grams = cls._variant_weight_grams(variant)
            if grams is not None and grams > 0:
                values.append(grams)
        return min(values) if values else None

    @classmethod
    def _variant_weight_grams(cls, variant: Mapping[str, object]) -> int | None:
        direct_grams = cls._coerce_positive_int(variant.get("grams"))
        if direct_grams is not None:
            return direct_grams

        raw_weight = cls._coerce_positive_float(variant.get("weight"))
        if raw_weight is None:
            return None

        unit = str(variant.get("weight_unit") or variant.get("weightUnit") or "").strip().lower()
        if unit in cls._GRAM_UNITS:
            return cls._round_grams(raw_weight)
        if unit in cls._KILOGRAM_UNITS:
            return cls._round_grams(raw_weight * 1000.0)
        if unit in cls._OUNCE_UNITS:
            return cls._round_grams(raw_weight * 28.349523125)
        if unit in cls._POUND_UNITS:
            return cls._round_grams(raw_weight * 453.59237)

        if raw_weight >= 10 or float(raw_weight).is_integer():
            return cls._round_grams(raw_weight)
        return None

    @staticmethod
    def _coerce_positive_int(value: object) -> int | None:
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except Exception:
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _coerce_positive_float(value: object) -> float | None:
        try:
            parsed = float(value)  # type: ignore[arg-type]
        except Exception:
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _round_grams(value: float) -> int | None:
        rounded = int(round(float(value)))
        return rounded if rounded > 0 else None
