"""Add source-level pricing settings

Revision ID: 0016_source_pricing_settings
Revises: 0015_pricing_currencies
Create Date: 2026-04-04 13:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0016_source_pricing_settings"
down_revision = "0015_pricing_currencies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_source",
        sa.Column("seller_delivery_rub", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "parser_source",
        sa.Column("promo_factor", sa.Float(), nullable=False, server_default="1"),
    )
    op.add_column(
        "parser_source",
        sa.Column("promo_only_no_discount", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("parser_source", "promo_only_no_discount")
    op.drop_column("parser_source", "promo_factor")
    op.drop_column("parser_source", "seller_delivery_rub")
