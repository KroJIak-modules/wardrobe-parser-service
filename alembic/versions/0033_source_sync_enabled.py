"""Add sync_enabled flag for parser_source

Revision ID: 0033_source_sync_enabled
Revises: 0032_drop_legacy_parser_tables
Create Date: 2026-04-21 04:30:00.000000
"""

from alembic import op


revision = "0033_source_sync_enabled"
down_revision = "0032_drop_legacy_parser_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE parser_source ADD COLUMN IF NOT EXISTS sync_enabled BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("CREATE INDEX IF NOT EXISTS idx_parser_source_sync_enabled ON parser_source (sync_enabled)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_parser_source_sync_enabled")
    op.execute("ALTER TABLE parser_source DROP COLUMN IF EXISTS sync_enabled")
