"""Platform treasury ledger entries.

Revision ID: b7c1e4a92d10
Revises: d5a1c9e73f20
"""

from alembic import op
import sqlalchemy as sa

revision = "b7c1e4a92d10"
down_revision = "d5a1c9e73f20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("entry_type", sa.String(length=40), nullable=False),
        sa.Column("journal_id", sa.String(length=36), nullable=False),
        sa.Column("reference_type", sa.String(length=30), nullable=True),
        sa.Column("reference_id", sa.String(length=64), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_platform_ledger_entries_account"), "platform_ledger_entries", ["account"])
    op.create_index(op.f("ix_platform_ledger_entries_created_at"), "platform_ledger_entries", ["created_at"])
    op.create_index(op.f("ix_platform_ledger_entries_entry_type"), "platform_ledger_entries", ["entry_type"])
    op.create_index(op.f("ix_platform_ledger_entries_journal_id"), "platform_ledger_entries", ["journal_id"])
    op.create_index(
        "ix_platform_ledger_account_created", "platform_ledger_entries", ["account", "created_at"]
    )
    op.create_index(
        "ix_platform_ledger_ref", "platform_ledger_entries", ["reference_type", "reference_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_platform_ledger_ref", table_name="platform_ledger_entries")
    op.drop_index("ix_platform_ledger_account_created", table_name="platform_ledger_entries")
    op.drop_index(op.f("ix_platform_ledger_entries_journal_id"), table_name="platform_ledger_entries")
    op.drop_index(op.f("ix_platform_ledger_entries_entry_type"), table_name="platform_ledger_entries")
    op.drop_index(op.f("ix_platform_ledger_entries_created_at"), table_name="platform_ledger_entries")
    op.drop_index(op.f("ix_platform_ledger_entries_account"), table_name="platform_ledger_entries")
    op.drop_table("platform_ledger_entries")
