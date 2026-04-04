"""Add pricing currencies for threshold and supplier base rates

Revision ID: 0015_pricing_currencies
Revises: 0014_supplier_shipping_rates
Create Date: 2026-04-04 14:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0015_pricing_currencies"
down_revision = "0014_supplier_shipping_rates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_pricing_settings",
        sa.Column("customs_threshold_currency", sa.String(length=3), nullable=False, server_default="EUR"),
    )
    op.add_column(
        "parser_supplier",
        sa.Column("rate_currency", sa.String(length=3), nullable=False, server_default="RUB"),
    )


def downgrade() -> None:
    op.drop_column("parser_supplier", "rate_currency")
    op.drop_column("parser_pricing_settings", "customs_threshold_currency")
