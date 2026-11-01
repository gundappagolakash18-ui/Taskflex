from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import PaymentStatus, PayoutStatus, TransactionType


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payments"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="mock")
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(20), default="TASK", server_default="TASK", nullable=False, index=True
    )  # TASK | BID_DELTA | TIP
    commission_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    worker_payout_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=PaymentStatus.INITIATED, nullable=False, index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped["Task"] = relationship()


class Wallet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wallets"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    balance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    total_earned: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_spent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    user: Mapped["User"] = relationship(back_populates="wallet")
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="wallet", cascade="all, delete-orphan"
    )


class Transaction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_transactions_user_created", "user_id", "created_at"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), default=TransactionType.CREDIT, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    balance_after: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(30), nullable=True)  # task | payment | dispute
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    wallet: Mapped[Wallet] = relationship(back_populates="transactions")


class PayoutRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An instant UPI cashout from the worker's wallet."""

    __tablename__ = "payout_requests"
    __table_args__ = (Index("ix_payout_requests_worker_created", "worker_id", "created_at"),)

    worker_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    upi_id: Mapped[str] = mapped_column(String(120), nullable=False)
    reference_utr: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=PayoutStatus.PROCESSING, server_default=PayoutStatus.PROCESSING, nullable=False, index=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
