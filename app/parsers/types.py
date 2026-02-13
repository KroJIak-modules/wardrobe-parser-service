from dataclasses import dataclass


@dataclass
class ParsedProduct:
    external_id: str
    name: str
    category: str | None
    price: float | None
    currency: str | None
    size: str | None
    additional_info: str | None
    size_data: list[dict] | None
    image_urls: list[str]
    product_url: str
    image_url: str | None
    description: str | None
