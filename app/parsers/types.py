from dataclasses import dataclass


@dataclass
class ParsedProduct:
    external_id: str
    name: str
    category: str | None
    price: float | None
    currency: str | None
    product_url: str
    image_url: str | None
    description: str | None
    raw_data: dict | None
