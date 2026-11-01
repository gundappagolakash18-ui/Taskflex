from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import DocumentType, VerificationStatus, WorkerTier


class WorkerProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "worker_profiles"
    __table_args__ = (Index("ix_workers_location", "latitude", "longitude"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    area: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    experience_years: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    languages: Mapped[str] = mapped_column(String(255), default="English", nullable=False)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(20), default=VerificationStatus.PENDING, nullable=False, index=True
    )
    working_radius_km: Mapped[float] = mapped_column(Float, default=8.0, nullable=False)
    max_concurrent_tasks: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    completed_tasks_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancelled_tasks_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missed_offers: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    total_earnings: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rating_average: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rating_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Gamification + chaining state.
    tier: Mapped[str] = mapped_column(
        String(20), default=WorkerTier.SILVER, server_default=WorkerTier.SILVER, nullable=False
    )
    commission_rate: Mapped[float] = mapped_column(
        Float, default=0.10, server_default="0.1", nullable=False
    )
    queued_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    wrapping_up_soon: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    upi_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_online_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="worker_profile")
    skills: Mapped[list["WorkerSkill"]] = relationship(
        back_populates="worker", cascade="all, delete-orphan", lazy="selectin"
    )
    availability: Mapped[list["WorkerAvailability"]] = relationship(
        back_populates="worker", cascade="all, delete-orphan", lazy="selectin"
    )
    documents: Mapped[list["VerificationDocument"]] = relationship(
        back_populates="worker", cascade="all, delete-orphan"
    )
    queued_task: Mapped["Task | None"] = relationship(foreign_keys=[queued_task_id])

    def skills_slugs(self) -> list[str]:
        return [ws.skill.slug for ws in self.skills]


class Skill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    category: Mapped[str] = mapped_column(String(60), default="general", nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    workers: Mapped[list["WorkerSkill"]] = relationship(back_populates="skill", cascade="all, delete-orphan")


class WorkerSkill(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "worker_skills"
    __table_args__ = (UniqueConstraint("worker_profile_id", "skill_id", name="uq_worker_skill"),)

    worker_profile_id: Mapped[str] = mapped_column(
        ForeignKey("worker_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    experience_level: Mapped[str] = mapped_column(String(20), default="intermediate", nullable=False)

    worker: Mapped[WorkerProfile] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship(back_populates="workers")


class WorkerAvailability(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "worker_availability"
    __table_args__ = (UniqueConstraint("worker_profile_id", "day_of_week", name="uq_worker_day"),)

    worker_profile_id: Mapped[str] = mapped_column(
        ForeignKey("worker_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day_of_week: Mapped[int] = mapped_column(nullable=False)  # 0=Monday .. 6=Sunday
    start_time: Mapped[time] = mapped_column(default=time(8, 0), nullable=False)
    end_time: Mapped[time] = mapped_column(default=time(20, 0), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    worker: Mapped[WorkerProfile] = relationship(back_populates="availability")


class VerificationDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "verification_documents"

    worker_profile_id: Mapped[str] = mapped_column(
        ForeignKey("worker_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(String(30), default=DocumentType.ID_CARD, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=VerificationStatus.PENDING, nullable=False, index=True)
    reviewed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    worker: Mapped[WorkerProfile] = relationship(back_populates="documents")


class WorkerQuest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A daily task-count target with a cash bonus, seeded by operations."""

    __tablename__ = "worker_quests"
    __table_args__ = (Index("ix_worker_quests_active_date", "is_active", "valid_date"),)

    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_tasks_count: Mapped[int] = mapped_column(Integer, nullable=False)
    bonus_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    valid_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    progress: Mapped[list["WorkerQuestProgress"]] = relationship(
        back_populates="quest", cascade="all, delete-orphan"
    )


class WorkerQuestProgress(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "worker_quest_progress"
    __table_args__ = (UniqueConstraint("worker_id", "quest_id", name="uq_worker_quest"),)

    worker_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    quest_id: Mapped[str] = mapped_column(
        ForeignKey("worker_quests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    completed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_claimed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    quest: Mapped[WorkerQuest] = relationship(back_populates="progress")
