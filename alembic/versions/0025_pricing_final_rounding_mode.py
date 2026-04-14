"""Add final rounding mode to pricing settings

Revision ID: 0025_pricing_final_rounding_mode
Revises: 0024_drop_legacy_svc_mode_value
Create Date: 2026-04-14 03:35:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0025_pricing_final_rounding_mode"
down_revision = "0024_drop_legacy_svc_mode_value"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_pricing_settings",
        sa.Column("final_rounding_mode", sa.String(length=32), nullable=False, server_default="unit"),
    )


def downgrade() -> None:
    op.drop_column("parser_pricing_settings", "final_rounding_mode")
