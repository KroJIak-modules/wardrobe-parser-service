"""Add auto-hide and auto-added product visibility flags

Revision ID: 0034_auto_hide_auto_products
Revises: 0033_source_sync_enabled
Create Date: 2026-04-21 05:40:00.000000
"""

from alembic import op


revision = "0034_auto_hide_auto_products"
down_revision = "0033_source_sync_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE parser_source "
        "ADD COLUMN IF NOT EXISTS hide_auto_added_products BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_parser_source_hide_auto_added_products "
        "ON parser_source (hide_auto_added_products)"
    )
    op.execute(
        "ALTER TABLE parser_product "
        "ADD COLUMN IF NOT EXISTS is_auto_added BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "ALTER TABLE parser_product "
        "ADD COLUMN IF NOT EXISTS auto_hide_force_visible BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE parser_product DROP COLUMN IF EXISTS auto_hide_force_visible")
    op.execute("ALTER TABLE parser_product DROP COLUMN IF EXISTS is_auto_added")
    op.execute("DROP INDEX IF EXISTS idx_parser_source_hide_auto_added_products")
    op.execute("ALTER TABLE parser_source DROP COLUMN IF EXISTS hide_auto_added_products")
