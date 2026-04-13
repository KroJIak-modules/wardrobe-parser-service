"""Pydantic schemas for Shopify parser endpoints."""

from pydantic import BaseModel, Field, model_validator

from app.core.config import settings


class ShopifyDiscoveryRequest(BaseModel):
    """Input payload for Shopify discovery endpoint."""

    source_key: str | None = Field(
        default=None,
        description="Ключ источника из файла sources.json (приоритетнее base_url)",
    )
    base_url: str | None = Field(
        default=None,
        description="Базовый домен Shopify-магазина. Можно не передавать, если указан source_key",
    )
    max_products: int = Field(
        default=settings.parser_default_max_products,
        ge=1,
        le=100000,
        description="Максимум URL товаров для discovery на один запуск",
    )
    sample_products: int = Field(
        default=settings.parser_default_sample_products,
        ge=1,
        le=1000,
        description="Сколько товаров загрузить для preview после discovery",
    )
    timeout_sec: float = Field(
        default=settings.parser_default_timeout_sec,
        ge=3.0,
        le=120.0,
        description="Таймаут одного HTTP-запроса в секундах",
    )
    fetch_all_products: bool = Field(
        default=False,
        description=(
            "Если true, parser попробует сходить в карточку каждого найденного товара "
            "и собрать полную статистику по ошибкам/успеху"
        ),
    )
    response_products_limit: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Максимум товаров, которые вернутся в поле previews ответа",
    )
    error_details_limit: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Максимум детальных ошибок в поле error_details",
    )
    parallel_workers: int = Field(
        default=settings.parser_default_parallel_workers,
        ge=1,
        le=64,
        description="Количество параллельных воркеров для обхода карточек одного сайта",
    )
    max_retries: int = Field(
        default=settings.parser_default_max_retries,
        ge=0,
        le=10,
        description="Количество повторных попыток на один сетевой запрос",
    )
    retry_backoff_sec: float = Field(
        default=settings.parser_default_retry_backoff_sec,
        ge=0.0,
        le=5.0,
        description="Базовая задержка между ретраями (экспоненциальный backoff)",
    )
    second_pass_enabled: bool = Field(
        default=settings.parser_default_second_pass_enabled,
        description="Если true, failed-карточки будут повторно обработаны отдельным вторым проходом",
    )
    second_pass_timeout_sec: float = Field(
        default=settings.parser_default_second_pass_timeout_sec,
        ge=3.0,
        le=240.0,
        description="Таймаут запроса на втором проходе",
    )

    @model_validator(mode="after")
    def validate_input_source(self) -> "ShopifyDiscoveryRequest":
        if self.source_key:
            return self
        if self.base_url:
            return self
        raise ValueError("Нужно передать source_key или base_url")


class ShopifyProductPreviewResponse(BaseModel):
    """Preview for one Shopify product loaded during discovery."""

    product_url: str
    handle: str
    product_id: str | None
    title: str | None
    vendor: str | None
    price: str | None
    currency: str | None
    payload_source: str


class ShopifySourceResponse(BaseModel):
    """Source record loaded from sources config file."""

    key: str
    name: str
    base_url: str
    parser_type: str
    enabled: bool
    notes: str | None


class ShopifySourceAdminResponse(BaseModel):
    """Source record for admin UI with runtime stats."""

    key: str
    source_id: int | None = None
    name: str
    base_url: str
    parser_type: str
    enabled: bool
    notes: str | None
    products_count: int = 0
    categories_count: int = 0
    supplier_id: int | None = None
    supplier_key: str | None = None
    supplier_name: str | None = None
    promo_factor: float = 1.0
    promo_only_no_discount: bool = False
    buyout_surcharge_value: float = 0.0
    buyout_surcharge_currency: str = "RUB"


class ShopifySourceToggleRequest(BaseModel):
    """Toggle source state for admin UI."""

    enabled: bool


class ShopifySourceSupplierRequest(BaseModel):
    """Update source pricing settings and supplier mapping."""

    supplier_id: int | None = Field(default=None, ge=1)
    promo_factor: float | None = Field(default=None, ge=0.1, le=5.0)
    promo_only_no_discount: bool | None = None
    buyout_surcharge_value: float | None = Field(default=None, ge=0.0, le=1000000.0)
    buyout_surcharge_currency: str | None = Field(default=None, min_length=3, max_length=3)


class ShopifyDiscoveryResponse(BaseModel):
    """Discovery diagnostic response."""

    source_key: str | None
    base_url: str
    parser_type: str
    sitemap_url: str
    discovery_mode: str
    product_sitemaps_found: int
    product_urls_found: int
    requested_previews: int
    products_fetch_attempted: int
    products_fetch_succeeded: int
    products_fetch_failed: int
    http_429_count: int
    http_5xx_count: int
    second_pass_attempted: int
    second_pass_recovered: int
    warnings: list[str]
    error_details: list[str]
    previews: list[ShopifyProductPreviewResponse]
