"""Add persisted Bybit bucket cache fields to pricing settings

Revision ID: 0019_pricing_bybit_bucket_cache
Revises: 0018_pricing_v2_settings
Create Date: 2026-04-05 17:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_pricing_bybit_bucket_cache"
down_revision = "0018_pricing_v2_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_pricing_settings",
        sa.Column("bybit_bucket_rates", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("bybit_last_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("bybit_last_error", sa.String(length=1024), nullable=True),
    )

    op.get_bind().exec_driver_sql(
        """
        UPDATE parser_pricing_settings
        SET bybit_bucket_rates = '[]'::json
        WHERE bybit_bucket_rates IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("parser_pricing_settings", "bybit_last_error")
    op.drop_column("parser_pricing_settings", "bybit_last_updated_at")
    op.drop_column("parser_pricing_settings", "bybit_bucket_rates")

