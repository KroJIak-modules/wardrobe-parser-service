from __future__ import annotations

from dataclasses import dataclass
import requests


@dataclass(frozen=True)
class WeightRule:
    weight_grams: int
    keywords: list[str]


@dataclass(frozen=True)
class WeightRulesPayload:
    revision: str
    rules: list[WeightRule]


class WeightRulesClient:
    def __init__(self, backend_base_url: str, timeout_sec: int = 10) -> None:
        self.backend_base_url = backend_base_url.rstrip('/')
        self.timeout_sec = timeout_sec

    def fetch(self) -> WeightRulesPayload:
        url = f'{self.backend_base_url}/api/v1/public/parser-contract/weight-rules'
        try:
            response = requests.get(url, timeout=self.timeout_sec)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return WeightRulesPayload(revision='unavailable', rules=[])
        revision = str(payload.get('revision') or 'unknown')
        out: list[WeightRule] = []
        for item in payload.get('rules') or []:
            weight = int(item.get('weight_grams') or 0)
            keywords = [str(x).strip().lower() for x in (item.get('keywords') or []) if str(x).strip()]
            if weight > 0:
                out.append(WeightRule(weight_grams=weight, keywords=keywords))
        return WeightRulesPayload(revision=revision, rules=out)
