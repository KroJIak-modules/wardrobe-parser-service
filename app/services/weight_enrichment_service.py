from __future__ import annotations

import re

from app.services.weight_rules_client import WeightRule


class WeightEnrichmentService:
    @staticmethod
    def apply_keyword_weight(product: dict, rules: list[WeightRule]) -> dict:
        current = product.get('weight_grams')
        if current is not None:
            try:
                if float(current) > 0:
                    product['weight_source'] = 'source'
                    return product
            except Exception:
                pass

        haystack = WeightEnrichmentService._normalize(
            ' '.join(
                [
                    str(product.get('title') or ''),
                    str(product.get('handle') or ''),
                    str(product.get('product_type') or ''),
                    WeightEnrichmentService._join_tags(product.get('tags')),
                ]
            )
        )

        best_weight: int | None = None
        best_kw_len = -1
        for rule in rules:
            for keyword in rule.keywords:
                kw = WeightEnrichmentService._normalize(keyword)
                if not kw:
                    continue
                if kw in haystack:
                    if len(kw) > best_kw_len or (len(kw) == best_kw_len and (best_weight is None or rule.weight_grams > best_weight)):
                        best_kw_len = len(kw)
                        best_weight = rule.weight_grams

        if best_weight is not None:
            product['weight_grams'] = best_weight
            product['weight_source'] = 'keyword_rule'
        else:
            product['weight_source'] = 'missing'
        return product

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = re.sub(r'[^a-z0-9\\s]+', ' ', text.strip().lower())
        return ' '.join(normalized.split())

    @staticmethod
    def _join_tags(tags: object) -> str:
        if not isinstance(tags, list):
            return ''
        return ' '.join(str(tag) for tag in tags if str(tag).strip())
