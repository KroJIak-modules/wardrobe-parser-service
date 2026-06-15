from app.services.sync_orchestrator_service import SyncOrchestratorService


def test_build_product_batch_items_skips_valid_products_without_variants() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "variants": [],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert items == []


def test_build_product_batch_items_keeps_valid_products_with_variants() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": True}
                ],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert len(items[0]["variants"]) == 1
    assert items[0]["gender"] == "unisex"


def test_build_product_batch_items_skips_unavailable_missing_weight_without_variants() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[],
        unavailable_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "variants": [],
                "status": "unavailable",
                "status_reasons": ["missing_weight"],
            }
        ],
    )
    assert items == []


def test_build_product_batch_items_keeps_unavailable_missing_weight_with_variants() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[],
        unavailable_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": False}
                ],
                "status": "unavailable",
                "status_reasons": ["missing_weight"],
            }
        ],
    )
    assert len(items) == 1
    assert len(items[0]["variants"]) == 1


def test_build_product_batch_items_preserves_gender() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "gender": "female",
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": True}
                ],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert items[0]["gender"] == "female"


def test_build_product_batch_items_emits_designer_category_and_nullable_status_reason() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "designer": "Rick Owens",
                "category": "Outerwear",
                "status_reason": "missing_weight",
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": True}
                ],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert items[0]["designer"] == "Rick Owens"
    assert items[0]["category"] == "Outerwear"
    assert items[0]["status_reason"] == "missing_weight"


def test_build_product_batch_items_sets_null_status_reason_when_absent() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "designer": "Rick Owens",
                "category": "Outerwear",
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": True}
                ],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert items[0]["status_reason"] is None


def test_build_product_batch_items_emits_product_source_ref() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "source_ref": {
                    "external_id": "ext-123",
                },
                "handle": "a",
                "title": "A",
                "description": "A",
                "designer": "Rick Owens",
                "category": "Outerwear",
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": True}
                ],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert items[0]["source_ref"] == {
        "external_id": "ext-123",
    }
