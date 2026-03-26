"""Add parser job orchestration tables

Revision ID: 0006_service_parser_jobs
Revises: 0005_service_add_site_avg_time
Create Date: 2026-03-26 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_service_parser_jobs"
down_revision = "0005_service_add_site_avg_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parser_source",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("parser_type", sa.String(50), nullable=False, server_default="shopify"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("config", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("url"),
    )
    op.create_index("idx_parser_source_enabled", "parser_source", ["enabled"])
    op.create_index("idx_parser_source_deleted_at", "parser_source", ["deleted_at"])

    op.create_table(
        "parser_job",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("status", postgresql.ENUM("pending", "in_progress", "completed", "failed", "cancelled", name="jobstatus"), nullable=False, server_default="pending"),
        sa.Column("triggered_by", sa.String(50), nullable=False),
        sa.Column("total_products", sa.Integer(), nullable=True),
        sa.Column("new_products", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("updated_products", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("new_images", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("http_429_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("http_5xx_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_parser_job_status", "parser_job", ["status"])
    op.create_index("idx_parser_job_created_at", "parser_job", ["created_at"])
    op.create_index("idx_parser_job_triggered_by", "parser_job", ["triggered_by"])
    op.create_index("idx_parser_job_deleted_at", "parser_job", ["deleted_at"])

    op.create_table(
        "parser_job_source_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("status", postgresql.ENUM("pending", "in_progress", "success", "partial", "failed", name="sourcerunstatus"), nullable=False, server_default="pending"),
        sa.Column("products_discovered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("products_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("products_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("discovery_mode", sa.String(50), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["job_id"], ["parser_job.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["parser_source.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "source_id", name="uq_job_source"),
    )
    op.create_index("idx_parser_job_source_run_job_id", "parser_job_source_run", ["job_id"])
    op.create_index("idx_parser_job_source_run_source_id", "parser_job_source_run", ["source_id"])
    op.create_index("idx_parser_job_source_run_status", "parser_job_source_run", ["status"])

    op.create_table(
        "parser_product",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("handle", sa.String(1024), nullable=False),
        sa.Column("title", sa.String(2048), nullable=False),
        sa.Column("vendor", sa.String(255), nullable=True),
        sa.Column("product_type", sa.String(255), nullable=True),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("status", postgresql.ENUM("available", "out_of_stock", "discontinued", name="productstatus"), nullable=False, server_default="available"),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["parser_source.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url"),
        sa.UniqueConstraint("source_id", "handle", name="uq_source_handle"),
    )
    op.create_index("idx_parser_product_source_id", "parser_product", ["source_id"])
    op.create_index("idx_parser_product_handle", "parser_product", ["handle"])
    op.create_index("idx_parser_product_vendor", "parser_product", ["vendor"])
    op.create_index("idx_parser_product_status", "parser_product", ["status"])
    op.create_index("idx_parser_product_deleted_at", "parser_product", ["deleted_at"])

    op.create_table(
        "parser_product_fingerprint",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["parser_product.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["parser_source.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_product_fingerprint"),
    )
    op.create_index("idx_parser_product_fingerprint_source_id", "parser_product_fingerprint", ["source_id"])
    op.create_index("idx_parser_product_fingerprint_product_id", "parser_product_fingerprint", ["product_id"])

    op.create_table(
        "parser_product_delta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("delta_type", postgresql.ENUM("new", "updated", "unchanged", "deleted", name="deltatype"), nullable=False),
        sa.Column("old_price", sa.Float(), nullable=True),
        sa.Column("new_price", sa.Float(), nullable=True),
        sa.Column("old_status", postgresql.ENUM("available", "out_of_stock", "discontinued", name="productstatus"), nullable=True),
        sa.Column("new_status", postgresql.ENUM("available", "out_of_stock", "discontinued", name="productstatus"), nullable=True),
        sa.Column("old_image_count", sa.Integer(), nullable=True),
        sa.Column("new_image_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["job_id"], ["parser_job.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["parser_product.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_parser_product_delta_job_id", "parser_product_delta", ["job_id"])
    op.create_index("idx_parser_product_delta_product_id", "parser_product_delta", ["product_id"])
    op.create_index("idx_parser_product_delta_type", "parser_product_delta", ["delta_type"])

    op.create_table(
        "image_asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("storage_mode", sa.String(50), nullable=False, server_default="proxy"),
        sa.Column("stored_path", sa.String(2048), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_url"),
    )
    op.create_index("idx_image_asset_storage_mode", "image_asset", ["storage_mode"])
    op.create_index("idx_image_asset_deleted_at", "image_asset", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("idx_image_asset_deleted_at", "image_asset")
    op.drop_index("idx_image_asset_storage_mode", "image_asset")
    op.drop_table("image_asset")

    op.drop_index("idx_parser_product_delta_type", "parser_product_delta")
    op.drop_index("idx_parser_product_delta_product_id", "parser_product_delta")
    op.drop_index("idx_parser_product_delta_job_id", "parser_product_delta")
    op.drop_table("parser_product_delta")

    op.drop_index("idx_parser_product_fingerprint_product_id", "parser_product_fingerprint")
    op.drop_index("idx_parser_product_fingerprint_source_id", "parser_product_fingerprint")
    op.drop_table("parser_product_fingerprint")

    op.drop_index("idx_parser_product_deleted_at", "parser_product")
    op.drop_index("idx_parser_product_status", "parser_product")
    op.drop_index("idx_parser_product_vendor", "parser_product")
    op.drop_index("idx_parser_product_handle", "parser_product")
    op.drop_index("idx_parser_product_source_id", "parser_product")
    op.drop_table("parser_product")

    op.drop_index("idx_parser_job_source_run_status", "parser_job_source_run")
    op.drop_index("idx_parser_job_source_run_source_id", "parser_job_source_run")
    op.drop_index("idx_parser_job_source_run_job_id", "parser_job_source_run")
    op.drop_table("parser_job_source_run")

    op.drop_index("idx_parser_job_deleted_at", "parser_job")
    op.drop_index("idx_parser_job_triggered_by", "parser_job")
    op.drop_index("idx_parser_job_created_at", "parser_job")
    op.drop_index("idx_parser_job_status", "parser_job")
    op.drop_table("parser_job")

    op.drop_index("idx_parser_source_deleted_at", "parser_source")
    op.drop_index("idx_parser_source_enabled", "parser_source")
    op.drop_table("parser_source")
