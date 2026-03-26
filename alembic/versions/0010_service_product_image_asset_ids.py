"""Add image_asset_ids to parser_product

Revision ID: 0010_service_img_asset_ids
Revises: 0009_service_product_image_urls
Create Date: 2026-03-26 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0010_service_img_asset_ids"
down_revision = "0009_service_product_image_urls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_product",
        sa.Column("image_asset_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )


def downgrade() -> None:
    op.drop_column("parser_product", "image_asset_ids")
