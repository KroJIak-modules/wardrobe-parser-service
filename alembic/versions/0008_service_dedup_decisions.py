"""Add dedup decisions table

Revision ID: 0008_service_dedup_decisions
Revises: 0007_service_categories_tree
Create Date: 2026-03-26 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "0008_service_dedup_decisions"
down_revision = "0007_service_categories_tree"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parser_dedup_decision",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pair_key", sa.String(length=64), nullable=False),
        sa.Column("left_product_id", sa.Integer(), nullable=False),
        sa.Column("right_product_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("merged_into_product_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["left_product_id"], ["parser_product.id"]),
        sa.ForeignKeyConstraint(["right_product_id"], ["parser_product.id"]),
        sa.ForeignKeyConstraint(["merged_into_product_id"], ["parser_product.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pair_key", name="uq_parser_dedup_pair_key"),
    )
    op.create_index("idx_parser_dedup_decision_action", "parser_dedup_decision", ["action"])
    op.create_index("idx_parser_dedup_decision_left", "parser_dedup_decision", ["left_product_id"])
    op.create_index("idx_parser_dedup_decision_right", "parser_dedup_decision", ["right_product_id"])


def downgrade() -> None:
    op.drop_index("idx_parser_dedup_decision_right", table_name="parser_dedup_decision")
    op.drop_index("idx_parser_dedup_decision_left", table_name="parser_dedup_decision")
    op.drop_index("idx_parser_dedup_decision_action", table_name="parser_dedup_decision")
    op.drop_table("parser_dedup_decision")
