from sqlalchemy import Boolean, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SavedLocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "saved_locations"
    __table_args__ = (UniqueConstraint("user_id", "label", name="uq_saved_location_label"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    customer: Mapped["CustomerProfile"] = relationship(
        primaryjoin="foreign(SavedLocation.user_id) == CustomerProfile.user_id",
        back_populates="saved_locations",
    )
