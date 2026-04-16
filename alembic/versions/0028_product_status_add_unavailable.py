"""Add unavailable value to productstatus enum.

Revision ID: 0028_add_unavailable_status
Revises: 0027_product_status_hidden_only
Create Date: 2026-04-16
"""

from alembic import op


revision = "0028_add_unavailable_status"
down_revision = "0027_product_status_hidden_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE productstatus ADD VALUE IF NOT EXISTS 'unavailable'")


def downgrade() -> None:
    # PostgreSQL does not support dropping enum values safely without rebuilding type.
    # Keep downgrade no-op to avoid destructive status remapping.
    pass
