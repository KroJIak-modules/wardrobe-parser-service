"""Add category enable toggle flag

Revision ID: 0026_category_is_enabled
Revises: 0025_pricing_final_rounding_mode
Create Date: 2026-04-14 16:35:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0026_category_is_enabled"
down_revision = "0025_pricing_final_rounding_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_category",
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("idx_parser_category_is_enabled", "parser_category", ["is_enabled"])


def downgrade() -> None:
    op.drop_index("idx_parser_category_is_enabled", table_name="parser_category")
    op.drop_column("parser_category", "is_enabled")
