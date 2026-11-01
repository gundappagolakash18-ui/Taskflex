"""Task execution proofs (PoE photos) and incidental expense ledger."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ExpenseCategory, ExpenseStatus


class TaskExecutionProof(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A photo/document proof uploaded by the worker as evidence of execution."""

    __tablename__ = "task_execution_proofs"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    file_key: Mapped[str] = mapped_column(String(255), nullable=False)  # storage key, not a public URL
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    location_source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # EXIF

    task: Mapped["Task"] = relationship(back_populates="execution_proofs")


class TaskExpense(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An on-the-spot incidental expense the worker paid and needs reimbursed."""

    __tablename__ = "task_expenses"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(20), default=ExpenseCategory.OTHER, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_url: Mapped[str | None] = mapped_column(String(255), nullable=True)  # storage key, never public
    receipt_mime_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ExpenseStatus.PENDING_APPROVAL, nullable=False, index=True)
    decided_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    task: Mapped["Task"] = relationship(back_populates="expenses")
