from app.adapters.archived_v1 import ArchivedV1Adapter


def test_archived_adapter_uses_category_when_title_matches_designer() -> None:
    draft = ArchivedV1Adapter().normalize_product(
        {
            "url": "https://archived.co/products/rick-owens-17",
            "handle": "rick-owens-17",
            "title": "Rick Owens",
            "vendor": "Rick Owens",
            "designer": "Rick Owens",
            "product_type": "Shield Wader Kiss Boots",
            "category": "Shield Wader Kiss Boots",
            "variants": [{"title": "10", "price": "2700.00", "currency": "USD", "available": True}],
        }
    )

    assert draft["title"] == "Shield Wader Kiss Boots"


def test_archived_adapter_appends_product_type_when_title_differs_from_designer() -> None:
    draft = ArchivedV1Adapter().normalize_product(
        {
            "url": "https://archived.co/products/undercover-aw02",
            "handle": "undercover-aw02",
            "title": "Witch's Cell Division Hybrid Cargos",
            "vendor": "Undercover",
            "designer": "Undercover",
            "product_type": "Flare Denim",
            "category": "Flare Denim",
            "variants": [{"title": "M", "price": "900.00", "currency": "USD", "available": True}],
        }
    )

    assert draft["title"] == "Witch's Cell Division Hybrid Cargos | Flare Denim"
