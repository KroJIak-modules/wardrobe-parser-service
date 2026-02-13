"""add size_data to parser_products

Revision ID: 0003_service_add_size_data
Revises: 0002_service_add_size_info
Create Date: 2026-02-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_service_add_size_data"
down_revision = "0002_service_add_size_info"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("parser_products", sa.Column("size_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("parser_products", "size_data")
