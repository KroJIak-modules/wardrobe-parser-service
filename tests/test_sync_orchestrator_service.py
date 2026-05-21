from app.services.sync_orchestrator_service import SyncOrchestratorService


def test_build_product_batch_items_skips_valid_products_without_variants() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        source_key="demo.com",
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "price": 100,
                "currency": "USD",
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
        source_key="demo.com",
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "price": 100,
                "currency": "USD",
                "variants": [
                    {"id": "v1", "title": "One", "price": 100, "currency": "USD", "available": True}
                ],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert len(items[0]["variants"]) == 1


def test_build_product_batch_items_skips_unavailable_missing_weight_without_variants() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        source_key="demo.com",
        valid_products=[],
        unavailable_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "price": 100,
                "currency": "USD",
                "variants": [],
                "status": "unavailable",
                "unavailable_reasons": ["missing_weight"],
            }
        ],
    )
    assert items == []


def test_build_product_batch_items_keeps_unavailable_missing_weight_with_variants() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        source_key="demo.com",
        valid_products=[],
        unavailable_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "price": 100,
                "currency": "USD",
                "variants": [
                    {"id": "v1", "title": "One", "price": 100, "currency": "USD", "available": False}
                ],
                "status": "unavailable",
                "unavailable_reasons": ["missing_weight"],
            }
        ],
    )
    assert len(items) == 1
    assert len(items[0]["variants"]) == 1
