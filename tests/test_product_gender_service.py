from app.services.product_gender_service import ProductGenderService


def test_infer_prefers_tags_before_other_fields() -> None:
    gender = ProductGenderService.infer(
        normalized_product={
            "tags": ["women", "summer-drop"],
            "category": "Men Jacket",
            "title": "Classic jacket",
            "description": "Unisex fit",
        },
        raw_product={},
        source_key="demo.com",
    )
    assert gender == "female"


def test_infer_falls_through_ambiguous_tags_to_title() -> None:
    gender = ProductGenderService.infer(
        normalized_product={
            "tags": ["mens", "womens"],
            "category": "",
            "title": "Women's leather sandals",
            "description": None,
        },
        raw_product={},
        source_key="demo.com",
    )
    assert gender == "female"


def test_infer_uses_grailed_source_specific_signals() -> None:
    gender = ProductGenderService.infer(
        normalized_product={
            "tags": [],
            "category": "",
            "title": "Vintage leather jacket",
            "description": "",
        },
        raw_product={
            "source_gender_hints": {
                "department": "womenswear",
                "category_path": "womens_outerwear.coats",
            }
        },
        source_key="grailed.com",
    )
    assert gender == "female"


def test_infer_uses_vinted_root_breadcrumb_signal() -> None:
    gender = ProductGenderService.infer(
        normalized_product={
            "tags": [],
            "category": "",
            "title": "Nike Air Max 98",
            "description": "",
        },
        raw_product={
            "source_gender_hints": {
                "root_breadcrumb_title": "Women",
                "root_breadcrumb_href": "/catalog/1904-women",
            }
        },
        source_key="vinted.com",
    )
    assert gender == "female"


def test_infer_defaults_to_unisex() -> None:
    gender = ProductGenderService.infer(
        normalized_product={
            "tags": [],
            "category": "Boots",
            "title": "Black sidezip boots",
            "description": "",
        },
        raw_product={},
        source_key="demo.com",
    )
    assert gender == "unisex"
