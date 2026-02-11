from pydantic import BaseModel


class ParserStatus(BaseModel):
    site_key: str
    is_active: bool
    last_run_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    last_error_at: str | None = None


class ParseResponse(BaseModel):
    created: int
    updated: int
