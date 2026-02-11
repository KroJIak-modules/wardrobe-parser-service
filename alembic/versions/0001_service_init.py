"""init service tables

Revision ID: 0001_service_init
Revises: 
Create Date: 2026-02-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_service_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parser_sites",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("key", name="uq_parser_sites_key"),
    )
    op.create_index("ix_parser_sites_id", "parser_sites", ["id"], unique=False)
    op.create_index("ix_parser_sites_key", "parser_sites", ["key"], unique=True)

    op.create_table(
        "parser_products",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parser_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("product_url", sa.String(length=1024), nullable=False),
        sa.Column("image_url", sa.String(length=1024), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_sync", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("site_id", "external_id", name="uq_parser_products_site_external"),
    )
    op.create_index("ix_parser_products_id", "parser_products", ["id"], unique=False)
    op.create_index("ix_parser_products_site_id", "parser_products", ["site_id"], unique=False)
    op.create_index("ix_parser_products_external_id", "parser_products", ["external_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_parser_products_external_id", table_name="parser_products")
    op.drop_index("ix_parser_products_site_id", table_name="parser_products")
    op.drop_index("ix_parser_products_id", table_name="parser_products")
    op.drop_table("parser_products")
    op.drop_index("ix_parser_sites_key", table_name="parser_sites")
    op.drop_index("ix_parser_sites_id", table_name="parser_sites")
    op.drop_table("parser_sites")
