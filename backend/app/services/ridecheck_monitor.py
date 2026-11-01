"""RideCheck: live safety anomaly detection from worker GPS telemetry.

Two detectors run on every accepted ping:

* ``ROUTE_DEVIATION`` — perpendicular distance from the active OSRM route is
  above 400 m for three consecutive pings.
* ``UNEXPLAINED_STOP`` — speed below 0.5 m/s for more than 300 seconds while
  the worker is still more than 200 m from the destination.

Each incident raises a durable ``RideCheckEvent`` and a non-dismissible
``RIDECHECK_ALERT`` WebSocket banner on both sides. The worker can clear it
with "I'm Safe — Traffic/Detour" (which also rebuilds the route from their
current position) or escalate with "Need Help / SOS". If nobody acknowledges
within 120 seconds the task is flagged on the Admin Dashboard.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import (
    NotificationType,
    RideCheckEvent,
    RideCheckStatus,
    RideCheckType,
    Task,
    TaskStatus,
    User,
    UserRole,
)
from app.notifications.dispatcher import notify_users_sync
from app.websocket.manager import fire_and_forget, manager

logger = get_logger("taskflex.ridecheck")

DEVIATION_THRESHOLD_M = 400.0
DEVIATION_CONSECUTIVE_PINGS = 3
STOP_SPEED_KMH = 1.8  # 0.5 m/s
STOP_THRESHOLD_SECONDS = 300
STOP_MIN_DISTANCE_M = 200.0
ACK_GRACE_SECONDS = 120

_state: dict[str, dict] = {}
_state_lock = threading.Lock()


def _state_for(task_id: str) -> dict:
    with _state_lock:
        return _state.setdefault(
            task_id,
            {
                "deviation_chain": 0,
                "stop_since": None,
                "open_deviation_id": None,
                "open_stop_id": None,
            },
        )


class RideCheckMonitor:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Ping evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        task: Task,
        worker_user: User,
        *,
        latitude: float,
        longitude: float,
        deviation_m: float,
        remaining_km: float,
        speed_kmph: float | None,
    ) -> list[RideCheckEvent]:
        if task.status not in (
            TaskStatus.WORKER_ON_THE_WAY.value,
            TaskStatus.IN_PROGRESS.value,
        ):
            self.clear_task(task.id)
            return []
        state = _state_for(task.id)
        raised: list[RideCheckEvent] = []

        # --- route deviation ---
        if deviation_m > DEVIATION_THRESHOLD_M:
            state["deviation_chain"] += 1
            if state["deviation_chain"] >= DEVIATION_CONSECUTIVE_PINGS:
                event = self._raise_deviation(
                    task, worker_user, latitude, longitude, deviation_m, state
                )
                if event is not None:
                    raised.append(event)
                state["deviation_chain"] = 0
        else:
            state["deviation_chain"] = 0
            if state["open_deviation_id"]:
                self._resolve(state["open_deviation_id"])
                state["open_deviation_id"] = None

        # --- unexplained stop (only while en route) ---
        if task.status == TaskStatus.WORKER_ON_THE_WAY.value:
            stopped = (
                speed_kmph is not None
                and speed_kmph * (1000.0 / 3600.0) < 0.5
                and remaining_km * 1000.0 > STOP_MIN_DISTANCE_M
            )
            if stopped:
                now_mono = datetime.now(timezone.utc).timestamp()
                if state["stop_since"] is None:
                    state["stop_since"] = now_mono
                elif (
                    now_mono - state["stop_since"] >= STOP_THRESHOLD_SECONDS
                    and not state["open_stop_id"]
                ):
                    event = self._raise_stop(
                        task, worker_user, latitude, longitude,
                        int(now_mono - state["stop_since"]), state,
                    )
                    if event is not None:
                        raised.append(event)
                    state["stop_since"] = now_mono
            else:
                state["stop_since"] = None
                if state["open_stop_id"]:
                    self._resolve(state["open_stop_id"])
                    state["open_stop_id"] = None

        if raised:
            self.db.flush()
        return raised

    def _raise_deviation(
        self,
        task: Task,
        worker: User,
        latitude: float,
        longitude: float,
        deviation_m: float,
        state: dict,
    ) -> RideCheckEvent | None:
        if state["open_deviation_id"]:
            return None
        message = (
            f"Worker is {deviation_m:.0f} m off the planned route. "
            "If this isn't a detour, contact them or use SOS."
        )
        event = RideCheckEvent(
            task_id=task.id,
            worker_id=worker.id,
            type=RideCheckType.ROUTE_DEVIATION.value,
            status=RideCheckStatus.OPEN.value,
            latitude=latitude,
            longitude=longitude,
            deviation_m=round(deviation_m, 1),
            message=message,
        )
        self.db.add(event)
        self.db.flush()
        state["open_deviation_id"] = event.id
        self._announce(task, worker, event)
        logger.warning(
            "ridecheck_deviation task=%s worker=%s deviation_m=%.0f",
            task.id, worker.id, deviation_m,
        )
        return event

    def _raise_stop(
        self,
        task: Task,
        worker: User,
        latitude: float,
        longitude: float,
        stationary_seconds: int,
        state: dict,
    ) -> RideCheckEvent | None:
        if state["open_stop_id"]:
            return None
        message = (
            f"Worker has been stationary for {stationary_seconds // 60} minutes "
            "while still on the way. Please check in."
        )
        event = RideCheckEvent(
            task_id=task.id,
            worker_id=worker.id,
            type=RideCheckType.UNEXPLAINED_STOP.value,
            status=RideCheckStatus.OPEN.value,
            latitude=latitude,
            longitude=longitude,
            stationary_seconds=stationary_seconds,
            message=message,
        )
        self.db.add(event)
        self.db.flush()
        state["open_stop_id"] = event.id
        self._announce(task, worker, event)
        logger.warning(
            "ridecheck_stop task=%s worker=%s seconds=%d",
            task.id, worker.id, stationary_seconds,
        )
        return event

    def _announce(self, task: Task, worker: User, event: RideCheckEvent) -> None:
        payload = self.serialize(event)
        recipients = [task.customer_id, worker.id]
        notify_users_sync(
            recipients,
            notification_type=NotificationType.RIDECHECK_ALERT,
            title="RideCheck safety alert",
            body=event.message or "A safety check needs your attention.",
            data=payload,
            link=f"/customer/tasks/{task.id}" if task.customer_id in recipients else None,
            db=self.db,
        )
        fire_and_forget(manager.send_to_users(recipients, "RIDECHECK_ALERT", payload))

    def _resolve(self, event_id: str) -> None:
        event = self.db.get(RideCheckEvent, event_id)
        if event is not None and event.status in (
            RideCheckStatus.OPEN.value, RideCheckStatus.ESCALATED.value
        ):
            event.status = RideCheckStatus.RESOLVED.value
            event.resolved_at = datetime.now(timezone.utc)
            self.db.flush()

    # ------------------------------------------------------------------
    # Acknowledgement / escalation
    # ------------------------------------------------------------------

    def acknowledge(
        self,
        event: RideCheckEvent,
        worker_user: User,
        *,
        action: str,
        reason: str | None = None,
    ) -> dict:
        task = self.db.get(Task, event.task_id)
        if task is None:
            return {}
        now = datetime.now(timezone.utc)
        event.acknowledged_at = now
        event.acknowledgment_reason = (reason or "")[:120] or None
        if action == "HELP":
            event.status = RideCheckStatus.ESCALATED.value
            event.admin_flagged_at = now
            recipients = self._admin_ids()
            notify_users_sync(
                recipients,
                notification_type=NotificationType.RIDECHECK_ALERT,
                title="Worker requested help",
                body=(
                    f"{worker_user.full_name} used RideCheck SOS on task "
                    f"'{task.title[:60]}'. Immediate review required."
                ),
                data=self.serialize(event),
                link="/admin/dashboard",
                db=self.db,
            )
            fire_and_forget(
                manager.send_to_users(recipients, "RIDECHECK_ESCALATED", self.serialize(event))
            )
            notify_users_sync(
                [task.customer_id],
                notification_type=NotificationType.RIDECHECK_ALERT,
                title="Your worker requested help",
                body="We alerted our safety team. You can call or message your worker now.",
                data=self.serialize(event),
                link=f"/customer/tasks/{task.id}",
                db=self.db,
            )
            fire_and_forget(
                manager.send_to_user(
                    task.customer_id, "RIDECHECK_ALERT", self.serialize(event)
                )
            )
        else:
            event.status = RideCheckStatus.ACKNOWLEDGED.value
            notify_users_sync(
                [task.customer_id],
                notification_type=NotificationType.RIDECHECK_ALERT,
                title="Worker checked in — they're safe",
                body=(
                    "Your worker acknowledged the safety alert"
                    + (f" ({reason.replace('_', ' ').title()})" if reason else "")
                    + " and is continuing to you."
                ),
                data=self.serialize(event),
                link=f"/customer/tasks/{task.id}",
                db=self.db,
            )
            fire_and_forget(
                manager.send_to_user(task.customer_id, "RIDECHECK_UPDATE", self.serialize(event))
            )
            with _state_lock:
                state = _state.get(task.id)
                if state:
                    if event.type == RideCheckType.ROUTE_DEVIATION.value:
                        # The new route was rebuilt by the route endpoint; drop
                        # the counters so a different detour can still fire.
                        state["deviation_chain"] = 0
                        state["open_deviation_id"] = None
                    elif event.type == RideCheckType.UNEXPLAINED_STOP.value:
                        state["stop_since"] = None
                        state["open_stop_id"] = None
        self.db.flush()
        logger.info(
            "ridecheck_ack event=%s action=%s reason=%s",
            event.id, action, reason,
        )
        return self.serialize(event)

    def flag_overdue(self, *, grace_seconds: int = ACK_GRACE_SECONDS) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=grace_seconds)
        candidates = list(
            self.db.scalars(
                select(RideCheckEvent).where(
                    RideCheckEvent.status == RideCheckStatus.OPEN.value,
                    RideCheckEvent.admin_flagged_at.is_(None),
                    RideCheckEvent.created_at <= cutoff,
                )
            )
        )
        if not candidates:
            return 0
        admin_ids = self._admin_ids()
        flagged = 0
        for event in candidates:
            event.status = RideCheckStatus.ESCALATED.value
            event.admin_flagged_at = datetime.now(timezone.utc)
            flagged += 1
            task = self.db.get(Task, event.task_id)
            payload = self.serialize(event)
            payload["task_title"] = task.title if task else None
            notify_users_sync(
                admin_ids,
                notification_type=NotificationType.RIDECHECK_ALERT,
                title="Unacknowledged RideCheck alert",
                body=(
                    f"No response after 120 seconds — task '{task.title[:60] if task else event.task_id}' "
                    f"has been flagged on the admin dashboard."
                ),
                data=payload,
                link="/admin/dashboard",
                db=self.db,
            )
            fire_and_forget(manager.send_to_users(admin_ids, "RIDECHECK_ESCALATED", payload))
        self.db.flush()
        logger.warning("ridecheck_escalated count=%d", flagged)
        return flagged

    def _admin_ids(self) -> list[str]:
        return list(
            self.db.scalars(
                select(User.id).where(
                    User.role == UserRole.ADMIN.value, User.is_active.is_(True)
                )
            )
        )

    # ------------------------------------------------------------------
    # Queries / lifecycle
    # ------------------------------------------------------------------

    def active_for_task(self, task_id: str) -> dict | None:
        event = self.db.scalar(
            select(RideCheckEvent)
            .where(
                RideCheckEvent.task_id == task_id,
                RideCheckEvent.status.in_(
                    [
                        RideCheckStatus.OPEN.value,
                        RideCheckStatus.ESCALATED.value,
                    ]
                ),
            )
            .order_by(RideCheckEvent.created_at.desc())
            .limit(1)
        )
        return self.serialize(event) if event else None

    def events_for_task(self, task_id: str) -> list[RideCheckEvent]:
        return list(
            self.db.scalars(
                select(RideCheckEvent)
                .where(RideCheckEvent.task_id == task_id)
                .order_by(RideCheckEvent.created_at.desc())
            )
        )

    def flagged_events(self, page: int = 1, page_size: int = 20) -> tuple[list[RideCheckEvent], int]:
        from sqlalchemy import func

        stmt = (
            select(RideCheckEvent)
            .where(RideCheckEvent.admin_flagged_at.is_not(None))
            .order_by(RideCheckEvent.admin_flagged_at.desc())
        )
        total = self.db.execute(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        ).scalar_one()
        rows = list(
            self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars()
        )
        return rows, int(total)

    def admin_resolve(self, event: RideCheckEvent, admin_user: User, note: str | None = None) -> dict:
        event.status = RideCheckStatus.RESOLVED.value
        event.resolved_at = datetime.now(timezone.utc)
        event.acknowledged_at = event.acknowledged_at or datetime.now(timezone.utc)
        event.acknowledgment_reason = (note or "resolved by admin")[:120]
        with _state_lock:
            state = _state.get(event.task_id)
            if state:
                if event.type == RideCheckType.ROUTE_DEVIATION.value:
                    state["deviation_chain"] = 0
                    state["open_deviation_id"] = None
                elif event.type == RideCheckType.UNEXPLAINED_STOP.value:
                    state["stop_since"] = None
                    state["open_stop_id"] = None
        self.db.flush()
        logger.info("ridecheck_admin_resolved event=%s admin=%s", event.id, admin_user.id)
        return self.serialize(event)

    def clear_task(self, task_id: str) -> None:
        """Task closed: resolve open incidents and drop detector state."""
        for event in self.db.scalars(
            select(RideCheckEvent).where(
                RideCheckEvent.task_id == task_id,
                RideCheckEvent.status.in_(
                    [RideCheckStatus.OPEN.value, RideCheckStatus.ESCALATED.value]
                ),
            )
        ):
            event.status = RideCheckStatus.RESOLVED.value
            event.resolved_at = datetime.now(timezone.utc)
        with _state_lock:
            _state.pop(task_id, None)
        self.db.flush()

    @staticmethod
    def serialize(event: RideCheckEvent) -> dict:
        return {
            "id": event.id,
            "task_id": event.task_id,
            "worker_id": event.worker_id,
            "type": event.type,
            "status": event.status,
            "latitude": event.latitude,
            "longitude": event.longitude,
            "deviation_m": event.deviation_m,
            "stationary_seconds": event.stationary_seconds,
            "message": event.message,
            "acknowledged_at": event.acknowledged_at.isoformat() if event.acknowledged_at else None,
            "acknowledgment_reason": event.acknowledgment_reason,
            "resolved_at": event.resolved_at.isoformat() if event.resolved_at else None,
            "admin_flagged_at": event.admin_flagged_at.isoformat() if event.admin_flagged_at else None,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "non_dismissible": event.status in (
                RideCheckStatus.OPEN.value, RideCheckStatus.ESCALATED.value
            ),
        }
