from datetime import datetime

from pydantic import BaseModel, Field


class ProductResponse(BaseModel):
    id: int
    site_id: int
    external_id: str = Field(..., max_length=128)
    name: str
    category: str | None = None
    price: float | None = None
    currency: str | None = None
    size: str | None = None
    additional_info: str | None = None
    size_data: list[dict] | None = None
    image_urls: list[str] | None = None
    product_url: str
    image_url: str | None = None
    description: str | None = None
    parsed_at: datetime | None = None
    pending_sync: bool

    class Config:
        from_attributes = True
