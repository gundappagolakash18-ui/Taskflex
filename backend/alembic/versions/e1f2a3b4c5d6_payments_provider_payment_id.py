"""Add provider_payment_id column to payments table.

Revision ID: e1f2a3b4c5d6
Revises: b7c1e4a92d10
"""

from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "b7c1e4a92d10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_payments_provider_payment_id"),
        "payments",
        ["provider_payment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_payments_provider_payment_id"), table_name="payments")
    op.drop_column("payments", "provider_payment_id")
