from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import UserRole


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=UserRole.CUSTOMER)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verification_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_reset_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_reset_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    customer_profile: Mapped["CustomerProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )
    worker_profile: Mapped["WorkerProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )
    wallet: Mapped["Wallet | None"] = relationship(
        back_populates="user", uselist=False, lazy="joined", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_worker(self) -> bool:
        return self.role == UserRole.WORKER

    @property
    def is_customer(self) -> bool:
        return self.role == UserRole.CUSTOMER

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "avatar_url": self.avatar_url,
            "city": self.city,
            "role": self.role,
        }


class EmailOtp(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_otps"

    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="EMAIL_VERIFICATION")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)


class CustomerProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customer_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_latitude: Mapped[float | None] = mapped_column(nullable=True)
    default_longitude: Mapped[float | None] = mapped_column(nullable=True)
    total_tasks_posted: Mapped[int] = mapped_column(default=0, nullable=False)
    total_spent: Mapped[float] = mapped_column(default=0.0, nullable=False)

    user: Mapped[User] = relationship(back_populates="customer_profile")
    saved_locations: Mapped[list["SavedLocation"]] = relationship(
        primaryjoin="foreign(SavedLocation.user_id) == CustomerProfile.user_id",
        cascade="all, delete-orphan",
        back_populates="customer",
    )
