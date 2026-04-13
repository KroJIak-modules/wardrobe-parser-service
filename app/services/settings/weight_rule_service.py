"""Service for weight rules CRUD and keyword-based weight estimation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import ParserProduct, ParserSource, ParserWeightRule
from app.repositories import ParserWeightKeywordRepository, ParserWeightRuleRepository
from app.schemas.parser import (
    WeightRuleCreateRequest,
    WeightRuleKeywordRequest,
    WeightMissingProductResponse,
    WeightRuleResponse,
    WeightRuleUpdateRequest,
)


@dataclass(slots=True)
class WeightMatchResult:
    """Resolved weight from keyword rules."""

    weight_grams: float | None
    matched_keyword: str | None


def _normalize_keyword(keyword: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s]+", " ", keyword.strip().lower())
    normalized = " ".join(normalized.split())
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ключевое слово не может быть пустым")
    if len(normalized) > 255:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ключевое слово слишком длинное")
    return normalized


def _normalize_match_haystack(*parts: str | None) -> str:
    text = " ".join(item.strip().lower() for item in parts if item and item.strip())
    # Keep letters/digits/spaces only for stable contains checks.
    normalized = re.sub(r"[^a-z0-9\s]+", " ", text)
    return " ".join(normalized.split())


def _unique_normalized_keywords(keywords: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        normalized = _normalize_keyword(keyword)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


DEFAULT_WEIGHT_RULES: list[tuple[int, list[str]]] = [
    (80, ["ring", "rings", "earring", "earrings", "ear cuff", "earcuff", "stud earring", "hoop earring", "brooch", "pin badge", "lapel pin", "cufflink", "tie clip", "charm", "nose ring"]),
    (130, ["necklace", "chain", "chain necklace", "pendant", "choker", "bracelet", "bangle", "bangles", "anklet", "body chain", "wallet chain", "key chain", "keychain", "lanyard"]),
    (190, ["card holder", "cardholders", "card case", "card wallet", "coin pouch", "coin purse", "wallet", "wallets", "passport holder", "id holder", "key holder", "phone pouch", "glasses case", "cardholder"]),
    (240, ["cap", "baseball cap", "trucker hat", "snapback", "beanie", "knit beanie", "bucket hat", "visor", "hat", "bandana", "headband", "necktie", "tie", "scarf", "neck scarf", "gloves", "mittens", "balaclava", "mask", "belt", "belts", "chain belt"]),
    (300, ["tank top", "tank", "cami", "camisole", "sleeveless top", "crop top", "bralette", "bra top", "bodysuit", "tube top", "halter top", "corset", "corset top"]),
    (360, ["t shirt", "tee", "graphic tee", "oversized tee", "long sleeve tee", "jersey tee", "polo tee", "thermal tee", "rib tee", "raglan tee", "top", "tops"]),
    (440, ["shirt", "shirts", "polo shirt", "polo", "button up", "button down", "oxford shirt", "dress shirt", "flannel shirt", "denim shirt", "blouse", "tunic"]),
    (540, ["shorts", "short", "boxer shorts", "bermuda", "cargo shorts", "denim shorts", "mini skirt", "midi skirt", "maxi skirt", "skirt", "skort"]),
    (680, ["pants", "pant", "trouser", "trousers", "jeans", "denim jeans", "straight leg jeans", "skinny jeans", "wide leg jeans", "flared jeans", "capri", "capri pants", "cargo pants", "track pants", "joggers", "sweatpants", "lounge pants", "chinos", "slacks", "leggings", "bottom", "bottoms", "denim"]),
    (820, ["sweatshirt", "crewneck", "jumper", "knit", "knitwear", "sweater", "pullover", "cardigan", "zip sweater", "knit top", "fleece top"]),
    (960, ["hoodie", "hooded sweatshirt", "zip hoodie", "quarter zip", "vest", "puffer vest", "down vest", "knit vest", "waistcoat", "gilet"]),
    (1120, ["jacket", "blouson", "bomber", "trucker jacket", "denim jacket", "varsity jacket", "windbreaker", "shell jacket", "rain jacket", "blazer", "overshirt", "outerwear"]),
    (1380, ["coat", "overcoat", "trench coat", "parka", "puffer", "puffer jacket", "down jacket", "quilted jacket", "wool coat", "pea coat", "duffle coat"]),
    (1560, ["sneakers", "sneaker", "running shoes", "running shoe", "trainers", "shoes", "shoe", "loafers", "loafer", "derby", "oxford shoes", "moccasin", "espadrille", "ballet flats", "flats", "sandals", "mule", "kitten heel", "heel shoes", "heel", "heels"]),
    (1860, ["boots", "boot", "ankle boots", "combat boots", "chelsea boots", "hiking boots", "cowboy boots", "platform boots", "prosthetic boots"]),
    (2300, ["tote bag", "shoulder bag", "crossbody bag", "messenger bag", "satchel", "handbag", "clutch bag", "hobo bag", "belt bag", "waist bag", "fanny pack", "sling bag", "bag", "bags"]),
    (2850, ["backpack", "rucksack", "duffle bag", "duffel bag", "weekender bag", "gym bag", "travel bag", "garment bag"]),
    (3800, ["suitcase", "carry on", "trolley case", "hard case luggage", "trunk case"]),
]


class WeightRuleService:
    """Business logic for weight rules and fallback estimation."""

    def __init__(self, db: Session):
        self.db = db
        self.rule_repo = ParserWeightRuleRepository(db)
        self.keyword_repo = ParserWeightKeywordRepository(db)

    def _build_responses(self, rules: list[ParserWeightRule]) -> list[WeightRuleResponse]:
        rows: list[WeightRuleResponse] = []
        for rule in rules:
            keywords = [item.keyword for item in self.keyword_repo.get_by_rule(rule.id)]
            rows.append(
                WeightRuleResponse(
                    id=rule.id,
                    weight_grams=rule.weight_grams,
                    keywords=keywords,
                )
            )
        return rows

    def ensure_default_rules(self) -> list[ParserWeightRule]:
        active = self.rule_repo.get_all_active()
        changed = False
        if not active:
            for index, (weight_grams, keywords) in enumerate(DEFAULT_WEIGHT_RULES, start=1):
                created = self.rule_repo.create(
                    weight_grams=weight_grams,
                    sort_order=index,
                )
                self.rule_repo.flush()
                for normalized in _unique_normalized_keywords(keywords):
                    self.keyword_repo.create(rule_id=created.id, keyword=normalized)
            changed = True
            active = self.rule_repo.get_all_active()

        for rule in active:
            changed = self._normalize_rule_keywords(rule.id) or changed

        active = self.rule_repo.get_all_active()
        by_weight = {rule.weight_grams: rule for rule in active}
        next_sort_order = max((rule.sort_order for rule in active), default=0)
        for weight_grams, keywords in DEFAULT_WEIGHT_RULES:
            rule = by_weight.get(weight_grams)
            if rule is None:
                next_sort_order += 1
                rule = self.rule_repo.create(weight_grams=weight_grams, sort_order=next_sort_order)
                self.rule_repo.flush()
                by_weight[weight_grams] = rule
                changed = True

            existing = {item.keyword for item in self.keyword_repo.get_by_rule(rule.id)}
            for normalized in _unique_normalized_keywords(keywords):
                if normalized not in existing:
                    self.keyword_repo.create(rule_id=rule.id, keyword=normalized)
                    existing.add(normalized)
                    changed = True

        if changed:
            self.db.commit()
        return self.rule_repo.get_all_active()

    def _normalize_rule_keywords(self, rule_id: int) -> bool:
        """Normalize punctuation/spacing in stored keywords and dedupe collisions."""
        changed = False
        seen_normalized: set[str] = set()
        for item in self.keyword_repo.get_by_rule(rule_id):
            normalized = _normalize_keyword(item.keyword)
            if normalized in seen_normalized:
                self.db.delete(item)
                changed = True
                continue
            seen_normalized.add(normalized)
            if item.keyword != normalized:
                item.keyword = normalized
                changed = True
        return changed

    def list_rules(self) -> list[WeightRuleResponse]:
        rules = self.ensure_default_rules()
        return self._build_responses(rules)

    def create_rule(self, payload: WeightRuleCreateRequest) -> WeightRuleResponse:
        self.ensure_default_rules()
        current = self.rule_repo.get_all_active()
        max_sort = max((item.sort_order for item in current), default=0)
        created = self.rule_repo.create(
            weight_grams=payload.weight_grams,
            sort_order=max_sort + 1,
        )
        self.rule_repo.flush()
        self.db.commit()
        return WeightRuleResponse(id=created.id, weight_grams=created.weight_grams, keywords=[])

    def update_rule(self, rule_id: int, payload: WeightRuleUpdateRequest) -> WeightRuleResponse:
        rule = self.rule_repo.get_by_id(rule_id)
        if not rule or rule.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило веса не найдено")

        self.rule_repo.update(rule, weight_grams=payload.weight_grams)
        self.db.commit()
        keywords = [item.keyword for item in self.keyword_repo.get_by_rule(rule.id)]
        return WeightRuleResponse(id=rule.id, weight_grams=rule.weight_grams, keywords=keywords)

    def delete_rule(self, rule_id: int) -> dict:
        rule = self.rule_repo.get_by_id(rule_id)
        if not rule or rule.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило веса не найдено")

        # Soft-delete rule and hard-delete its keywords.
        for keyword in self.keyword_repo.get_by_rule(rule_id):
            self.db.delete(keyword)
        rule.deleted_at = datetime.now(timezone.utc)
        self.db.commit()
        return {"ok": True}

    def add_keyword(self, rule_id: int, payload: WeightRuleKeywordRequest) -> dict:
        rule = self.rule_repo.get_by_id(rule_id)
        if not rule or rule.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило веса не найдено")

        keyword = _normalize_keyword(payload.keyword)
        existing = self.keyword_repo.get_exact(rule_id, keyword)
        if existing:
            return {"ok": True, "keyword": keyword, "duplicated": True}

        self.keyword_repo.create(rule_id=rule_id, keyword=keyword)
        self.db.commit()
        return {"ok": True, "keyword": keyword}

    def remove_keyword(self, rule_id: int, keyword: str) -> dict:
        rule = self.rule_repo.get_by_id(rule_id)
        if not rule or rule.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило веса не найдено")

        normalized = _normalize_keyword(keyword)
        entity = self.keyword_repo.get_exact(rule_id, normalized)
        if not entity:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ключевое слово не найдено")

        self.db.delete(entity)
        self.db.commit()
        return {"ok": True}

    def get_matching_rules(self) -> list[WeightRuleResponse]:
        """Return active rules guaranteed to be non-empty (defaults are auto-created)."""
        return self.list_rules()

    def list_missing_weight_products(self, limit: int = 500) -> list[WeightMissingProductResponse]:
        safe_limit = max(1, min(limit, 5000))
        rules = self.get_matching_rules()
        # Fetch a wider window because some records may become resolvable
        # after applying current keyword rules in-memory.
        probe_limit = min(safe_limit * 5, 20000)
        rows = (
            self.db.query(ParserProduct, ParserSource)
            .join(ParserSource, ParserSource.id == ParserProduct.source_id)
            .filter(ParserProduct.deleted_at.is_(None))
            .filter((ParserProduct.weight_grams.is_(None)) | (ParserProduct.weight_source == "missing"))
            .order_by(ParserProduct.updated_at.desc())
            .limit(probe_limit)
            .all()
        )
        unresolved: list[WeightMissingProductResponse] = []
        for product, source in rows:
            match = self.match_weight_from_rules(
                rules=rules,
                title=product.title,
                vendor=product.vendor,
                product_type=product.product_type,
                handle=product.handle,
            )
            if match.weight_grams is not None:
                continue
            unresolved.append(
                WeightMissingProductResponse(
                    id=product.id,
                    title=product.title,
                    url=product.url,
                    source_id=product.source_id,
                    source_name=source.name,
                )
            )
            if len(unresolved) >= safe_limit:
                break
        return unresolved

    @staticmethod
    def match_weight_from_rules(
        *,
        rules: list[WeightRuleResponse],
        title: str | None,
        vendor: str | None,
        product_type: str | None,
        handle: str | None,
    ) -> WeightMatchResult:
        if not rules:
            return WeightMatchResult(weight_grams=None, matched_keyword=None)

        haystack = _normalize_match_haystack(title, vendor, product_type, handle)
        if not haystack:
            return WeightMatchResult(weight_grams=None, matched_keyword=None)

        best_rule_weight: int | None = None
        best_keyword: str | None = None
        best_keyword_len = -1
        for rule in rules:
            for keyword in rule.keywords:
                normalized_keyword = _normalize_keyword(keyword)
                if normalized_keyword in haystack:
                    keyword_len = len(normalized_keyword)
                    if keyword_len > best_keyword_len or (
                        keyword_len == best_keyword_len and (best_rule_weight is None or rule.weight_grams > best_rule_weight)
                    ):
                        best_keyword_len = keyword_len
                        best_rule_weight = rule.weight_grams
                        best_keyword = normalized_keyword

        if best_rule_weight is None:
            return WeightMatchResult(weight_grams=None, matched_keyword=None)
        return WeightMatchResult(weight_grams=float(best_rule_weight), matched_keyword=best_keyword)

    def match_weight_by_keywords(
        self,
        *,
        title: str | None,
        vendor: str | None,
        product_type: str | None,
        handle: str | None,
    ) -> WeightMatchResult:
        rules = self.get_matching_rules()
        return self.match_weight_from_rules(
            rules=rules,
            title=title,
            vendor=vendor,
            product_type=product_type,
            handle=handle,
        )
