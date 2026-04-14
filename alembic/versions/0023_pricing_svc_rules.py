"""Add ranged SVC rules and backfill from existing service fee rules

Revision ID: 0023_pricing_svc_rules
Revises: 0022_pricing_svc_settings
Create Date: 2026-04-14 00:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0023_pricing_svc_rules"
down_revision = "0022_pricing_svc_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parser_pricing_settings",
        sa.Column("svc_rules", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.execute(
        sa.text(
            """
            UPDATE parser_pricing_settings
            SET svc_rules = COALESCE(
                (
                    SELECT json_agg(
                        json_build_object(
                            'min_rub', GREATEST(0, COALESCE((item->>'min_rub')::double precision, 0)),
                            'max_rub', GREATEST(
                                GREATEST(0, COALESCE((item->>'min_rub')::double precision, 0)) + 1,
                                COALESCE((item->>'max_rub')::double precision, 10000000)
                            ),
                            'mode', CASE
                                WHEN lower(COALESCE(item->>'mode', 'fixed_rub')) = 'percent' THEN 'percent'
                                ELSE 'fixed_rub'
                            END,
                            'value', GREATEST(0, COALESCE((item->>'value')::double precision, 0))
                        )
                        ORDER BY
                            GREATEST(0, COALESCE((item->>'min_rub')::double precision, 0)),
                            GREATEST(
                                GREATEST(0, COALESCE((item->>'min_rub')::double precision, 0)) + 1,
                                COALESCE((item->>'max_rub')::double precision, 10000000)
                            )
                    )
                    FROM json_array_elements(COALESCE(service_fee_rules, '[]'::json)) AS item
                ),
                '[]'::json
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_column("parser_pricing_settings", "svc_rules")
