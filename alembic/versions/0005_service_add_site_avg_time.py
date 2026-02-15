"""add avg_parse_time_sec to parser_sites

Revision ID: 0005_service_add_site_avg_time
Revises: 0004_service_images_drop
Create Date: 2026-02-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_service_add_site_avg_time"
down_revision = "0004_service_images_drop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_sites",
        sa.Column("avg_parse_time_sec", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("parser_sites", "avg_parse_time_sec")
