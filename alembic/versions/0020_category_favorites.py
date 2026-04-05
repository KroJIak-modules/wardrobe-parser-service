"""Add favorite category flag and manual favorite products table

Revision ID: 0020_category_favorites
Revises: 0019_pricing_bybit_bucket_cache
Create Date: 2026-04-05 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "0020_category_favorites"
down_revision = "0019_pricing_bybit_bucket_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_category",
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("idx_parser_category_is_favorite", "parser_category", ["is_favorite"])

    op.create_table(
        "parser_favorite_product",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["product_id"], ["parser_product.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_parser_favorite_product_product_id"),
    )
    op.create_index("idx_parser_favorite_product_product_id", "parser_favorite_product", ["product_id"])


def downgrade() -> None:
    op.drop_index("idx_parser_favorite_product_product_id", table_name="parser_favorite_product")
    op.drop_table("parser_favorite_product")

    op.drop_index("idx_parser_category_is_favorite", table_name="parser_category")
    op.drop_column("parser_category", "is_favorite")
