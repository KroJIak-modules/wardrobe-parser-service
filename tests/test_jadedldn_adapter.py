from app.adapters.jadedldn_v1 import JadedldnV1Adapter


def test_extract_handle_from_product_url() -> None:
    assert JadedldnV1Adapter._extract_handle('https://jadedldn.com/products/example-handle') == 'example-handle'


def test_extract_handle_from_nested_product_url() -> None:
    assert JadedldnV1Adapter._extract_handle('https://jadedldn.com/en-us/products/example-handle') == 'example-handle'
