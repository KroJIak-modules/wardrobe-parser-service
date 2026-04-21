"""Drop legacy parser_sites/parser_products tables

Revision ID: 0032_drop_legacy_parser_tables
Revises: 0031_product_description
Create Date: 2026-04-21 00:00:00.000000
"""

from alembic import op


revision = "0032_drop_legacy_parser_tables"
down_revision = "0031_product_description"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy tables from pre-refactor service parser storage.
    op.execute("DROP TABLE IF EXISTS parser_products CASCADE")
    op.execute("DROP TABLE IF EXISTS parser_sites CASCADE")


def downgrade() -> None:
    # Irreversible cleanup of deprecated schema.
    pass

