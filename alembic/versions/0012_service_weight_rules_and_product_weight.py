"""Add product weight fields and keyword-based weight rules

Revision ID: 0012_service_weight_rules
Revises: 0011_service_product_variants
Create Date: 2026-04-03 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0012_service_weight_rules"
down_revision = "0011_service_product_variants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("parser_product", sa.Column("weight_grams", sa.Float(), nullable=True))
    op.add_column("parser_product", sa.Column("weight_source", sa.String(length=32), nullable=True))
    op.add_column("parser_product", sa.Column("weight_match_keyword", sa.String(length=255), nullable=True))
    op.add_column("parser_product", sa.Column("weight_value", sa.Float(), nullable=True))
    op.add_column("parser_product", sa.Column("weight_unit", sa.String(length=16), nullable=True))
    op.create_index("idx_parser_product_weight_grams", "parser_product", ["weight_grams"])
    op.create_index("idx_parser_product_weight_source", "parser_product", ["weight_source"])

    op.create_table(
        "parser_weight_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("weight_grams", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_parser_weight_rule_deleted_at", "parser_weight_rule", ["deleted_at"])
    op.create_index("idx_parser_weight_rule_weight_grams", "parser_weight_rule", ["weight_grams"])

    op.create_table(
        "parser_weight_keyword",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["rule_id"], ["parser_weight_rule.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "keyword", name="uq_parser_weight_rule_keyword"),
    )
    op.create_index("idx_parser_weight_keyword_rule_id", "parser_weight_keyword", ["rule_id"])
    op.create_index("idx_parser_weight_keyword_keyword", "parser_weight_keyword", ["keyword"])


def downgrade() -> None:
    op.drop_index("idx_parser_weight_keyword_keyword", table_name="parser_weight_keyword")
    op.drop_index("idx_parser_weight_keyword_rule_id", table_name="parser_weight_keyword")
    op.drop_table("parser_weight_keyword")

    op.drop_index("idx_parser_weight_rule_weight_grams", table_name="parser_weight_rule")
    op.drop_index("idx_parser_weight_rule_deleted_at", table_name="parser_weight_rule")
    op.drop_table("parser_weight_rule")

    op.drop_index("idx_parser_product_weight_source", table_name="parser_product")
    op.drop_index("idx_parser_product_weight_grams", table_name="parser_product")
    op.drop_column("parser_product", "weight_unit")
    op.drop_column("parser_product", "weight_value")
    op.drop_column("parser_product", "weight_match_keyword")
    op.drop_column("parser_product", "weight_source")
    op.drop_column("parser_product", "weight_grams")
