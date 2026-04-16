"""Add description to parser_product

Revision ID: 0031_product_description
Revises: 0030_supplier_alternatives
Create Date: 2026-04-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0031_product_description"
down_revision = "0030_supplier_alternatives"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("parser_product", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("parser_product", "description")

