"""Service layer for dedup candidates and moderation actions."""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import combinations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import DedupAction, ParserProduct
from app.repositories import ParserDedupDecisionRepository, ParserProductRepository
from app.schemas.parser import (
    DedupCandidateListResponse,
    DedupCandidateResponse,
    DedupMergeRequest,
    DedupRejectRequest,
    ProductResponse,
)


class DedupService:
    """Encapsulates duplicate detection and moderation business rules."""

    def __init__(self, db: Session):
        self.db = db
        self.product_repo = ParserProductRepository(db)
        self.decision_repo = ParserDedupDecisionRepository(db)

    @staticmethod
    def _pair_key(a: int, b: int) -> str:
        left, right = sorted([a, b])
        return f"{left}:{right}"

    @staticmethod
    def _normalize_title(title: str) -> str:
        return " ".join(title.strip().lower().split())

    @staticmethod
    def _normalize_vendor(vendor: str | None) -> str:
        return (vendor or "").strip().lower()

    def _candidate_score(self, left: ParserProduct, right: ParserProduct) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.0

        if self._normalize_title(left.title) == self._normalize_title(right.title):
            score += 0.55
            reasons.append("title_match")

        if self._normalize_vendor(left.vendor) and self._normalize_vendor(left.vendor) == self._normalize_vendor(right.vendor):
            score += 0.25
            reasons.append("vendor_match")

        if left.price is not None and right.price is not None:
            max_price = max(left.price, right.price)
            diff = abs(left.price - right.price)
            if max_price > 0 and diff / max_price <= 0.08:
                score += 0.15
                reasons.append("price_close")

        if left.handle == right.handle:
            score += 0.2
            reasons.append("handle_match")

        return min(score, 0.99), reasons

    def get_candidates(self, limit: int = 30) -> DedupCandidateListResponse:
        products = self.product_repo.filter_products(limit=2000)

        buckets: dict[tuple[str, str], list[ParserProduct]] = {}
        for product in products:
            key = (self._normalize_title(product.title), self._normalize_vendor(product.vendor))
            buckets.setdefault(key, []).append(product)

        candidates: list[DedupCandidateResponse] = []
        for bucket_items in buckets.values():
            if len(bucket_items) < 2:
                continue

            for left, right in combinations(bucket_items, 2):
                key = self._pair_key(left.id, right.id)
                if self.decision_repo.get_by_pair_key(key):
                    continue

                score, reasons = self._candidate_score(left, right)
                if score < 0.55:
                    continue

                candidates.append(
                    DedupCandidateResponse(
                        pair_key=key,
                        score=score,
                        reasons=reasons,
                        left=ProductResponse.model_validate(left),
                        right=ProductResponse.model_validate(right),
                    )
                )
                if len(candidates) >= limit:
                    return DedupCandidateListResponse(items=candidates, total=len(candidates), limit=limit)

        return DedupCandidateListResponse(items=candidates, total=len(candidates), limit=limit)

    def merge_duplicate(self, payload: DedupMergeRequest) -> dict:
        if payload.primary_product_id == payload.duplicate_product_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="IDs должны отличаться")

        primary = self.product_repo.get_by_id(payload.primary_product_id)
        duplicate = self.product_repo.get_by_id(payload.duplicate_product_id)

        if not primary or primary.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Primary product не найден")
        if not duplicate or duplicate.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Duplicate product не найден")

        # Keep richer values on the product that survives merge.
        if not primary.vendor and duplicate.vendor:
            primary.vendor = duplicate.vendor
        if not primary.product_type and duplicate.product_type:
            primary.product_type = duplicate.product_type
        if primary.image_count < duplicate.image_count:
            primary.image_count = duplicate.image_count

        duplicate.deleted_at = datetime.now(timezone.utc)

        key = self._pair_key(primary.id, duplicate.id)
        decision = self.decision_repo.get_by_pair_key(key)
        if decision:
            decision.action = DedupAction.MERGE.value
            decision.left_product_id = min(primary.id, duplicate.id)
            decision.right_product_id = max(primary.id, duplicate.id)
            decision.merged_into_product_id = primary.id
            decision.decided_at = datetime.now(timezone.utc)
        else:
            self.decision_repo.create(
                pair_key=key,
                left_product_id=min(primary.id, duplicate.id),
                right_product_id=max(primary.id, duplicate.id),
                action=DedupAction.MERGE.value,
                merged_into_product_id=primary.id,
            )

        self.db.commit()
        return {"ok": True, "merged_into_product_id": primary.id, "removed_product_id": duplicate.id}

    def reject_duplicate(self, payload: DedupRejectRequest) -> dict:
        if payload.product_a_id == payload.product_b_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="IDs должны отличаться")

        left = self.product_repo.get_by_id(payload.product_a_id)
        right = self.product_repo.get_by_id(payload.product_b_id)
        if not left or left.deleted_at is not None or not right or right.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Одна из карточек не найдена")

        key = self._pair_key(left.id, right.id)
        decision = self.decision_repo.get_by_pair_key(key)
        if decision:
            decision.action = DedupAction.REJECT.value
            decision.left_product_id = min(left.id, right.id)
            decision.right_product_id = max(left.id, right.id)
            decision.merged_into_product_id = None
            decision.decided_at = datetime.now(timezone.utc)
        else:
            self.decision_repo.create(
                pair_key=key,
                left_product_id=min(left.id, right.id),
                right_product_id=max(left.id, right.id),
                action=DedupAction.REJECT.value,
                merged_into_product_id=None,
            )

        self.db.commit()
        return {"ok": True, "pair_key": key}
