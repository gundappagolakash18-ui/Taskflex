"""Counter-offer bidding: workers propose a price, the customer accepts one.

Bids live only while the task is still searching. Each bid carries a
45-second acceptance window; when the customer accepts, the budget is
updated, the worker is assigned atomically under the same dispatch lock
used by ring-down offers, every other bid/offer is expired, and the extra
escrow delta is held through PaymentService.

WebSocket event: ``TASK_BID_RECEIVED`` pushed to the task owner with the
worker's public profile, rating, distance and proposed price.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.logging import get_logger
from app.core.timeutils import as_aware, utcnow
from app.dispatch.engine import dispatch_engine
from app.matching.geo import haversine_km
from app.models import (
    AffinityType,
    BidStatus,
    CustomerWorkerAffinity,
    NotificationType,
    Task,
    TaskAssignment,
    TaskBid,
    TaskOffer,
    TaskStatus,
    TaskStatusHistory,
    User,
    UserRole,
    WorkerProfile,
)
from app.notifications.dispatcher import notify_users_sync
from app.repositories import TaskRepository, UserRepository
from app.services.payment_service import PaymentService
from app.websocket.manager import fire_and_forget, manager

logger = get_logger("taskflex.bidding")

BID_TTL_SECONDS = 45
MIN_BID_ABOVE_BUDGET = 10.0
MAX_BID_MULTIPLIER = 1.5


class BiddingService:
    def __init__(self, db: Session):
        self.db = db
        self.tasks = TaskRepository(db)
        self.users = UserRepository(db)
        self.payments = PaymentService(db)

    # ------------------------------------------------------------------
    # Worker side
    # ------------------------------------------------------------------

    def place_bid(
        self,
        task: Task,
        worker: User,
        *,
        proposed_amount: float,
        note: str | None = None,
        estimated_arrival_minutes: int = 0,
    ) -> TaskBid:
        if worker.role != UserRole.WORKER.value:
            raise ForbiddenException("Only workers can place bids.")
        if task.customer_id == worker.id:
            raise ForbiddenException("You cannot bid on your own task.")
        if task.status not in (TaskStatus.SEARCHING_WORKER.value, TaskStatus.OFFERED.value):
            raise ConflictException("This task is no longer accepting counter-offers.")
        profile = self.users.get_worker_profile(worker.id)
        if profile is None:
            raise ForbiddenException("Worker profile missing.")
        if not profile.is_verified:
            raise ForbiddenException("Only verified workers can bid on tasks.")
        blacklisted = self.db.scalar(
            select(CustomerWorkerAffinity.id).where(
                CustomerWorkerAffinity.customer_id == task.customer_id,
                CustomerWorkerAffinity.worker_id == worker.id,
                CustomerWorkerAffinity.affinity_type == AffinityType.BLACKLISTED.value,
            )
        )
        if blacklisted:
            raise ForbiddenException("This customer has blocked you from their tasks.")

        budget = float(task.budget or 0)
        amount = round(float(proposed_amount), 2)
        minimum = round(budget + MIN_BID_ABOVE_BUDGET, 2)
        maximum = round(budget * MAX_BID_MULTIPLIER, 2)
        if amount < minimum or amount > maximum:
            raise ConflictException(
                f"Your counter-offer must be between ₹{minimum:.0f} and ₹{maximum:.0f} "
                f"for this ₹{budget:.0f} task."
            )

        now = datetime.now(timezone.utc)
        existing = self.db.scalar(
            select(TaskBid).where(
                TaskBid.task_id == task.id,
                TaskBid.worker_id == worker.id,
                TaskBid.status == BidStatus.PENDING.value,
            )
        )
        if existing is not None:
            existing.proposed_amount = amount
            existing.note = (note or "").strip()[:140] or None
            existing.estimated_arrival_minutes = max(0, int(estimated_arrival_minutes or 0))
            existing.expires_at = now + timedelta(seconds=BID_TTL_SECONDS)
            bid = existing
        else:
            bid = TaskBid(
                task_id=task.id,
                worker_id=worker.id,
                proposed_amount=amount,
                note=(note or "").strip()[:140] or None,
                estimated_arrival_minutes=max(0, int(estimated_arrival_minutes or 0)),
                status=BidStatus.PENDING.value,
                expires_at=now + timedelta(seconds=BID_TTL_SECONDS),
            )
            self.db.add(bid)
        self.db.flush()

        payload = self.bid_payload(bid, task)
        notify_users_sync(
            [task.customer_id],
            notification_type=NotificationType.TASK_BID_RECEIVED,
            title=f"New counter-offer: ₹{amount:.0f}",
            body=f"{worker.full_name} offered ₹{amount:.0f} for '{task.title[:60]}'. "
                 f"Accept within {BID_TTL_SECONDS} seconds.",
            data=payload,
            link=f"/customer/tasks/{task.id}",
            db=self.db,
        )
        fire_and_forget(manager.send_to_user(task.customer_id, "TASK_BID_RECEIVED", payload))
        logger.info(
            "bid_placed task=%s worker=%s amount=%.2f bid=%s",
            task.id, worker.id, amount, bid.id,
        )
        return bid

    def my_bid(self, task: Task, worker_user: User) -> TaskBid | None:
        return self.db.scalar(
            select(TaskBid)
            .where(TaskBid.task_id == task.id, TaskBid.worker_id == worker_user.id)
            .order_by(TaskBid.created_at.desc())
            .limit(1)
        )

    def worker_bids(self, worker_user: User) -> list[TaskBid]:
        return list(
            self.db.scalars(
                select(TaskBid)
                .where(TaskBid.worker_id == worker_user.id)
                .order_by(TaskBid.created_at.desc())
                .limit(100)
            )
        )

    # ------------------------------------------------------------------
    # Customer side
    # ------------------------------------------------------------------

    def bids_for_task(self, task: Task, viewer: User) -> list[TaskBid]:
        if viewer.role != UserRole.ADMIN.value and task.customer_id != viewer.id:
            raise ForbiddenException("Only the task owner can view counter-offers.")
        self.expire_bids(task_id=task.id)
        return list(
            self.db.scalars(
                select(TaskBid)
                .where(TaskBid.task_id == task.id)
                .order_by(TaskBid.proposed_amount.asc(), TaskBid.created_at.asc())
            )
        )

    def accept_bid(self, bid_id: str, customer: User) -> Task:
        bid = self.db.get(TaskBid, bid_id)
        if bid is None:
            raise NotFoundException("Counter-offer not found.")
        task = self.tasks.get(bid.task_id)
        if task is None:
            raise NotFoundException("Task not found.")
        if task.customer_id != customer.id:
            raise ForbiddenException("Only the task owner can accept a counter-offer.")
        if bid.status != BidStatus.PENDING.value:
            raise ConflictException("This counter-offer is no longer pending.")
        if bid.expires_at is not None and as_aware(bid.expires_at) < utcnow():
            bid.status = BidStatus.EXPIRED.value
            bid.responded_at = utcnow()
            self.db.flush()
            raise ConflictException("This counter-offer has expired.")
        if task.status not in (TaskStatus.SEARCHING_WORKER.value, TaskStatus.OFFERED.value):
            raise ConflictException("This task is no longer accepting workers.")
        if task.assigned_worker_id is not None:
            raise ConflictException("A worker is already assigned to this task.")
        if not dispatch_engine.try_acquire_lock(task.id, customer.id):
            raise ConflictException("A worker was just assigned to this task.")
        try:
            return self._accept_locked(bid, task, customer)
        except Exception:
            dispatch_engine.release_lock(task.id)
            raise

    def _accept_locked(self, bid: TaskBid, task: Task, customer: User) -> Task:
        worker = self.db.get(User, bid.worker_id)
        if worker is None or not worker.is_active:
            raise ConflictException("This worker is no longer available.")
        profile = self.users.get_worker_profile(worker.id)
        if profile is None or not profile.is_verified:
            raise ConflictException("This worker is not verified.")

        active = self.tasks.worker_active_task_count(worker.id)
        if active >= (profile.max_concurrent_tasks or 1):
            raise ConflictException(
                f"{worker.full_name} is currently at their concurrent task limit. "
                "Decline this bid and pick another worker."
            )

        previous_budget = float(task.budget or 0)
        new_budget = round(float(bid.proposed_amount), 2)
        rate = self.payments.commission_rate_for(worker.id)
        commission, _payout = self.payments.split_for(new_budget, rate)
        now = datetime.now(timezone.utc)

        task.budget = Decimal(str(new_budget))
        self.db.add(
            TaskAssignment(
                task_id=task.id,
                worker_id=worker.id,
                earnings_amount=Decimal(str(new_budget)),
                commission_amount=Decimal(str(commission)),
                accepted_at=now,
            )
        )
        previous_status = task.status
        task.assigned_worker_id = worker.id
        task.status = TaskStatus.ACCEPTED.value
        task.bids_close_at = None
        self.db.add(
            TaskStatusHistory(
                task_id=task.id,
                from_status=previous_status,
                to_status=TaskStatus.ACCEPTED.value,
                changed_by_id=customer.id,
                changed_by_role=customer.role,
                note=f"customer accepted counter-offer of ₹{new_budget:.0f}",
            )
        )

        bid.status = BidStatus.ACCEPTED.value
        bid.responded_at = now
        for sibling in self.db.scalars(
            select(TaskBid).where(
                TaskBid.task_id == task.id,
                TaskBid.id != bid.id,
                TaskBid.status == BidStatus.PENDING.value,
            )
        ):
            sibling.status = BidStatus.EXPIRED.value
            sibling.responded_at = now
        for offer in self.db.scalars(
            select(TaskOffer).where(
                TaskOffer.task_id == task.id, TaskOffer.status == "PENDING"
            )
        ):
            offer.status = "EXPIRED"
            offer.responded_at = now

        dispatch_engine.finalize_accept(task.id)

        # Re-price the base hold at the worker's tier, then hold the delta.
        self.payments.apply_worker_rate(task)
        delta_payment = self.payments.adjust_for_budget(task, previous_budget)

        other_bidder_ids = [
            b.worker_id
            for b in self.db.scalars(
                select(TaskBid).where(
                    TaskBid.task_id == task.id,
                    TaskBid.id != bid.id,
                    TaskBid.status == BidStatus.EXPIRED.value,
                )
            )
        ]
        client_ws_payload = {
            "task_id": task.id,
            "bid_id": bid.id,
            "worker_id": worker.id,
            "worker_name": worker.full_name,
            "budget": new_budget,
            "payment_status": task.payment_status,
            "delta_due": float(delta_payment.amount) if delta_payment is not None
                          and delta_payment.status != "AUTHORIZED" else 0.0,
        }
        notify_users_sync(
            [worker.id],
            notification_type=NotificationType.TASK_BID_ACCEPTED,
            title=f"Your counter-offer was accepted: ₹{new_budget:.0f}",
            body=f"The customer accepted your bid for '{task.title[:60]}'. "
                 f"Head to the task location as planned.",
            data={"task_id": task.id},
            link="/worker/tasks",
            db=self.db,
        )
        if other_bidder_ids:
            notify_users_sync(
                other_bidder_ids,
                notification_type=NotificationType.SYSTEM,
                title="Counter-offer closed",
                body=f"'{task.title[:60]}' was assigned to another worker.",
                data={"task_id": task.id},
                db=self.db,
            )
        if delta_payment is not None and delta_payment.status != "AUTHORIZED":
            notify_users_sync(
                [customer.id],
                notification_type=NotificationType.PAYMENT_SUCCESSFUL,
                title="Complete the price difference",
                body=(
                    f"Your accepted counter-offer raised the budget by "
                    f"₹{float(delta_payment.amount):.0f}. Please complete the additional "
                    f"payment so the worker is fully covered."
                ),
                data={"task_id": task.id, "amount": float(delta_payment.amount),
                      "purpose": "BID_DELTA"},
                link=f"/customer/tasks/{task.id}",
                db=self.db,
            )
        fire_and_forget(manager.send_to_user(worker.id, "TASK_BID_ACCEPTED", client_ws_payload))
        payload = {"task_id": task.id, "status": task.status}
        fire_and_forget(manager.send_to_users([task.customer_id, worker.id], "TASK_STATUS", payload))
        self.db.flush()
        logger.info(
            "bid_accepted task=%s worker=%s amount=%.2f",
            task.id, worker.id, new_budget,
        )
        return task

    def decline_bid(self, bid_id: str, customer: User) -> TaskBid:
        bid = self.db.get(TaskBid, bid_id)
        if bid is None:
            raise NotFoundException("Counter-offer not found.")
        task = self.db.get(Task, bid.task_id)
        if task is None or task.customer_id != customer.id:
            raise ForbiddenException("Only the task owner can decline a counter-offer.")
        if bid.status != BidStatus.PENDING.value:
            raise ConflictException("This counter-offer is no longer pending.")
        bid.status = BidStatus.DECLINED.value
        bid.responded_at = utcnow()
        notify_users_sync(
            [bid.worker_id],
            notification_type=NotificationType.SYSTEM,
            title="Counter-offer declined",
            body=f"The customer declined your bid for '{task.title[:60]}'.",
            data={"task_id": task.id},
            db=self.db,
        )
        self.db.flush()
        return bid

    # ------------------------------------------------------------------
    # Sweeps / serialization
    # ------------------------------------------------------------------

    def expire_bids(self, *, task_id: str | None = None) -> int:
        stmt = select(TaskBid).where(
            TaskBid.status == BidStatus.PENDING.value,
            TaskBid.expires_at.is_not(None),
            TaskBid.expires_at <= utcnow(),
        )
        if task_id:
            stmt = stmt.where(TaskBid.task_id == task_id)
        expired = list(self.db.scalars(stmt))
        for bid in expired:
            bid.status = BidStatus.EXPIRED.value
            bid.responded_at = utcnow()
        if expired:
            self.db.flush()
        return len(expired)

    def bid_payload(self, bid: TaskBid, task: Task) -> dict:
        profile = self.users.get_worker_profile(bid.worker_id)
        distance_km = None
        if profile is not None and profile.latitude is not None and task.latitude is not None:
            distance_km = round(
                haversine_km(
                    float(task.latitude), float(task.longitude),
                    float(profile.latitude), float(profile.longitude),
                ),
                2,
            )
        return {
            "bid_id": bid.id,
            "task_id": task.id,
            "status": bid.status,
            "proposed_amount": float(bid.proposed_amount),
            "note": bid.note,
            "estimated_arrival_minutes": bid.estimated_arrival_minutes,
            "expires_at": bid.expires_at.isoformat() if bid.expires_at else None,
            "expires_in": BID_TTL_SECONDS,
            "distance_km": distance_km,
            "worker": {
                "id": bid.worker_id,
                "full_name": bid.worker.full_name if bid.worker else (profile.user.full_name if profile else ""),
                "avatar_url": (bid.worker.avatar_url if bid.worker else None),
                "rating_average": float(profile.rating_average or 0) if profile else 0.0,
                "rating_count": int(profile.rating_count or 0) if profile else 0,
                "completed_tasks_count": int(profile.completed_tasks_count or 0) if profile else 0,
                "is_verified": bool(profile.is_verified) if profile else False,
                "tier": profile.tier if profile else "SILVER",
            },
            "created_at": bid.created_at.isoformat() if bid.created_at else None,
        }
