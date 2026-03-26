"""Add parser category tree and keyword tables

Revision ID: 0007_service_categories_tree
Revises: 0006_service_parser_jobs
Create Date: 2026-03-26 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "0007_service_categories_tree"
down_revision = "0006_service_parser_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parser_category",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("is_fallback", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], ["parser_category.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_parser_category_slug"),
    )
    op.create_index("idx_parser_category_parent_id", "parser_category", ["parent_id"])
    op.create_index("idx_parser_category_deleted_at", "parser_category", ["deleted_at"])
    op.create_index("idx_parser_category_is_fallback", "parser_category", ["is_fallback"])

    op.create_table(
        "parser_category_keyword",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["category_id"], ["parser_category.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_id", "keyword", name="uq_parser_category_keyword"),
    )
    op.create_index("idx_parser_category_keyword_category", "parser_category_keyword", ["category_id"])
    op.create_index("idx_parser_category_keyword_keyword", "parser_category_keyword", ["keyword"])

    op.execute(
        """
        INSERT INTO parser_category (name, slug, parent_id, is_fallback)
        VALUES ('Прочее', 'prochee', NULL, true)
        """
    )


def downgrade() -> None:
    op.drop_index("idx_parser_category_keyword_keyword", table_name="parser_category_keyword")
    op.drop_index("idx_parser_category_keyword_category", table_name="parser_category_keyword")
    op.drop_table("parser_category_keyword")

    op.drop_index("idx_parser_category_is_fallback", table_name="parser_category")
    op.drop_index("idx_parser_category_deleted_at", table_name="parser_category")
    op.drop_index("idx_parser_category_parent_id", table_name="parser_category")
    op.drop_table("parser_category")
