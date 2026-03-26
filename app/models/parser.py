"""
SQLAlchemy models for parser job orchestration and product delta tracking.
"""

from datetime import datetime, timezone
from typing import Optional
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


class DeltaType(str, Enum):
    """Type of change detected in product."""
    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    DELETED = "deleted"


class ProductStatus(str, Enum):
    """Product availability status."""
    AVAILABLE = "available"
    OUT_OF_STOCK = "out_of_stock"
    DISCONTINUED = "discontinued"


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
    config = Column(Text, nullable=True)  # JSON for source-specific config
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # Soft delete

    products = relationship("ParserProduct", back_populates="source")
    fingerprints = relationship("ParserProductFingerprint", back_populates="source")

    __table_args__ = (
        Index("idx_parser_source_enabled", "enabled"),
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
    deltas = relationship("ParserProductDelta", back_populates="job", cascade="all, delete-orphan")

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
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # Soft delete

    source = relationship("ParserSource", back_populates="products")
    fingerprints = relationship("ParserProductFingerprint", back_populates="product")
    deltas = relationship("ParserProductDelta", back_populates="product")

    __table_args__ = (
        UniqueConstraint("source_id", "handle", name="uq_source_handle"),
        Index("idx_parser_product_source_id", "source_id"),
        Index("idx_parser_product_handle", "handle"),
        Index("idx_parser_product_vendor", "vendor"),
        Index("idx_parser_product_status", "status"),
        Index("idx_parser_product_deleted_at", "deleted_at"),
    )


class ParserProductFingerprint(Base):
    """SHA256 fingerprint for delta detection."""
    __tablename__ = "parser_product_fingerprint"

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("parser_source.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("parser_product.id"), nullable=False)
    
    fingerprint = Column(String(64), nullable=False)  # SHA256 hex
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    source = relationship("ParserSource", back_populates="fingerprints")
    product = relationship("ParserProduct", back_populates="fingerprints")

    __table_args__ = (
        UniqueConstraint("product_id", name="uq_product_fingerprint"),
        Index("idx_parser_product_fingerprint_source_id", "source_id"),
        Index("idx_parser_product_fingerprint_product_id", "product_id"),
    )


class ParserProductDelta(Base):
    """Delta changes detected in product during sync."""
    __tablename__ = "parser_product_delta"

    id = Column(Integer, primary_key=True)
    job_id = Column(String(36), ForeignKey("parser_job.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("parser_product.id"), nullable=False)
    
    delta_type = Column(SQLEnum(DeltaType, values_callable=_enum_values), nullable=False)
    
    old_price = Column(Float, nullable=True)
    new_price = Column(Float, nullable=True)
    
    old_status = Column(SQLEnum(ProductStatus, values_callable=_enum_values), nullable=True)
    new_status = Column(SQLEnum(ProductStatus, values_callable=_enum_values), nullable=True)
    
    old_image_count = Column(Integer, nullable=True)
    new_image_count = Column(Integer, nullable=True)
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    job = relationship("ParserJob", back_populates="deltas")
    product = relationship("ParserProduct", back_populates="deltas")

    __table_args__ = (
        Index("idx_parser_product_delta_job_id", "job_id"),
        Index("idx_parser_product_delta_product_id", "product_id"),
        Index("idx_parser_product_delta_type", "delta_type"),
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
