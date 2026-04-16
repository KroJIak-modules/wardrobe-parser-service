"""Add dedup-only-available toggle to pricing settings.

Revision ID: 0029_dedup_only_available
Revises: 0028_add_unavailable_status
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_dedup_only_available"
down_revision = "0028_add_unavailable_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_pricing_settings",
        sa.Column("dedup_only_available_products", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute("UPDATE parser_pricing_settings SET dedup_only_available_products = false WHERE dedup_only_available_products IS NULL")
    op.alter_column("parser_pricing_settings", "dedup_only_available_products", server_default=None)


def downgrade() -> None:
    op.drop_column("parser_pricing_settings", "dedup_only_available_products")

