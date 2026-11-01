"""Audit metadata for proof-of-execution photos and expense receipts.

Revision ID: f6a2b9d41e83
Revises: a3f9d12c7b64
"""

from alembic import op
import sqlalchemy as sa

revision = "f6a2b9d41e83"
down_revision = "a3f9d12c7b64"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_execution_proofs",
        sa.Column("location_source", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "task_expenses",
        sa.Column("receipt_mime_type", sa.String(length=60), nullable=True),
    )
    op.add_column(
        "task_expenses",
        sa.Column("decision_note", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task_expenses", "decision_note")
    op.drop_column("task_expenses", "receipt_mime_type")
    op.drop_column("task_execution_proofs", "location_source")
