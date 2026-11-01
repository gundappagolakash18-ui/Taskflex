from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AssignmentStatus, BidStatus, OfferStatus, TaskStatus, Urgency


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status_created", "status", "created_at"),
        Index("ix_tasks_location", "latitude", "longitude"),
        Index("ix_tasks_customer", "customer_id"),
    )

    customer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default=TaskStatus.DRAFT, nullable=False, index=True)
    urgency: Mapped[str] = mapped_column(String(10), default=Urgency.NORMAL, nullable=False)

    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    scheduled_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    time_window_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    estimated_duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    address_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    area_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    budget: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    special_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)

    parsed_by_ai: Mapped[bool] = mapped_column(default=False, nullable=False)
    ai_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    raw_request_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    assigned_worker_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    worker_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    customer_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    payment_status: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    commission_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    worker_payout_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    tip_amount: Mapped[float] = mapped_column(
        Numeric(10, 2), default=0, server_default="0", nullable=False
    )

    # Scheduling / reservations. A task confirmed more than 60 minutes ahead
    # opens a reservation board instead of live dispatch.
    is_scheduled: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    worker_confirmed_readiness: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )

    # Round-trip errands return to the pickup origin; the final handback is
    # gated by a separate OTP.
    is_round_trip: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)
    return_otp_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    return_otp_display: Mapped[str | None] = mapped_column(String(4), nullable=True)
    return_otp_attempts: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    return_otp_locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    return_otp_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Counter-offer auction window. Bids are only valid while the task is in
    # SEARCHING_WORKER.
    bids_close_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # OTP gates: hashed with HMAC-SHA256; the plaintext display copy is exposed
    # only to the task creator via the owner serializer.
    start_otp_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_otp_display: Mapped[str | None] = mapped_column(String(4), nullable=True)
    start_otp_attempts: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    start_otp_locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_otp_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completion_otp_display: Mapped[str | None] = mapped_column(String(4), nullable=True)
    completion_otp_attempts: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    completion_otp_locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Public live-tracking share link.
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    share_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    customer: Mapped["User"] = relationship(foreign_keys=[customer_id])
    assigned_worker: Mapped["User | None"] = relationship(foreign_keys=[assigned_worker_id])
    requirements: Mapped[list["TaskRequirement"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", lazy="selectin"
    )
    locations: Mapped[list["TaskLocation"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", lazy="selectin"
    )
    offers: Mapped[list["TaskOffer"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    bids: Mapped[list["TaskBid"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    assignments: Mapped[list["TaskAssignment"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    status_history: Mapped[list["TaskStatusHistory"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskStatusHistory.created_at"
    )
    ratings: Mapped[list["Rating"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    dispute: Mapped["Dispute | None"] = relationship(back_populates="task", uselist=False)
    execution_proofs: Mapped[list["TaskExecutionProof"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    expenses: Mapped[list["TaskExpense"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TaskLocation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "task_locations"
    __table_args__ = (Index("ix_task_locations_geo", "latitude", "longitude"),)

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(40), default="primary", nullable=False)  # primary | pickup | dropoff
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)

    task: Mapped[Task] = relationship(back_populates="locations")


class TaskRequirement(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "task_requirements"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_id: Mapped[str | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"), nullable=True)
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_required: Mapped[bool] = mapped_column(default=True, nullable=False)

    task: Mapped[Task] = relationship(back_populates="requirements")


class TaskOffer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "task_offers"
    __table_args__ = (Index("ix_offers_worker_status", "worker_id", "status"),)

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=OfferStatus.PENDING, nullable=False, index=True)
    match_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    match_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates="offers")
    worker: Mapped["User"] = relationship()


class TaskBid(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A worker's counter-offer for a task that is still searching for a runner."""

    __tablename__ = "task_bids"
    __table_args__ = (
        Index("ix_task_bids_task_status", "task_id", "status"),
        Index("ix_task_bids_worker", "worker_id"),
    )

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    worker_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    proposed_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(String(140), nullable=True)
    estimated_arrival_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=BidStatus.PENDING, nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates="bids")
    worker: Mapped["User"] = relationship()


class TaskAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "task_assignments"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default=AssignmentStatus.ACTIVE, nullable=False, index=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    earnings_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    commission_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)

    task: Mapped[Task] = relationship(back_populates="assignments")
    worker: Mapped["User"] = relationship()


class TaskStatusHistory(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "task_status_history"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_by_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task: Mapped[Task] = relationship(back_populates="status_history")
