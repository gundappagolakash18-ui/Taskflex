"""Operations watchdog — scheduling, bids, quests, safety and offer expiry.

Runs every 60 seconds in the FastAPI lifespan:

* Scheduled reservations: T-45 readiness reminder, T-30 revoke + live
  dispatch, T-0 promotion of confirmed reservations to ACCEPTED. Unclaimed
  scheduled tasks open for live dispatch at T-30 as well.
* Expire stale counter-offers and dispatch offers.
* Seed the day's quests and escalate RideCheck incidents unanswered for
  120 seconds.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.timeutils import as_aware
from app.db.session import SessionLocal
from app.dispatch.engine import dispatch_engine
from app.models import (
    NotificationType,
    Task,
    TaskAssignment,
    TaskOffer,
    TaskStatus,
    TaskStatusHistory,
)
from app.notifications.dispatcher import notify_users_sync
from app.services.bidding_service import BiddingService
from app.services.gamification_service import GamificationService
from app.services.payment_service import PaymentService
from app.services.ridecheck_monitor import RideCheckMonitor
from app.services.task_service import TaskService, broadcast_task_status
from app.websocket.manager import fire_and_forget, manager

logger = get_logger("watchdog.ops")

READINESS_REMINDER_MINUTES = 45
REVOKE_MINUTES = 30
SWEEP_SECONDS = 60

_reminded: set[str] = set()


class ReserveWatchdog:
    def __init__(self, db: Session):
        self.db = db

    def tick(self) -> dict:
        now = datetime.now(timezone.utc)
        counts = {"reminded": 0, "revoked": 0, "opened": 0, "activated": 0}
        scheduled = list(
            self.db.scalars(
                select(Task).where(
                    Task.is_scheduled.is_(True),
                    Task.status.in_(
                        [
                            TaskStatus.SCHEDULED_OPEN.value,
                            TaskStatus.SCHEDULED_ASSIGNED.value,
                        ]
                    ),
                    Task.scheduled_for.is_not(None),
                )
            )
        )
        for task in scheduled:
            scheduled_for = as_aware(task.scheduled_for)
            seconds_left = (scheduled_for - now).total_seconds()
            if task.status == TaskStatus.SCHEDULED_OPEN.value:
                if seconds_left <= REVOKE_MINUTES * 60:
                    self._open_for_dispatch(task, reason="scheduled window opened without a reservation")
                    counts["opened"] += 1
                continue
            if task.worker_confirmed_readiness:
                if seconds_left <= 0:
                    self._activate(task)
                    counts["activated"] += 1
                continue
            if seconds_left <= REVOKE_MINUTES * 60:
                self._revoke(task)
                counts["revoked"] += 1
            elif seconds_left <= READINESS_REMINDER_MINUTES * 60:
                if task.id not in _reminded:
                    self._remind(task)
                    counts["reminded"] += 1
        if any(counts.values()):
            logger.info("reserve_watchdog %s", counts)
        return counts

    def _remind(self, task: Task) -> None:
        _reminded.add(task.id)
        when = as_aware(task.scheduled_for).strftime("%d %b, %I:%M %p")
        notify_users_sync(
            [task.assigned_worker_id],
            notification_type=NotificationType.READINESS_REQUIRED,
            title="Confirm I'm Ready",
            body=f"Your reserved task '{task.title[:60]}' starts at {when}. "
                 f"Confirm readiness in the next 15 minutes or the reservation is released.",
            data={"task_id": task.id, "scheduled_for": task.scheduled_for.isoformat()
                  if task.scheduled_for else None},
            link="/worker/reserved",
            db=self.db,
        )
        fire_and_forget(
            manager.send_to_user(
                task.assigned_worker_id,
                "READINESS_REQUIRED",
                {
                    "task_id": task.id,
                    "title": task.title,
                    "scheduled_for": task.scheduled_for.isoformat() if task.scheduled_for else None,
                },
            )
        )

    def _revoke(self, task: Task) -> None:
        worker_id = task.assigned_worker_id
        for assignment in self.db.scalars(
            select(TaskAssignment).where(
                TaskAssignment.task_id == task.id,
                TaskAssignment.worker_id == worker_id,
                TaskAssignment.status == "ACTIVE",
            )
        ):
            assignment.status = "CANCELLED"
        previous = task.status
        task.assigned_worker_id = None
        task.worker_confirmed_readiness = False
        task.status = TaskStatus.SEARCHING_WORKER.value
        self.db.add(
            TaskStatusHistory(
                task_id=task.id,
                from_status=previous,
                to_status=TaskStatus.SEARCHING_WORKER.value,
                note="reservation released — readiness was not confirmed by T-30",
            )
        )
        self.db.flush()
        if worker_id:
            notify_users_sync(
                [worker_id],
                notification_type=NotificationType.RESERVATION_REVOKED,
                title="Reservation released",
                body=f"You did not confirm readiness for '{task.title[:60]}'. "
                     f"The task has been opened to other workers.",
                data={"task_id": task.id},
                link="/worker/reserved",
                db=self.db,
            )
            fire_and_forget(
                manager.send_to_user(
                    worker_id,
                    "RESERVATION_REVOKED",
                    {"task_id": task.id, "title": task.title},
                )
            )
            notify_users_sync(
                [task.customer_id],
                notification_type=NotificationType.SYSTEM,
                title="Reserved worker released",
                body=f"We're re-matching '{task.title[:60]}' to another verified worker now.",
                data={"task_id": task.id},
                link=f"/customer/tasks/{task.id}",
                db=self.db,
            )
        self._open_for_dispatch(task, reason="reservation revoked", set_status=False)
        logger.info("reservation_revoked task=%s worker=%s", task.id, worker_id)

    def _open_for_dispatch(self, task: Task, *, reason: str, set_status: bool = True) -> None:
        if set_status:
            previous = task.status
            task.status = TaskStatus.SEARCHING_WORKER.value
            self.db.add(
                TaskStatusHistory(
                    task_id=task.id,
                    from_status=previous,
                    to_status=TaskStatus.SEARCHING_WORKER.value,
                    note=reason,
                )
            )
            self.db.flush()
        candidates = dispatch_engine.start(self.db, task)
        if candidates == 0:
            notify_users_sync(
                [task.customer_id],
                notification_type=NotificationType.SYSTEM,
                title="No workers available yet",
                body=f"'{task.title[:60]}' is open for matching — we'll offer it as verified workers come online.",
                data={"task_id": task.id},
                link=f"/customer/tasks/{task.id}",
                db=self.db,
            )
        broadcast_task_status(task)
        logger.info("scheduled_task_opened task=%s reason=%s candidates=%d", task.id, reason, candidates)

    def _activate(self, task: Task) -> None:
        TaskService(self.db).activate_reservation(
            task, reason="scheduled start reached with confirmed readiness"
        )


def _tick_once() -> None:
    db = SessionLocal()
    try:
        ReserveWatchdog(db).tick()
        BiddingService(db).expire_bids()
        GamificationService(db).ensure_daily_quests()
        RideCheckMonitor(db).flag_overdue()
        TaskService(db).expire_stale_offers()
        _expire_stale_scheduled_offers(db)
        dispatch_engine.recover_open_tasks(db)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("operations_watchdog_tick_failed")
    finally:
        db.close()


def _expire_stale_scheduled_offers(db: Session) -> None:
    """Offers whose countdown lapsed but whose timer thread died with a restart."""
    from app.core.timeutils import utcnow_naive
    from sqlalchemy import or_

    stale = list(
        db.scalars(
            select(TaskOffer).where(
                TaskOffer.status == "PENDING",
                TaskOffer.expires_at.is_not(None),
                TaskOffer.expires_at <= utcnow_naive(),
            )
        )
    )
    for offer in stale:
        offer.status = "TIMEOUT"
        offer.responded_at = datetime.now(timezone.utc)
    if stale:
        db.flush()


async def run_operations_watchdog(stop_event: asyncio.Event) -> None:
    logger.info("operations_watchdog started (interval=%ss)", SWEEP_SECONDS)
    while not stop_event.is_set():
        await asyncio.to_thread(_tick_once)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=SWEEP_SECONDS)
        except asyncio.TimeoutError:
            continue
    logger.info("operations_watchdog stopped")
