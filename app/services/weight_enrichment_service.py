from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Mapping

from app.schemas.source_product import WeightSource
from app.services.weight_rules_client import WeightRule


@dataclass(frozen=True, slots=True)
class WeightResolution:
    source_weight_grams: int | None
    resolved_weight_grams: int | None
    weight_source: WeightSource


class WeightEnrichmentService:
    @classmethod
    def resolve(cls, product: Mapping[str, object], rules: list[WeightRule]) -> WeightResolution:
        source_weight = cls._coerce_positive_weight(product.get("weight_grams"))
        if source_weight is not None:
            return WeightResolution(
                source_weight_grams=source_weight,
                resolved_weight_grams=source_weight,
                weight_source="source",
            )

        matched_rule = cls._match_best_rule(product=product, rules=rules)
        if matched_rule is not None:
            return WeightResolution(
                source_weight_grams=None,
                resolved_weight_grams=matched_rule.weight_grams,
                weight_source="keyword_rule",
            )

        return WeightResolution(
            source_weight_grams=None,
            resolved_weight_grams=None,
            weight_source="missing",
        )

    @classmethod
    def apply_keyword_weight(cls, product: dict, rules: list[WeightRule]) -> dict:
        resolution = cls.resolve(product, rules)
        product["source_weight_grams"] = resolution.source_weight_grams
        product["resolved_weight_grams"] = resolution.resolved_weight_grams
        product["weight_grams"] = resolution.resolved_weight_grams
        product["weight_source"] = resolution.weight_source
        return product

    @classmethod
    def _match_best_rule(cls, *, product: Mapping[str, object], rules: list[WeightRule]) -> WeightRule | None:
        haystack = cls._build_haystack(product)
        best_rule: WeightRule | None = None
        best_match_count = 0
        for rule in rules:
            match_count = cls._count_rule_matches(rule=rule, haystack=haystack)
            if match_count > best_match_count:
                best_match_count = match_count
                best_rule = rule
        return best_rule

    @classmethod
    def _build_haystack(cls, product: Mapping[str, object]) -> str:
        return cls._normalize(
            " ".join(
                [
                    str(product.get("title") or ""),
                    str(product.get("handle") or ""),
                    str(product.get("category") or ""),
                    cls._join_tags(product.get("tags")),
                ]
            )
        )

    @classmethod
    def _count_rule_matches(cls, *, rule: WeightRule, haystack: str) -> int:
        matched_keywords: set[str] = set()
        for keyword in rule.keywords:
            normalized_keyword = cls._normalize(keyword)
            if normalized_keyword and normalized_keyword in haystack:
                matched_keywords.add(normalized_keyword)
        return len(matched_keywords)

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

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = re.sub(r"[^a-z0-9\\s]+", " ", text.strip().lower())
        return " ".join(normalized.split())

    @staticmethod
    def _join_tags(tags: object) -> str:
        if not isinstance(tags, list):
            return ""
        return " ".join(str(tag) for tag in tags if str(tag).strip())
