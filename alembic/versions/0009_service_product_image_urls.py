"""Add image_urls to parser_product

Revision ID: 0009_service_product_image_urls
Revises: 0008_service_dedup_decisions
Create Date: 2026-03-26 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0009_service_product_image_urls"
down_revision = "0008_service_dedup_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_product",
        sa.Column("image_urls", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )


def downgrade() -> None:
    op.drop_column("parser_product", "image_urls")
