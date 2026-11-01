from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AffinityType


class CustomerWorkerAffinity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A customer's private preference or block list entry for a worker."""

    __tablename__ = "customer_worker_affinities"
    __table_args__ = (
        UniqueConstraint("customer_id", "worker_id", name="uq_customer_worker_affinity"),
        Index("ix_affinity_worker_type", "worker_id", "affinity_type"),
    )

    customer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    worker_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    affinity_type: Mapped[str] = mapped_column(
        String(20), default=AffinityType.PREFERRED, nullable=False
    )
