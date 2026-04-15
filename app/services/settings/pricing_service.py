"""Pricing settings CRUD and formula metadata for admin panel."""

from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import ParserSupplier
from app.repositories import ParserPricingSettingsRepository, ParserSourceRepository, ParserSupplierRepository
from app.schemas.parser import (
    PricingSupplierCreateRequest,
    PricingSettingsResponse,
    PricingSettingsUpdateRequest,
    PricingSupplierResponse,
    PricingSupplierUpdateRequest,
)


_FORMULA_LINES = [
    "CDT_EUR = max(0, (SP_EUR - THR_EUR)) * DUTY",
    "STEP = ceil((WEIGHT_G * WT) / 500)",
    "STC_RUB = SSR[SUPPLIER][STEP]",
    "BSC_RUB = buyout surcharge in source currency converted to RUB",
    "SP_AFTER_PROMO_RUB = SP_RUB * PROMO",
    "TP_RUB = SP_AFTER_PROMO_RUB + BSC_RUB + CDT_RUB + STC_RUB",
    "FP_RUB = ceil(TP_RUB * MP)",
]

_FORMULA_LATEX = (
    r"\left\lceil\left(SP_{RUB}\cdot PROMO + BSC_{RUB} + \max(0,SP_{EUR}-THR_{EUR})\cdot DUTY\cdot EUR2RUB + "
    r"SSR_{SUPPLIER,\left\lceil\frac{WEIGHT_G\cdot WT}{500}\right\rceil}\right)\cdot MP\right\rceil"
)

_FORMULA_LEGEND = [
    {"key": "SP", "description": "Seller price (исходная цена товара)"},
    {"key": "SP_EUR", "description": "Цена товара, приведенная к EUR"},
    {"key": "SP_RUB", "description": "Цена товара, приведенная к RUB"},
    {"key": "THR_EUR", "description": "Порог для расчета пошлины в EUR"},
    {"key": "DUTY", "description": "Ставка пошлины"},
    {"key": "EUR2RUB", "description": "Курс EUR к RUB"},
    {"key": "CDT_EUR", "description": "Пошлина в EUR"},
    {"key": "CDT_RUB", "description": "Пошлина в RUB"},
    {"key": "STC_RUB", "description": "Транспортировка поставщиком в RUB"},
    {"key": "BSC_RUB", "description": "Доплата к стоимости выкупа в RUB"},
    {"key": "MP", "description": "Коэффициент наценки"},
    {"key": "WT", "description": "Коэффициент погрешности веса"},
    {"key": "WEIGHT_G", "description": "Вес товара в граммах"},
    {"key": "STEP", "description": "Вычисленный номер шага веса для SSR"},
    {"key": "PROMO", "description": "Коэффициент промокода"},
    {"key": "SUPPLIER", "description": "Поставщик, привязанный к источнику магазина"},
    {"key": "SSR[SUPPLIER][STEP]", "description": "Тариф по таблице поставщика и шагу веса"},
    {"key": "FP_RUB", "description": "Финальная цена для витрины"},
]

class PricingSettingsService:
    """Manage pricing settings and calculate final customer price."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = ParserPricingSettingsRepository(db)
        self.supplier_repo = ParserSupplierRepository(db)
        self.source_repo = ParserSourceRepository(db)

    def _bootstrap_suppliers(self) -> bool:
        changed = False
        if self.supplier_repo.get_by_key("default") is None:
            changed = True
        default_supplier = self.supplier_repo.get_default_supplier()
        if not default_supplier.shipping_rates:
            self.supplier_repo.ensure_linear_rates(
                supplier_id=default_supplier.id,
                per_500g_rub=0.0,
                max_step_500g=120,
            )
            self.db.flush()
            changed = True
        return changed

    @staticmethod
    def _normalize_currency(raw: str | None, *, default: str = "RUB") -> str:
        value = (raw or default).strip().upper()
        if value not in {"RUB", "USD", "EUR", "GBP"}:
            return default
        return value

    @staticmethod
    def _normalize_supplier_category(raw: str | None, *, default: str = "main") -> str:
        value = (raw or default).strip().lower()
        if value not in {"main", "alt"}:
            return default
        return value

    @staticmethod
    def _to_rub(value: float, currency: str, *, usd_to_rub: float, eur_to_rub: float) -> float:
        normalized = PricingSettingsService._normalize_currency(currency)
        if normalized == "RUB":
            return float(value)
        if normalized == "USD":
            return float(value) * float(usd_to_rub)
        return float(value) * float(eur_to_rub)

    @staticmethod
    def _from_rub(value_rub: float, currency: str, *, usd_to_rub: float, eur_to_rub: float) -> float:
        normalized = PricingSettingsService._normalize_currency(currency)
        if normalized == "RUB":
            return float(value_rub)
        if normalized == "USD":
            return float(value_rub) / float(usd_to_rub) if usd_to_rub > 0 else 0.0
        return float(value_rub) / float(eur_to_rub) if eur_to_rub > 0 else 0.0

    def get_settings(self) -> PricingSettingsResponse:
        bootstrap_changed = self._bootstrap_suppliers()
        entity, created = self.repo.get_or_create_default()
        if created or bootstrap_changed:
            self.db.commit()
            self.db.refresh(entity)
        suppliers = self.supplier_repo.list_all_with_rates()
        return self._to_response(entity, suppliers=suppliers)

    def update_settings(self, payload: PricingSettingsUpdateRequest) -> PricingSettingsResponse:
        self._bootstrap_suppliers()
        entity, created = self.repo.get_or_create_default()
        patch = payload.model_dump(exclude_none=True)
        if "customs_threshold_currency" in patch:
            patch["customs_threshold_currency"] = self._normalize_currency(
                patch.get("customs_threshold_currency"),
                default=self._normalize_currency(getattr(entity, "customs_threshold_currency", None), default="EUR"),
            )
        for key, value in patch.items():
            setattr(entity, key, value)
        self.db.commit()
        if created or patch:
            self.db.refresh(entity)
        suppliers = self.supplier_repo.list_all_with_rates()
        return self._to_response(entity, suppliers=suppliers)

    @staticmethod
    def _to_response(entity, *, suppliers: list[ParserSupplier]) -> PricingSettingsResponse:
        svc_rules = getattr(entity, "svc_rules", None) or []
        if isinstance(svc_rules, str):
            try:
                import json
                svc_rules = json.loads(svc_rules)
            except Exception:
                svc_rules = []
        return PricingSettingsResponse(
            markup_multiplier=float(entity.markup_multiplier),
            weight_tolerance=float(entity.weight_tolerance),
            promo_factor=float(entity.promo_factor),
            customs_threshold_eur=float(entity.customs_threshold_eur),
            customs_threshold_currency=PricingSettingsService._normalize_currency(
                getattr(entity, "customs_threshold_currency", None),
                default="EUR",
            ),
            customs_duty_rate=float(entity.customs_duty_rate),
            usd_to_rub=float(entity.usd_to_rub),
            eur_to_rub=float(entity.eur_to_rub),
            suppliers=[
                PricingSettingsService._supplier_to_response(
                    item,
                    usd_to_rub=float(entity.usd_to_rub),
                    eur_to_rub=float(entity.eur_to_rub),
                )
                for item in suppliers
            ],
            formula_latex=_FORMULA_LATEX,
            formula_lines=list(_FORMULA_LINES),
            formula_legend=[dict(item) for item in _FORMULA_LEGEND],
            svc_rules=svc_rules,
            pricing_supplier_updated_at=getattr(entity, "updated_at", None).isoformat() if getattr(entity, "updated_at", None) else None,
        )

    @staticmethod
    def _supplier_to_response(
        supplier: ParserSupplier,
        *,
        usd_to_rub: float,
        eur_to_rub: float,
    ) -> PricingSupplierResponse:
        rates = sorted(supplier.shipping_rates, key=lambda item: item.step_500g)
        if rates:
            first_step = max(1, int(rates[0].step_500g))
            rate_per_500g = float(rates[0].rate_rub) / float(first_step)
        else:
            rate_per_500g = 0.0
        rate_currency = PricingSettingsService._normalize_currency(getattr(supplier, "rate_currency", None), default="RUB")
        rate_per_500g_value = PricingSettingsService._from_rub(
            rate_per_500g,
            rate_currency,
            usd_to_rub=usd_to_rub,
            eur_to_rub=eur_to_rub,
        )
        max_step = int(rates[-1].step_500g) if rates else 0
        return PricingSupplierResponse(
            id=int(supplier.id),
            key=supplier.key,
            name=supplier.name,
            category=PricingSettingsService._normalize_supplier_category(getattr(supplier, "category", None)),
            rate_currency=rate_currency,
            rate_per_500g_value=rate_per_500g_value,
            rate_per_500g_rub=rate_per_500g,
            max_step_500g=max_step,
            rates=[
                {
                    "step_500g": int(rate.step_500g),
                    "rate_rub": float(rate.rate_rub),
                }
                for rate in rates
            ],
        )

    def update_supplier(self, supplier_id: int, payload: PricingSupplierUpdateRequest) -> PricingSupplierResponse:
        self._bootstrap_suppliers()
        supplier = self.supplier_repo.get_by_id(supplier_id)
        if supplier is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Поставщик не найден",
            )

        patch = payload.model_dump(exclude_none=True)
        settings_entity, _ = self.repo.get_or_create_default()
        for key in ("name",):
            if key in patch:
                setattr(supplier, key, patch[key])
        if "category" in patch:
            supplier.category = self._normalize_supplier_category(patch.get("category"), default=supplier.category)
        if "rate_currency" in patch:
            supplier.rate_currency = self._normalize_currency(patch.get("rate_currency"), default=supplier.rate_currency)

        current_rates = sorted(supplier.shipping_rates, key=lambda item: item.step_500g)
        if current_rates:
            first_step = max(1, int(current_rates[0].step_500g))
            current_rate_per_500g = float(current_rates[0].rate_rub) / float(first_step)
        else:
            current_rate_per_500g = 0.0
        current_max_step = int(current_rates[-1].step_500g) if current_rates else 120
        active_currency = self._normalize_currency(
            patch.get("rate_currency"),
            default=self._normalize_currency(getattr(supplier, "rate_currency", None), default="RUB"),
        )
        if "rate_per_500g_value" in patch:
            target_rate_per_500g = self._to_rub(
                float(patch.get("rate_per_500g_value")),
                active_currency,
                usd_to_rub=float(settings_entity.usd_to_rub),
                eur_to_rub=float(settings_entity.eur_to_rub),
            )
        else:
            target_rate_per_500g = float(patch.get("rate_per_500g_rub", current_rate_per_500g))
        target_max_step = int(patch.get("max_step_500g", current_max_step))
        if "rate_per_500g_rub" in patch or "rate_per_500g_value" in patch or "max_step_500g" in patch:
            self.supplier_repo.ensure_linear_rates(
                supplier_id=supplier.id,
                per_500g_rub=target_rate_per_500g,
                max_step_500g=target_max_step,
            )

        self.db.commit()
        refreshed = self.supplier_repo.get_by_id(supplier.id)
        if refreshed is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Поставщик не найден после обновления",
            )
        self.db.refresh(refreshed)
        return self._supplier_to_response(
            refreshed,
            usd_to_rub=float(settings_entity.usd_to_rub),
            eur_to_rub=float(settings_entity.eur_to_rub),
        )

    def create_supplier(self, payload: PricingSupplierCreateRequest) -> PricingSupplierResponse:
        self._bootstrap_suppliers()

        base_key = (payload.key or "").strip().lower()
        if not base_key:
            base_key = re.sub(r"[^a-z0-9]+", "-", payload.name.lower()).strip("-")
        if not base_key:
            base_key = "supplier"

        key = base_key
        suffix = 2
        while self.supplier_repo.get_by_key(key) is not None:
            key = f"{base_key}-{suffix}"
            suffix += 1

        self.db.execute(
            text(
                """
                SELECT setval(
                    pg_get_serial_sequence('parser_supplier', 'id'),
                    COALESCE((SELECT MAX(id) FROM parser_supplier), 1),
                    true
                )
                """
            )
        )
        supplier = self.supplier_repo.create(
            key=key,
            name=payload.name.strip(),
            category=self._normalize_supplier_category(payload.category, default="main"),
            rate_currency=self._normalize_currency(payload.rate_currency, default="RUB"),
        )
        self.supplier_repo.flush()
        settings_entity, _ = self.repo.get_or_create_default()
        per_500g_rub = self._to_rub(
            float(payload.rate_per_500g_value),
            self._normalize_currency(payload.rate_currency, default="RUB"),
            usd_to_rub=float(settings_entity.usd_to_rub),
            eur_to_rub=float(settings_entity.eur_to_rub),
        )
        self.supplier_repo.ensure_linear_rates(
            supplier_id=supplier.id,
            per_500g_rub=per_500g_rub,
            max_step_500g=int(payload.max_step_500g),
        )
        self.db.commit()
        created = self.supplier_repo.get_by_id(int(supplier.id))
        if created is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось создать поставщика",
            )
        return self._supplier_to_response(
            created,
            usd_to_rub=float(settings_entity.usd_to_rub),
            eur_to_rub=float(settings_entity.eur_to_rub),
        )

    def delete_supplier(self, supplier_id: int) -> dict[str, str]:
        supplier = self.supplier_repo.get_by_id(supplier_id)
        if supplier is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Поставщик не найден",
            )
        if supplier.key == "default":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя удалить поставщика default",
            )
        assigned_sources = self.source_repo.count_by_supplier_id(supplier.id)
        if assigned_sources > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Нельзя удалить: поставщик назначен на {assigned_sources} источников",
            )
        try:
            self.db.delete(supplier)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Нельзя удалить поставщика: есть связанные записи",
            )
        return {"status": "ok", "message": "Поставщик удален"}
