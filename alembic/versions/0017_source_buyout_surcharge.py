"""Add source-level buyout surcharge fields

Revision ID: 0017_source_buyout_surcharge
Revises: 0016_source_pricing_settings
Create Date: 2026-04-04 13:45:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0017_source_buyout_surcharge"
down_revision = "0016_source_pricing_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_source",
        sa.Column("buyout_surcharge_value", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "parser_source",
        sa.Column("buyout_surcharge_currency", sa.String(length=3), nullable=False, server_default="RUB"),
    )


def downgrade() -> None:
    op.drop_column("parser_source", "buyout_surcharge_currency")
    op.drop_column("parser_source", "buyout_surcharge_value")
