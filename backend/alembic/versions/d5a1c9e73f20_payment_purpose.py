"""Payment purpose (task escrow, bid delta, tip).

Revision ID: d5a1c9e73f20
Revises: c8e4f1a72d63
"""

from alembic import op
import sqlalchemy as sa

revision = "d5a1c9e73f20"
down_revision = "c8e4f1a72d63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("purpose", sa.String(length=20), server_default="TASK", nullable=False),
    )
    op.create_index(op.f("ix_payments_purpose"), "payments", ["purpose"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_payments_purpose"), table_name="payments")
    op.drop_column("payments", "purpose")
