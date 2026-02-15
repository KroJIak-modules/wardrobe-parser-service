from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, String, Text, UniqueConstraint, func

from app.core.database import Base


class Site(Base):
    __tablename__ = "parser_sites"
    __table_args__ = (UniqueConstraint("key", name="uq_parser_sites_key"),)

    id = Column(BigInteger, primary_key=True, index=True)
    key = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    base_url = Column(String(512), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="true")
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime(timezone=True), nullable=True)
    avg_parse_time_sec = Column(Float, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, nullable=False, server_default="false")
    deleted_at = Column(DateTime(timezone=True), nullable=True)
