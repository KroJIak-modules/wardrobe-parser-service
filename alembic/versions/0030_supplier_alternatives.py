"""Add supplier alternative hierarchy fields.

Revision ID: 0030_supplier_alternatives
Revises: 0029_dedup_only_available
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa


revision = "0030_supplier_alternatives"
down_revision = "0029_dedup_only_available"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("parser_supplier", sa.Column("parent_supplier_id", sa.Integer(), nullable=True))
    op.add_column("parser_supplier", sa.Column("alt_position", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.create_foreign_key(
        "fk_parser_supplier_parent_supplier_id",
        "parser_supplier",
        "parser_supplier",
        ["parent_supplier_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("idx_parser_supplier_parent_supplier_id", "parser_supplier", ["parent_supplier_id"])
    op.create_index("idx_parser_supplier_alt_position", "parser_supplier", ["alt_position"])
    op.execute("UPDATE parser_supplier SET alt_position = 0 WHERE alt_position IS NULL")
    op.alter_column("parser_supplier", "alt_position", server_default=None)


def downgrade() -> None:
    op.drop_index("idx_parser_supplier_alt_position", table_name="parser_supplier")
    op.drop_index("idx_parser_supplier_parent_supplier_id", table_name="parser_supplier")
    op.drop_constraint("fk_parser_supplier_parent_supplier_id", "parser_supplier", type_="foreignkey")
    op.drop_column("parser_supplier", "alt_position")
    op.drop_column("parser_supplier", "parent_supplier_id")

