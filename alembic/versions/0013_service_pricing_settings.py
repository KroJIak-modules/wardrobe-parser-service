"""Add pricing settings table for final customer price formula

Revision ID: 0013_service_pricing_settings
Revises: 0012_service_weight_rules
Create Date: 2026-04-04 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0013_service_pricing_settings"
down_revision = "0012_service_weight_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parser_pricing_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("markup_multiplier", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("weight_tolerance", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("promo_factor", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("customs_threshold_eur", sa.Float(), nullable=False, server_default="200.0"),
        sa.Column("customs_duty_rate", sa.Float(), nullable=False, server_default="0.15"),
        sa.Column("seller_delivery_rub", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("supplier_shipping_per_500g_rub", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("usd_to_rub", sa.Float(), nullable=False, server_default="95.0"),
        sa.Column("eur_to_rub", sa.Float(), nullable=False, server_default="105.0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_parser_pricing_settings_updated_at",
        "parser_pricing_settings",
        ["updated_at"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO parser_pricing_settings (
                id, markup_multiplier, weight_tolerance, promo_factor,
                customs_threshold_eur, customs_duty_rate, seller_delivery_rub,
                supplier_shipping_per_500g_rub, usd_to_rub, eur_to_rub
            ) VALUES (
                1, 1.0, 1.0, 1.0,
                200.0, 0.15, 0.0,
                0.0, 95.0, 105.0
            )
            ON CONFLICT (id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("idx_parser_pricing_settings_updated_at", table_name="parser_pricing_settings")
    op.drop_table("parser_pricing_settings")

