"""Dispute lifecycle: participants raise, admins resolve."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.core.logging import get_logger
from app.models import Dispute, DisputeStatus, NotificationType, Task, User, UserRole
from app.notifications.dispatcher import notify_users_sync
from app.repositories import DisputeRepository
from app.services.task_service import TaskService

logger = get_logger("taskflex.disputes")

ALLOWED_REASON_TAGS = {
    "worker_no_show",
    "work_not_done",
    "behaviour",
    "payment_issue",
    "safety_concern",
    "other",
}


class DisputeService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = DisputeRepository(db)
        self.task_service = TaskService(db)

    def raise_dispute(self, task: Task, raiser: User, *, reason: str, description: str) -> Dispute:
        if reason not in ALLOWED_REASON_TAGS:
            raise NotFoundException(f"Unknown dispute reason '{reason}'.")
        if raiser.id not in (task.customer_id, task.assigned_worker_id):
            raise ForbiddenException("Only task participants can open a dispute.")

        existing = self.db.scalar(select(Dispute).where(Dispute.task_id == task.id))
        if existing is not None:
            raise ConflictException("A dispute is already open for this task.")

        if task.status not in ("ACCEPTED", "WORKER_ON_THE_WAY", "IN_PROGRESS", "COMPLETED"):
            raise ConflictException(f"A task in status {task.status} cannot be disputed.")

        against_id = task.assigned_worker_id if raiser.id == task.customer_id else task.customer_id
        dispute = Dispute(
            task_id=task.id,
            raised_by_id=raiser.id,
            against_id=against_id,
            reason=reason,
            description=description.strip()[:4000],
            status=DisputeStatus.OPEN,
        )
        self.repo.add(dispute)

        self.task_service.mark_disputed(task)

        notify_users_sync(
            [u for u in {task.customer_id, task.assigned_worker_id} if u and u != raiser.id],
            notification_type=NotificationType.DISPUTE_CREATED,
            title=f"Dispute opened for '{task.title}'",
            body="Our team will review the case and get back to both parties.",
            data={"task_id": task.id, "dispute_id": dispute.id},
            db=self.db,
        )
        self.db.flush()
        logger.info(
            "dispute_opened",
            extra_fields={"task_id": task.id, "dispute_id": dispute.id, "raised_by": raiser.id},
        )
        return dispute

    def get_dispute_or_404(self, dispute_id: str) -> Dispute:
        dispute = self.repo.get(dispute_id)
        if dispute is None:
            raise NotFoundException("Dispute not found.")
        return dispute

    def assert_can_view(self, dispute: Dispute, user: User) -> None:
        if user.role == UserRole.ADMIN.value:
            return
        task = self.task_service.get_task_or_404(dispute.task_id)
        if user.id in (task.customer_id, task.assigned_worker_id):
            return
        raise ForbiddenException("You do not have access to this dispute.")

    def list_disputes(self, status: str | None, page: int, page_size: int):
        return self.repo.all_disputes(page=page, page_size=page_size, status=status)

    def resolve(self, dispute: Dispute, admin: User, *, outcome: str, resolution_note: str) -> Dispute:
        if admin.role != UserRole.ADMIN.value:
            raise ForbiddenException("Only admins can resolve disputes.")
        if dispute.status in (DisputeStatus.RESOLVED.value, DisputeStatus.REJECTED.value):
            raise ConflictException("This dispute is already closed.")

        dispute.status = outcome
        dispute.resolution_note = resolution_note.strip()[:4000]
        dispute.resolved_by_id = admin.id
        dispute.resolved_at = datetime.now(timezone.utc)

        task = self.task_service.get_task_or_404(dispute.task_id)
        if outcome == DisputeStatus.RESOLVED.value:
            # Release payment to the worker if it was still held.
            if task.payment_status == "AUTHORIZED":
                from app.services.payment_service import PaymentService

                try:
                    PaymentService(self.db).capture_for_task(task)
                except Exception:
                    logger.exception("dispute_resolution_capture_failed task=%s", task.id)
        elif outcome == DisputeStatus.REJECTED.value and task.payment_status == "AUTHORIZED":
            from app.services.payment_service import PaymentService

            try:
                PaymentService(self.db).refund_task(task, reason="Dispute rejected — amount refunded")
            except Exception:
                logger.exception("dispute_resolution_refund_failed task=%s", task.id)

        notify_users_sync(
            [u for u in {task.customer_id, task.assigned_worker_id} if u],
            notification_type=NotificationType.DISPUTE_RESOLVED,
            title=f"Dispute {outcome.lower()} for '{task.title}'",
            body=dispute.resolution_note[:200] if dispute.resolution_note else "The case is now closed.",
            data={"task_id": task.id, "dispute_id": dispute.id},
            db=self.db,
        )
        self.db.flush()
        return dispute
