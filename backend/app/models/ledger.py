"""Platform treasury ledger — double-entry accounting for real money movement.

Every journal contains entries that sum to zero. Account balances are derived
from the entries, so the books can always be reconciled against the gateway.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class PlatformLedgerEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "platform_ledger_entries"
    __table_args__ = (
        Index("ix_platform_ledger_account_created", "account", "created_at"),
        Index("ix_platform_ledger_ref", "reference_type", "reference_id"),
    )

    account: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    entry_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    journal_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reference_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
