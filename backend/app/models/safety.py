from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import RideCheckStatus, RideCheckType, SosStatus


class TaskSosAlert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A durable emergency trigger on a task. The GPS trail is copied into the
    row at trigger time so evidence survives Redis expiry and later pings."""

    __tablename__ = "task_sos_alerts"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raised_by_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raised_by_role: Mapped[str] = mapped_column(String(20), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=SosStatus.OPEN, nullable=False, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_history: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    resolved_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class RideCheckEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A safety anomaly detected from live GPS telemetry (RideCheck)."""

    __tablename__ = "ridecheck_events"
    __table_args__ = (
        Index("ix_ridecheck_task_status", "task_id", "status"),
        Index("ix_ridecheck_worker_created", "worker_id", "created_at"),
    )

    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(30), default=RideCheckType.ROUTE_DEVIATION, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=RideCheckStatus.OPEN, server_default=RideCheckStatus.OPEN, nullable=False
    )
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    deviation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    stationary_seconds: Mapped[int | None] = mapped_column(nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledgment_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_flagged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
