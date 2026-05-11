from app.adapters.professore_v1 import ProfessoreV1Adapter


def test_extract_handle_from_product_url() -> None:
    assert ProfessoreV1Adapter._extract_handle('https://professor-e.com/products/example-handle') == 'example-handle'


def test_extract_handle_from_nested_product_url() -> None:
    assert ProfessoreV1Adapter._extract_handle('https://professor-e.com/en/products/example-handle') == 'example-handle'


def test_extract_handle_decodes_percent_encoded_product_url() -> None:
    assert ProfessoreV1Adapter._extract_handle('https://professor-e.com/products/test%C2%AE-product') == 'test®-product'
