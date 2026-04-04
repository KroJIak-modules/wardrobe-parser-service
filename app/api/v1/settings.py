"""API endpoints for parser/admin settings."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.parser import (
    PricingSupplierCreateRequest,
    PricingSettingsResponse,
    PricingSupplierResponse,
    PricingSupplierUpdateRequest,
    PricingSettingsUpdateRequest,
    WeightRuleCreateRequest,
    WeightRuleKeywordRequest,
    WeightMissingProductResponse,
    WeightRuleResponse,
    WeightRuleUpdateRequest,
)
from app.services.settings.pricing_service import PricingSettingsService
from app.services.settings.weight_rule_service import WeightRuleService

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/pricing", response_model=PricingSettingsResponse)
def get_pricing_settings(db: Session = Depends(get_db)):
    service = PricingSettingsService(db)
    return service.get_settings()


@router.patch("/pricing", response_model=PricingSettingsResponse)
def update_pricing_settings(payload: PricingSettingsUpdateRequest, db: Session = Depends(get_db)):
    service = PricingSettingsService(db)
    return service.update_settings(payload)


@router.patch("/pricing/suppliers/{supplier_id}", response_model=PricingSupplierResponse)
def update_pricing_supplier(supplier_id: int, payload: PricingSupplierUpdateRequest, db: Session = Depends(get_db)):
    service = PricingSettingsService(db)
    return service.update_supplier(supplier_id=supplier_id, payload=payload)


@router.post("/pricing/suppliers", response_model=PricingSupplierResponse)
def create_pricing_supplier(payload: PricingSupplierCreateRequest, db: Session = Depends(get_db)):
    service = PricingSettingsService(db)
    return service.create_supplier(payload)


@router.delete("/pricing/suppliers/{supplier_id}")
def delete_pricing_supplier(supplier_id: int, db: Session = Depends(get_db)):
    service = PricingSettingsService(db)
    return service.delete_supplier(supplier_id)


@router.get("/weight-rules", response_model=list[WeightRuleResponse])
def list_weight_rules(db: Session = Depends(get_db)):
    service = WeightRuleService(db)
    return service.list_rules()


@router.get("/weight-rules/missing-products", response_model=list[WeightMissingProductResponse])
def list_missing_weight_products(limit: int = 500, db: Session = Depends(get_db)):
    service = WeightRuleService(db)
    return service.list_missing_weight_products(limit=limit)


@router.post("/weight-rules", response_model=WeightRuleResponse)
def create_weight_rule(payload: WeightRuleCreateRequest, db: Session = Depends(get_db)):
    service = WeightRuleService(db)
    return service.create_rule(payload)


@router.patch("/weight-rules/{rule_id}", response_model=WeightRuleResponse)
def update_weight_rule(rule_id: int, payload: WeightRuleUpdateRequest, db: Session = Depends(get_db)):
    service = WeightRuleService(db)
    return service.update_rule(rule_id, payload)


@router.delete("/weight-rules/{rule_id}")
def delete_weight_rule(rule_id: int, db: Session = Depends(get_db)):
    service = WeightRuleService(db)
    return service.delete_rule(rule_id)


@router.post("/weight-rules/{rule_id}/keywords")
def add_weight_rule_keyword(rule_id: int, payload: WeightRuleKeywordRequest, db: Session = Depends(get_db)):
    service = WeightRuleService(db)
    return service.add_keyword(rule_id, payload)


@router.delete("/weight-rules/{rule_id}/keywords/{keyword}")
def remove_weight_rule_keyword(rule_id: int, keyword: str, db: Session = Depends(get_db)):
    service = WeightRuleService(db)
    return service.remove_keyword(rule_id, keyword)
