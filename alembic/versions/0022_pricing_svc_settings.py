"""Add configurable SVC mode/value to pricing settings

Revision ID: 0022_pricing_svc_settings
Revises: 0021_supplier_category
Create Date: 2026-04-14 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0022_pricing_svc_settings"
down_revision = "0021_supplier_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_pricing_settings",
        sa.Column("svc_mode", sa.String(length=16), nullable=False, server_default="fixed_rub"),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("svc_value", sa.Float(), nullable=False, server_default="0.0"),
    )


def downgrade() -> None:
    op.drop_column("parser_pricing_settings", "svc_value")
    op.drop_column("parser_pricing_settings", "svc_mode")
