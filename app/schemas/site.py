from datetime import datetime

from pydantic import BaseModel, Field


class SiteResponse(BaseModel):
    id: int
    key: str = Field(..., max_length=64)
    name: str = Field(..., max_length=255)
    base_url: str | None = Field(default=None, max_length=512)
    is_active: bool
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None

    class Config:
        from_attributes = True
