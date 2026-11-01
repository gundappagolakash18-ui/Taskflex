"""SOS safety workflow: freeze the GPS trail, alert admins, resume the task.

The freeze happens at trigger time so the evidence survives Redis eviction,
and every alert is a durable row — an admin must explicitly resolve it before
the task can continue."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, NotFoundException
from app.core.logging import get_logger
from app.models import (
    NotificationType,
    SosStatus,
    Task,
    TaskSosAlert,
    TaskStatus,
    TaskStatusHistory,
    User,
    UserRole,
)
from app.notifications.dispatcher import notify_users_sync
from app.services.task_service import broadcast_task_status
from app.websocket.manager import fire_and_forget, manager

logger = get_logger("taskflex.safety")

CLOSED_STATUSES = {TaskStatus.COMPLETED, TaskStatus.CANCELLED}


class SafetyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------- trigger ----------

    def trigger_sos(
        self,
        task: Task,
        actor: User,
        *,
        location_history: list[dict] | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        message: str | None = None,
    ) -> TaskSosAlert:
        if actor.id not in (task.customer_id, task.assigned_worker_id):
            raise NotFoundException("Task not found.")
        if TaskStatus(task.status) in CLOSED_STATUSES:
            raise ConflictException("This task is already closed — an emergency alert can no longer be raised.")

        existing = self.db.scalars(
            select(TaskSosAlert).where(
                TaskSosAlert.task_id == task.id,
                TaskSosAlert.status == SosStatus.OPEN,
            )
        ).first()
        if existing is not None:
            raise ConflictException("An emergency alert is already open for this task.")

        history = list(location_history or [])
        latest = history[-1] if history else None
        alert = TaskSosAlert(
            task_id=task.id,
            raised_by_id=actor.id,
            raised_by_role=actor.role,
            previous_status=task.status,
            status=SosStatus.OPEN,
            latitude=latitude if latitude is not None else (latest or {}).get("latitude"),
            longitude=longitude if longitude is not None else (latest or {}).get("longitude"),
            message=(message or "").strip() or None,
            location_history=history,
        )
        self.db.add(alert)

        task.status = TaskStatus.EMERGENCY_ALERT
        self.db.add(
            TaskStatusHistory(
                task_id=task.id,
                from_status=alert.previous_status,
                to_status=TaskStatus.EMERGENCY_ALERT,
                changed_by_id=actor.id,
                changed_by_role=actor.role,
                note="SOS triggered",
            )
        )
        self.db.flush()

        admins = list(
            self.db.scalars(
                select(User.id).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
            ).all()
        )
        if admins:
            notify_users_sync(
                admins,
                notification_type=NotificationType.SOS_TRIGGERED,
                title="Emergency SOS",
                body=f'{actor.full_name} raised an emergency alert on "{task.title}".',
                data={
                    "task_id": task.id,
                    "alert_id": alert.id,
                    "latitude": alert.latitude,
                    "longitude": alert.longitude,
                },
                link="/admin/sos",
                db=self.db,
            )
            fire_and_forget(
                manager.send_to_users(
                    admins,
                    "EMERGENCY_ALERT",
                    {
                        "alert_id": alert.id,
                        "task_id": task.id,
                        "raised_by_role": actor.role,
                        "latitude": alert.latitude,
                        "longitude": alert.longitude,
                        "message": alert.message,
                        "created_at": alert.created_at.isoformat() if alert.created_at else None,
                    },
                )
            )

        counterparty = task.customer_id if actor.id == task.assigned_worker_id else task.assigned_worker_id
        if counterparty:
            notify_users_sync(
                [counterparty],
                notification_type=NotificationType.SOS_TRIGGERED,
                title="Emergency alert raised",
                body="An emergency alert was raised on your task. Support has been notified.",
                data={"task_id": task.id, "alert_id": alert.id},
                link=f"/tasks/{task.id}",
                db=self.db,
            )

        broadcast_task_status(task)
        self.db.refresh(alert)
        logger.info(
            "sos_triggered",
            extra_fields={
                "task_id": task.id,
                "alert_id": alert.id,
                "role": actor.role,
                "admins_alerted": len(admins),
                "frozen_positions": len(history),
            },
        )
        return alert

    # ---------- admin handling ----------

    def get_alert_or_404(self, alert_id: str) -> TaskSosAlert:
        alert = self.db.get(TaskSosAlert, alert_id)
        if alert is None:
            raise NotFoundException("Emergency alert not found.")
        return alert

    def list_alerts(
        self, *, status: str | None = None, page: int = 1, page_size: int = 20
    ) -> tuple[list[TaskSosAlert], int]:
        filters = []
        if status:
            filters.append(TaskSosAlert.status == status)
        total = self.db.execute(
            select(func.count()).select_from(TaskSosAlert).where(*filters)
        ).scalar_one()
        rows = list(
            self.db.scalars(
                select(TaskSosAlert)
                .where(*filters)
                .order_by(TaskSosAlert.created_at.desc())
                .offset((max(page, 1) - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return rows, int(total)

    def resolve_alert(self, alert: TaskSosAlert, admin: User, note: str | None) -> TaskSosAlert:
        if alert.status == SosStatus.RESOLVED:
            raise ConflictException("This emergency alert is already resolved.")
        alert.status = SosStatus.RESOLVED
        alert.resolved_by_id = admin.id
        alert.resolved_at = datetime.now(timezone.utc)
        alert.resolution_note = (note or "").strip() or None

        task = self.db.get(Task, alert.task_id)
        if task is not None and task.status == TaskStatus.EMERGENCY_ALERT:
            task.status = alert.previous_status
            self.db.add(
                TaskStatusHistory(
                    task_id=task.id,
                    from_status=TaskStatus.EMERGENCY_ALERT,
                    to_status=task.status,
                    changed_by_id=admin.id,
                    changed_by_role=admin.role,
                    note="SOS resolved by support",
                )
            )
        self.db.flush()

        recipients = {alert.raised_by_id}
        if task is not None:
            recipients.add(task.customer_id)
            if task.assigned_worker_id:
                recipients.add(task.assigned_worker_id)
        notify_users_sync(
            sorted(recipients),
            notification_type=NotificationType.SOS_TRIGGERED,
            title="Emergency alert resolved",
            body="Support has resolved the emergency alert on your task.",
            data={"task_id": alert.task_id, "alert_id": alert.id},
            link=f"/tasks/{alert.task_id}",
            db=self.db,
        )
        if task is not None:
            broadcast_task_status(task)

        self.db.refresh(alert)
        logger.info(
            "sos_resolved",
            extra_fields={"task_id": alert.task_id, "alert_id": alert.id, "admin_id": admin.id},
        )
        return alert
