from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import RatingDirection


class Rating(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("task_id", "direction", name="uq_rating_task_direction"),
        Index("ix_ratings_ratee", "ratee_id"),
    )

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    rater_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ratee_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    direction: Mapped[str] = mapped_column(String(30), default=RatingDirection.CUSTOMER_TO_WORKER, nullable=False)
    score: Mapped[int] = mapped_column(nullable=False)  # 1..5
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship(back_populates="ratings")


class Review(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reviews"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rating_score: Mapped[int] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_public: Mapped[bool] = mapped_column(default=True, nullable=False)

    author: Mapped["User"] = relationship(foreign_keys=[author_id])
    target: Mapped["User"] = relationship(foreign_keys=[target_user_id])
