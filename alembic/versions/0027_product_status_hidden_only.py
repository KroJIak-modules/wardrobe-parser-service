"""Replace legacy product status discontinued with hidden

Revision ID: 0027_product_status_hidden_only
Revises: 0026_category_is_enabled
Create Date: 2026-04-16 12:20:00.000000

"""

from alembic import op


revision = "0027_product_status_hidden_only"
down_revision = "0026_category_is_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE productstatus RENAME TO productstatus_old")
    op.execute("CREATE TYPE productstatus AS ENUM ('available', 'out_of_stock', 'hidden')")

    op.execute(
        """
        ALTER TABLE parser_product
        ALTER COLUMN status DROP DEFAULT,
        ALTER COLUMN status TYPE productstatus
        USING (
            CASE
                WHEN status::text = 'discontinued' THEN 'hidden'
                ELSE status::text
            END
        )::productstatus,
        ALTER COLUMN status SET DEFAULT 'available'::productstatus
        """
    )

    op.execute(
        """
        ALTER TABLE parser_product_delta
        ALTER COLUMN old_status TYPE productstatus
        USING (
            CASE
                WHEN old_status IS NULL THEN NULL
                WHEN old_status::text = 'discontinued' THEN 'hidden'
                ELSE old_status::text
            END
        )::productstatus,
        ALTER COLUMN new_status TYPE productstatus
        USING (
            CASE
                WHEN new_status IS NULL THEN NULL
                WHEN new_status::text = 'discontinued' THEN 'hidden'
                ELSE new_status::text
            END
        )::productstatus
        """
    )

    op.execute("DROP TYPE productstatus_old")


def downgrade() -> None:
    op.execute("ALTER TYPE productstatus RENAME TO productstatus_new")
    op.execute("CREATE TYPE productstatus AS ENUM ('available', 'out_of_stock', 'discontinued')")

    op.execute(
        """
        ALTER TABLE parser_product
        ALTER COLUMN status DROP DEFAULT,
        ALTER COLUMN status TYPE productstatus
        USING (
            CASE
                WHEN status::text = 'hidden' THEN 'discontinued'
                ELSE status::text
            END
        )::productstatus,
        ALTER COLUMN status SET DEFAULT 'available'::productstatus
        """
    )

    op.execute(
        """
        ALTER TABLE parser_product_delta
        ALTER COLUMN old_status TYPE productstatus
        USING (
            CASE
                WHEN old_status IS NULL THEN NULL
                WHEN old_status::text = 'hidden' THEN 'discontinued'
                ELSE old_status::text
            END
        )::productstatus,
        ALTER COLUMN new_status TYPE productstatus
        USING (
            CASE
                WHEN new_status IS NULL THEN NULL
                WHEN new_status::text = 'hidden' THEN 'discontinued'
                ELSE new_status::text
            END
        )::productstatus
        """
    )

    op.execute("DROP TYPE productstatus_new")
