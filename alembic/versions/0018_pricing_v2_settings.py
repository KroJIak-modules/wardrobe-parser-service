"""Add pricing v2 fields for new TZ formula

Revision ID: 0018_pricing_v2_settings
Revises: 0017_source_buyout_surcharge
Create Date: 2026-04-05 17:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_pricing_v2_settings"
down_revision = "0017_source_buyout_surcharge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_pricing_settings",
        sa.Column("bybit_usdt_to_rub", sa.Float(), nullable=False, server_default="95.0"),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("bybit_extra_rub", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("eur_to_usd_rate", sa.Float(), nullable=False, server_default="1.18"),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("gbp_to_usd_rate", sa.Float(), nullable=False, server_default="1.4"),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("payment_fee_rate", sa.Float(), nullable=False, server_default="0.02"),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("customs_processing_rate", sa.Float(), nullable=False, server_default="0.08"),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("customs_fixed_rub", sa.Float(), nullable=False, server_default="540.0"),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("shipping_alt_threshold_eur", sa.Float(), nullable=False, server_default="300.0"),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("tax_rate", sa.Float(), nullable=False, server_default="0.06"),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("insurance_rules", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("service_fee_rules", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "parser_pricing_settings",
        sa.Column("shipping_rules", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )

    op.get_bind().exec_driver_sql(
        """
        UPDATE parser_pricing_settings
        SET bybit_usdt_to_rub = CASE WHEN usd_to_rub > 0 THEN usd_to_rub ELSE 95.0 END,
            bybit_extra_rub = 1.0,
            eur_to_usd_rate = 1.18,
            gbp_to_usd_rate = 1.4,
            payment_fee_rate = 0.02,
            customs_processing_rate = 0.08,
            customs_fixed_rub = 540.0,
            shipping_alt_threshold_eur = 300.0,
            tax_rate = 0.06,
            insurance_rules = '[{"min_eur":0.0,"max_eur":300.0,"mode":"percent","value":0.01},{"min_eur":300.0,"max_eur":520.0,"mode":"fixed_rub","value":1000.0},{"min_eur":520.0,"max_eur":null,"mode":"fixed_rub","value":1300.0}]'::json,
            service_fee_rules = '[{"min_rub":0.0,"max_rub":7000.0,"mode":"percent","value":0.25},{"min_rub":7000.0,"max_rub":10000.0,"mode":"fixed_rub","value":2500.0},{"min_rub":10000.0,"max_rub":17000.0,"mode":"fixed_rub","value":3000.0},{"min_rub":17000.0,"max_rub":20000.0,"mode":"fixed_rub","value":3500.0},{"min_rub":20000.0,"max_rub":30000.0,"mode":"percent","value":0.2},{"min_rub":30000.0,"max_rub":40000.0,"mode":"fixed_rub","value":6000.0},{"min_rub":40000.0,"max_rub":null,"mode":"percent","value":0.15}]'::json,
            shipping_rules = '{"US":{"normal":[{"kg":0.5,"rub":1400.0},{"kg":1.0,"rub":1650.0},{"kg":1.5,"rub":2250.0},{"kg":2.0,"rub":2900.0},{"kg":2.5,"rub":3500.0},{"kg":3.0,"rub":4100.0}],"alt":[{"kg":0.5,"rub":1700.0},{"kg":1.0,"rub":3350.0},{"kg":1.5,"rub":4100.0},{"kg":2.0,"rub":4950.0},{"kg":2.5,"rub":5650.0},{"kg":3.0,"rub":6500.0}]},"EU":{"normal":[{"kg":0.5,"rub":1100.0},{"kg":1.0,"rub":1500.0},{"kg":1.5,"rub":1900.0},{"kg":2.0,"rub":2300.0},{"kg":2.5,"rub":2700.0},{"kg":3.0,"rub":3150.0}],"alt":[{"kg":0.5,"rub":2300.0},{"kg":1.0,"rub":2750.0},{"kg":1.5,"rub":3750.0},{"kg":2.0,"rub":4800.0},{"kg":2.5,"rub":5800.0},{"kg":3.0,"rub":6800.0}]},"UK":{"normal":[{"kg":0.5,"rub":3400.0},{"kg":1.0,"rub":3900.0},{"kg":1.5,"rub":4400.0},{"kg":2.0,"rub":4900.0},{"kg":2.5,"rub":5450.0},{"kg":3.0,"rub":5950.0}],"alt":[]}}'::json
        """
    )


def downgrade() -> None:
    op.drop_column("parser_pricing_settings", "shipping_rules")
    op.drop_column("parser_pricing_settings", "service_fee_rules")
    op.drop_column("parser_pricing_settings", "insurance_rules")
    op.drop_column("parser_pricing_settings", "tax_rate")
    op.drop_column("parser_pricing_settings", "shipping_alt_threshold_eur")
    op.drop_column("parser_pricing_settings", "customs_fixed_rub")
    op.drop_column("parser_pricing_settings", "customs_processing_rate")
    op.drop_column("parser_pricing_settings", "payment_fee_rate")
    op.drop_column("parser_pricing_settings", "gbp_to_usd_rate")
    op.drop_column("parser_pricing_settings", "eur_to_usd_rate")
    op.drop_column("parser_pricing_settings", "bybit_extra_rub")
    op.drop_column("parser_pricing_settings", "bybit_usdt_to_rub")
