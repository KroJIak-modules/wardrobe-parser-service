"""Add supplier SSR table and source->supplier mapping

Revision ID: 0014_supplier_shipping_rates
Revises: 0013_service_pricing_settings
Create Date: 2026-04-04 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0014_supplier_shipping_rates"
down_revision = "0013_service_pricing_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parser_supplier",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("country_code", sa.String(length=16), nullable=False, server_default="N/A"),
        sa.Column("country_name", sa.String(length=255), nullable=False, server_default="Unknown"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("idx_parser_supplier_key", "parser_supplier", ["key"])
    op.create_index("idx_parser_supplier_country_code", "parser_supplier", ["country_code"])

    op.create_table(
        "parser_supplier_shipping_rate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("step_500g", sa.Integer(), nullable=False),
        sa.Column("rate_rub", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["supplier_id"], ["parser_supplier.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supplier_id", "step_500g", name="uq_parser_supplier_shipping_rate_supplier_step"),
    )
    op.create_index(
        "idx_parser_supplier_shipping_rate_supplier_id",
        "parser_supplier_shipping_rate",
        ["supplier_id"],
    )
    op.create_index(
        "idx_parser_supplier_shipping_rate_step_500g",
        "parser_supplier_shipping_rate",
        ["step_500g"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO parser_supplier (id, key, name, country_code, country_name)
            VALUES (1, 'default', 'Default Supplier', 'N/A', 'Default')
            ON CONFLICT (id) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            SELECT setval(
                pg_get_serial_sequence('parser_supplier', 'id'),
                COALESCE((SELECT MAX(id) FROM parser_supplier), 1),
                true
            )
            """
        )
    )

    op.add_column(
        "parser_source",
        sa.Column(
            "supplier_id",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_index("idx_parser_source_supplier_id", "parser_source", ["supplier_id"])
    op.create_foreign_key(
        "fk_parser_source_supplier_id",
        "parser_source",
        "parser_supplier",
        ["supplier_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.execute(
        sa.text(
            """
            WITH base AS (
                SELECT COALESCE(
                    (SELECT supplier_shipping_per_500g_rub
                     FROM parser_pricing_settings
                     ORDER BY id ASC
                     LIMIT 1),
                    0
                )::double precision AS per_500g
            )
            INSERT INTO parser_supplier_shipping_rate (supplier_id, step_500g, rate_rub)
            SELECT 1, gs, gs * base.per_500g
            FROM generate_series(1, 120) AS gs
            CROSS JOIN base
            ON CONFLICT (supplier_id, step_500g) DO NOTHING
            """
        )
    )

    op.drop_column("parser_pricing_settings", "supplier_shipping_per_500g_rub")


def downgrade() -> None:
    op.add_column(
        "parser_pricing_settings",
        sa.Column("supplier_shipping_per_500g_rub", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.execute(
        sa.text(
            """
            UPDATE parser_pricing_settings ps
            SET supplier_shipping_per_500g_rub = COALESCE(
                (
                    SELECT rate_rub
                    FROM parser_supplier_shipping_rate r
                    WHERE r.supplier_id = 1 AND r.step_500g = 1
                    LIMIT 1
                ),
                0
            )
            """
        )
    )

    op.drop_constraint("fk_parser_source_supplier_id", "parser_source", type_="foreignkey")
    op.drop_index("idx_parser_source_supplier_id", table_name="parser_source")
    op.drop_column("parser_source", "supplier_id")

    op.drop_index(
        "idx_parser_supplier_shipping_rate_step_500g",
        table_name="parser_supplier_shipping_rate",
    )
    op.drop_index(
        "idx_parser_supplier_shipping_rate_supplier_id",
        table_name="parser_supplier_shipping_rate",
    )
    op.drop_table("parser_supplier_shipping_rate")

    op.drop_index("idx_parser_supplier_country_code", table_name="parser_supplier")
    op.drop_index("idx_parser_supplier_key", table_name="parser_supplier")
    op.drop_table("parser_supplier")
