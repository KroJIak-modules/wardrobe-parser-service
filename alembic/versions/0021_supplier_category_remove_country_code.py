"""Replace supplier country code fields with category

Revision ID: 0021_supplier_category
Revises: 0020_category_favorites
Create Date: 2026-04-13 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0021_supplier_category"
down_revision = "0020_category_favorites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_supplier",
        sa.Column("category", sa.String(length=16), nullable=False, server_default="main"),
    )
    op.create_index("idx_parser_supplier_category", "parser_supplier", ["category"])

    op.execute(
        sa.text(
            """
            UPDATE parser_supplier
            SET category = 'alt'
            WHERE LOWER(COALESCE(key, '')) LIKE '%-alt'
               OR LOWER(COALESCE(name, '')) LIKE '% alt%'
            """
        )
    )

    op.execute(sa.text("DROP INDEX IF EXISTS idx_parser_supplier_country_code"))
    op.drop_column("parser_supplier", "country_code")
    op.drop_column("parser_supplier", "country_name")


def downgrade() -> None:
    op.add_column(
        "parser_supplier",
        sa.Column("country_name", sa.String(length=255), nullable=False, server_default="Unknown"),
    )
    op.add_column(
        "parser_supplier",
        sa.Column("country_code", sa.String(length=16), nullable=False, server_default="N/A"),
    )
    op.create_index("idx_parser_supplier_country_code", "parser_supplier", ["country_code"])

    op.execute(
        sa.text(
            """
            UPDATE parser_supplier
            SET country_code = CASE
                WHEN LOWER(COALESCE(name, '')) = 'us' OR LOWER(COALESCE(key, '')) LIKE 'us-%' THEN 'US'
                WHEN LOWER(COALESCE(name, '')) IN ('uk', 'gb') OR LOWER(COALESCE(key, '')) LIKE 'uk-%' THEN 'UK'
                ELSE 'EU'
            END,
            country_name = CASE
                WHEN LOWER(COALESCE(name, '')) = 'us' OR LOWER(COALESCE(key, '')) LIKE 'us-%' THEN 'United States'
                WHEN LOWER(COALESCE(name, '')) IN ('uk', 'gb') OR LOWER(COALESCE(key, '')) LIKE 'uk-%' THEN 'United Kingdom'
                ELSE 'Europe'
            END
            """
        )
    )

    op.drop_index("idx_parser_supplier_category", table_name="parser_supplier")
    op.drop_column("parser_supplier", "category")
