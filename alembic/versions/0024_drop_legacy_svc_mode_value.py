"""Drop legacy single-value SVC fields

Revision ID: 0024_drop_legacy_svc_mode_value
Revises: 0023_pricing_svc_rules
Create Date: 2026-04-14 02:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0024_drop_legacy_svc_mode_value"
down_revision = "0023_pricing_svc_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("parser_pricing_settings", "svc_value")
    op.drop_column("parser_pricing_settings", "svc_mode")


def downgrade() -> None:
    op.add_column(
        "parser_pricing_settings",
        sa.Column("svc_mode", sa.String(length=16), nullable=False, server_default="fixed_rub"),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("svc_value", sa.Float(), nullable=False, server_default="0.0"),
    )
