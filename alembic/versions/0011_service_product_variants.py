"""Add variants to parser_product

Revision ID: 0011_service_product_variants
Revises: 0010_service_img_asset_ids
Create Date: 2026-03-28 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0011_service_product_variants"
down_revision = "0010_service_img_asset_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_product",
        sa.Column("variants", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )


def downgrade() -> None:
    op.drop_column("parser_product", "variants")
