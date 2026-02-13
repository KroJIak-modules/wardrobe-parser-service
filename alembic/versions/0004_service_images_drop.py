"""add image_urls and drop raw_data

Revision ID: 0004_service_images_drop
Revises: 0003_service_add_size_data
Create Date: 2026-02-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_service_images_drop"
down_revision = "0003_service_add_size_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("parser_products", sa.Column("image_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.drop_column("parser_products", "raw_data")


def downgrade() -> None:
    op.add_column("parser_products", sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.drop_column("parser_products", "image_urls")
