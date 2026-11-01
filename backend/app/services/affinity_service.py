"""Customer ↔ worker affinity: preferred (repeat) and blacklisted (hard block).

The matching engine reads this table directly: blacklisted workers are
excluded before ranking, preferred workers get a +0.35 boost and sort first.
Ratings feed it automatically — a 5★ rating with the "prefer" toggle adds a
preference, a 1–2★ rating auto-blacklists the worker.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenException, NotFoundException
from app.core.logging import get_logger
from app.models import AffinityType, CustomerWorkerAffinity, User, UserRole, WorkerProfile

logger = get_logger("taskflex.affinity")


class AffinityService:
    def __init__(self, db: Session):
        self.db = db

    def _worker_profile(self, worker_id: str) -> WorkerProfile:
        worker = self.db.get(User, worker_id)
        if worker is None or worker.role != UserRole.WORKER.value or not worker.is_active:
            raise NotFoundException("Worker not found.")
        profile = self.db.scalar(
            select(WorkerProfile).where(WorkerProfile.user_id == worker_id)
        )
        if profile is None:
            raise NotFoundException("Worker profile not found.")
        return profile

    def _row(self, customer_id: str, worker_id: str) -> CustomerWorkerAffinity | None:
        return self.db.scalar(
            select(CustomerWorkerAffinity).where(
                CustomerWorkerAffinity.customer_id == customer_id,
                CustomerWorkerAffinity.worker_id == worker_id,
            )
        )

    def set_affinity(
        self, customer: User, worker_id: str, affinity: str
    ) -> CustomerWorkerAffinity:
        if customer.role != UserRole.CUSTOMER.value:
            raise ForbiddenException("Only customers can manage worker preferences.")
        if customer.id == worker_id:
            raise ForbiddenException("You cannot set an affinity for yourself.")
        if affinity not in (AffinityType.PREFERRED.value, AffinityType.BLACKLISTED.value):
            raise ForbiddenException("Unknown affinity type.")
        self._worker_profile(worker_id)
        row = self._row(customer.id, worker_id)
        if row is None:
            row = CustomerWorkerAffinity(
                customer_id=customer.id, worker_id=worker_id, affinity_type=affinity
            )
            self.db.add(row)
        else:
            row.affinity_type = affinity
        self.db.flush()
        logger.info(
            "affinity_set customer=%s worker=%s type=%s", customer.id, worker_id, affinity
        )
        return row

    def remove_affinity(self, customer: User, worker_id: str) -> bool:
        if customer.role != UserRole.CUSTOMER.value:
            raise ForbiddenException("Only customers can manage worker preferences.")
        row = self._row(customer.id, worker_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        logger.info("affinity_removed customer=%s worker=%s", customer.id, worker_id)
        return True

    def list_for_customer(self, customer: User) -> dict:
        rows = list(
            self.db.scalars(
                select(CustomerWorkerAffinity)
                .where(CustomerWorkerAffinity.customer_id == customer.id)
                .order_by(CustomerWorkerAffinity.updated_at.desc())
            )
        )
        preferred: list[dict] = []
        blacklisted: list[dict] = []
        for row in rows:
            profile = self._worker_profile(row.worker_id)
            entry = {
                "worker_id": row.worker_id,
                "affinity_type": row.affinity_type,
                "full_name": profile.user.full_name if profile.user else None,
                "avatar_url": profile.user.avatar_url if profile.user else None,
                "city": profile.city,
                "rating_average": float(profile.rating_average or 0),
                "rating_count": int(profile.rating_count or 0),
                "completed_tasks_count": int(profile.completed_tasks_count or 0),
                "tier": profile.tier,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            (preferred if row.affinity_type == AffinityType.PREFERRED.value else blacklisted).append(entry)
        return {"preferred": preferred, "blacklisted": blacklisted}
