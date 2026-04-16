"""Repositories for supplier entities used in pricing formula."""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import case

from app.models import ParserSupplier, ParserSupplierShippingRate
from app.repositories.base import BaseRepository


class ParserSupplierRepository(BaseRepository[ParserSupplier]):
    """Data access for parser suppliers and SSR rate rows."""

    def __init__(self, session: Session):
        super().__init__(session, ParserSupplier)

    def get_by_key(self, key: str) -> ParserSupplier | None:
        return self.query().filter(ParserSupplier.key == key).first()

    def get_fallback_supplier(self) -> ParserSupplier | None:
        return (
            self.query()
            .order_by(
                case((ParserSupplier.category == "main", 0), else_=1).asc(),
                ParserSupplier.id.asc(),
            )
            .first()
        )

    def list_all_with_rates(self) -> list[ParserSupplier]:
        return (
            self.query()
            .options(joinedload(ParserSupplier.shipping_rates))
            .order_by(ParserSupplier.id.asc())
            .all()
        )

    def ensure_linear_rates(self, *, supplier_id: int, per_500g_rub: float, max_step_500g: int) -> None:
        rates = (
            self.session.query(ParserSupplierShippingRate)
            .filter(ParserSupplierShippingRate.supplier_id == supplier_id)
            .all()
        )
        by_step = {int(round(float(item.max_kg or 0) / 0.5)): item for item in rates if item.max_kg is not None}
        target_steps = max(1, int(max_step_500g))
        for step in range(1, target_steps + 1):
            value = float(step) * float(per_500g_rub)
            existing = by_step.get(step)
            min_kg = float(step - 1) * 0.5
            max_kg = float(step) * 0.5
            if existing:
                existing.min_kg = min_kg
                existing.max_kg = max_kg
                existing.rate_rub = value
            else:
                self.session.add(
                    ParserSupplierShippingRate(
                        supplier_id=supplier_id,
                        min_kg=min_kg,
                        max_kg=max_kg,
                        rate_rub=value,
                    )
                )
        for step, item in by_step.items():
            if step > target_steps:
                self.session.delete(item)
