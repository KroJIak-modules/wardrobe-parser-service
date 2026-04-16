"""
SQLAlchemy models for parser job orchestration and product delta tracking.
"""

from enum import Enum

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    JSON,
    DateTime,
    Boolean,
    ForeignKey,
    Text,
    Enum as SQLEnum,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


def _enum_values(enum_cls: type[Enum]) -> list[str]:
    """Return enum values for SQLAlchemy enum binding, not member names."""
    return [member.value for member in enum_cls]


class JobStatus(str, Enum):
    """Status of a parser job."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceRunStatus(str, Enum):
    """Status of parsing a single source."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    PARTIAL = "partial"  # Some products failed
    FAILED = "failed"

class ProductStatus(str, Enum):
    """Product availability status."""
    AVAILABLE = "available"
    OUT_OF_STOCK = "out_of_stock"
    HIDDEN = "hidden"
    UNAVAILABLE = "unavailable"


class DedupAction(str, Enum):
    """Moderator decision for duplicate candidate."""

    MERGE = "merge"
    REJECT = "reject"


class ParserSource(Base):
    """Parser source (e.g., Shopify store)."""
    __tablename__ = "parser_source"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    url = Column(String(2048), nullable=False, unique=True)
    parser_type = Column(String(50), nullable=False, default="shopify")  # shopify, custom, etc.
    enabled = Column(Boolean, nullable=False, default=True)
    supplier_id = Column(
        Integer,
        ForeignKey("parser_supplier.id", ondelete="RESTRICT"),
        nullable=False,
        server_default="1",
    )
    promo_factor = Column(Float, nullable=False, default=1.0, server_default="1")
    promo_only_no_discount = Column(Boolean, nullable=False, default=False, server_default="false")
    buyout_surcharge_value = Column(Float, nullable=False, default=0.0, server_default="0")
    buyout_surcharge_currency = Column(String(3), nullable=False, default="RUB", server_default="RUB")
    config = Column(Text, nullable=True)  # JSON for source-specific config
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # Soft delete

    products = relationship("ParserProduct", back_populates="source")
    supplier = relationship("ParserSupplier", back_populates="sources")

    __table_args__ = (
        Index("idx_parser_source_enabled", "enabled"),
        Index("idx_parser_source_supplier_id", "supplier_id"),
        Index("idx_parser_source_deleted_at", "deleted_at"),
    )


class ParserJob(Base):
    """Represents a full sync job across all or selected sources."""
    __tablename__ = "parser_job"

    id = Column(String(36), primary_key=True)  # UUID
    status = Column(
        SQLEnum(JobStatus, values_callable=_enum_values),
        nullable=False,
        default=JobStatus.PENDING,
    )
    triggered_by = Column(String(50), nullable=False)  # "scheduled" or "manual"
    
    total_products = Column(Integer, nullable=True)
    new_products = Column(Integer, nullable=True, default=0)
    updated_products = Column(Integer, nullable=True, default=0)
    new_images = Column(Integer, nullable=True, default=0)
    
    error_count = Column(Integer, nullable=False, default=0)
    http_429_count = Column(Integer, nullable=False, default=0)
    http_5xx_count = Column(Integer, nullable=False, default=0)
    
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # Soft delete

    source_runs = relationship("ParserJobSourceRun", back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_parser_job_status", "status"),
        Index("idx_parser_job_created_at", "created_at"),
        Index("idx_parser_job_triggered_by", "triggered_by"),
        Index("idx_parser_job_deleted_at", "deleted_at"),
    )


class ParserJobSourceRun(Base):
    """Represents parsing a single source within a job."""
    __tablename__ = "parser_job_source_run"

    id = Column(Integer, primary_key=True)
    job_id = Column(String(36), ForeignKey("parser_job.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("parser_source.id"), nullable=False)
    
    status = Column(
        SQLEnum(SourceRunStatus, values_callable=_enum_values),
        nullable=False,
        default=SourceRunStatus.PENDING,
    )
    
    products_discovered = Column(Integer, nullable=False, default=0)
    products_fetched = Column(Integer, nullable=False, default=0)
    products_failed = Column(Integer, nullable=False, default=0)
    
    error_message = Column(Text, nullable=True)
    discovery_mode = Column(String(50), nullable=True)  # "sitemap", "fallback", "mixed"
    
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    job = relationship("ParserJob", back_populates="source_runs")
    source = relationship("ParserSource")

    __table_args__ = (
        UniqueConstraint("job_id", "source_id", name="uq_job_source"),
        Index("idx_parser_job_source_run_job_id", "job_id"),
        Index("idx_parser_job_source_run_source_id", "source_id"),
        Index("idx_parser_job_source_run_status", "status"),
    )


class ParserProduct(Base):
    """Product discovered by parser."""
    __tablename__ = "parser_product"

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("parser_source.id"), nullable=False)
    
    handle = Column(String(1024), nullable=False)
    title = Column(String(2048), nullable=False)
    vendor = Column(String(255), nullable=True)
    product_type = Column(String(255), nullable=True)
    
    url = Column(String(2048), nullable=False, unique=True)
    price = Column(Float, nullable=True)
    currency = Column(String(3), nullable=False, default="USD")
    
    status = Column(
        SQLEnum(ProductStatus, values_callable=_enum_values),
        nullable=False,
        default=ProductStatus.AVAILABLE,
    )
    image_count = Column(Integer, nullable=False, default=0)
    image_urls = Column(JSON, nullable=False, default=list)
    image_asset_ids = Column(JSON, nullable=False, default=list)
    weight_grams = Column(Float, nullable=True)
    weight_source = Column(String(32), nullable=True)
    weight_match_keyword = Column(String(255), nullable=True)
    weight_value = Column(Float, nullable=True)
    weight_unit = Column(String(16), nullable=True)
    
    variants = Column(JSON, nullable=False, default=list)  # Size/color variants with availability
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # Soft delete

    source = relationship("ParserSource", back_populates="products")

    __table_args__ = (
        UniqueConstraint("source_id", "handle", name="uq_source_handle"),
        Index("idx_parser_product_source_id", "source_id"),
        Index("idx_parser_product_handle", "handle"),
        Index("idx_parser_product_vendor", "vendor"),
        Index("idx_parser_product_status", "status"),
        Index("idx_parser_product_weight_grams", "weight_grams"),
        Index("idx_parser_product_weight_source", "weight_source"),
        Index("idx_parser_product_deleted_at", "deleted_at"),
    )

class ImageAsset(Base):
    """Cached or stored product images."""
    __tablename__ = "image_asset"

    id = Column(Integer, primary_key=True)
    
    source_url = Column(String(2048), nullable=False, unique=True)
    storage_mode = Column(String(50), nullable=False, default="proxy")  # proxy or stored_file
    stored_path = Column(String(2048), nullable=True)  # Local file path if stored
    
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    file_size = Column(Integer, nullable=True)
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_image_asset_storage_mode", "storage_mode"),
        Index("idx_image_asset_deleted_at", "deleted_at"),
    )


class ParserDedupDecision(Base):
    """Stored moderator decision for a pair of products."""

    __tablename__ = "parser_dedup_decision"

    id = Column(Integer, primary_key=True)
    pair_key = Column(String(64), nullable=False, unique=True)
    left_product_id = Column(Integer, ForeignKey("parser_product.id"), nullable=False)
    right_product_id = Column(Integer, ForeignKey("parser_product.id"), nullable=False)
    action = Column(String(20), nullable=False)
    merged_into_product_id = Column(Integer, ForeignKey("parser_product.id"), nullable=True)

    decided_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_parser_dedup_decision_action", "action"),
        Index("idx_parser_dedup_decision_left", "left_product_id"),
        Index("idx_parser_dedup_decision_right", "right_product_id"),
    )
