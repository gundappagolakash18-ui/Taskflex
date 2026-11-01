"""Admin operations: user management, worker verification, task oversight,
payments view, settings and audit logs."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.core.logging import get_logger
from app.models import (
    Task,
    User,
    UserRole,
    VerificationDocument,
    VerificationStatus,
    WorkerProfile,
)
from app.notifications.dispatcher import notify_users_sync
from app.repositories import (
    AuditRepository,
    PaymentRepository,
    SettingsRepository,
    TaskRepository,
    UserRepository,
)
from app.services.task_service import TaskService
from app.storage import get_storage

logger = get_logger("taskflex.admin")


class AdminService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.tasks = TaskRepository(db)
        self.payments = PaymentRepository(db)
        self.audit = AuditRepository(db)
        self.settings = SettingsRepository(db)

    # ---------- users ----------

    def list_users(self, *, role: str | None, search: str | None, is_active: bool | None,
                   page: int, page_size: int):
        return self.users.search_users(
            role=role, search=search, is_active=is_active, page=page, page_size=page_size
        )

    def set_user_active(self, admin: User, user_id: str, is_active: bool) -> User:
        user = self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundException("User not found.")
        if user.id == admin.id:
            raise ConflictException("You cannot deactivate your own admin account.")
        if user.role == UserRole.ADMIN.value:
            raise ForbiddenException("Admin accounts cannot be modified from the dashboard.")
        user.is_active = is_active
        self.audit.log(
            user_id=admin.id,
            action="user_deactivated" if not is_active else "user_reactivated",
            entity_type="user",
            entity_id=user.id,
        )
        self.db.flush()
        return user

    # ---------- worker verification ----------

    def pending_verifications(self, page: int, page_size: int):
        stmt = (
            select(VerificationDocument)
            .where(VerificationDocument.status == VerificationStatus.PENDING)
            .order_by(VerificationDocument.created_at.asc())
        )
        from sqlalchemy import func

        total = self.db.execute(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        ).scalar_one()
        rows = self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        return list(rows), total

    def decide_verification(
        self, admin: User, document_id: str, *, approve: bool, reason: str | None = None
    ) -> VerificationDocument:
        doc = self.db.get(VerificationDocument, document_id)
        if doc is None:
            raise NotFoundException("Document not found.")
        if doc.status != VerificationStatus.PENDING:
            raise ConflictException(f"This document was already {doc.status.lower()}.")

        doc.status = VerificationStatus.APPROVED if approve else VerificationStatus.REJECTED
        doc.reviewed_by_id = admin.id
        doc.reviewed_at = datetime.now(timezone.utc)
        if not approve:
            doc.rejection_reason = (reason or "Document could not be verified.")[:1000]

        profile = self.db.scalar(select(WorkerProfile).where(WorkerProfile.id == doc.worker_profile_id))
        if profile:
            if approve:
                pending = self.db.scalar(
                    select(VerificationDocument).where(
                        VerificationDocument.worker_profile_id == profile.id,
                        VerificationDocument.id != doc.id,
                        VerificationDocument.status == VerificationStatus.PENDING,
                    )
                )
                if pending is None:
                    profile.verification_status = VerificationStatus.APPROVED
                    profile.is_verified = True
            else:
                profile.verification_status = VerificationStatus.PENDING
                profile.is_verified = False

        self.audit.log(
            user_id=admin.id,
            action="verification_approved" if approve else "verification_rejected",
            entity_type="verification_document",
            entity_id=doc.id,
        )
        notify_users_sync(
            [profile.user_id] if profile else [],
            notification_type="SYSTEM",
            title="Verification update",
            body=(
                "Your document was approved — you are now a verified worker."
                if approve
                else f"Your document was rejected: {doc.rejection_reason}"
            ),
            link="/worker/profile",
            db=self.db,
        )
        self.db.flush()
        if approve and profile and profile.is_verified and profile.is_online:
            from app.dispatch import dispatch_engine

            dispatch_engine.recover_open_tasks(self.db)
        return doc

    def list_workers(self, *, search: str | None, verified: bool | None, online: bool | None,
                     page: int, page_size: int):
        from sqlalchemy import func, or_
        from sqlalchemy.orm import selectinload

        from app.models import WorkerSkill

        query = (
            select(WorkerProfile)
            .join(User, User.id == WorkerProfile.user_id)
            .where(User.is_active.is_(True))
        )
        if search:
            like = f"%{search.lower()}%"
            query = query.where(or_(func.lower(User.full_name).like(like), func.lower(User.email).like(like)))
        if verified is not None:
            query = query.where(WorkerProfile.is_verified == verified)
        if online is not None:
            query = query.where(WorkerProfile.is_online == online)

        query = query.options(
            selectinload(WorkerProfile.user),
            selectinload(WorkerProfile.skills).selectinload(WorkerSkill.skill),
        )
        query = query.order_by(WorkerProfile.created_at.desc())
        total = self.db.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        ).scalar_one()
        rows = self.db.execute(query.offset((page - 1) * page_size).limit(page_size)).scalars().unique().all()
        return list(rows), total

    # ---------- tasks / payments ----------

    def list_tasks(self, *, status: str | None, task_type: str | None, search: str | None,
                   page: int, page_size: int):
        return self.tasks.search_admin(
            status=status, task_type=task_type, search=search, page=page, page_size=page_size
        )

    def admin_cancel_task(self, admin: User, task_id: str, reason: str) -> Task:
        service = TaskService(self.db)
        task = service.get_task_or_404(task_id)
        return service.cancel_task(task, admin, reason=reason)

    def list_payments(self, page: int, page_size: int, status: str | None = None):
        return self.payments.all_payments(page=page, page_size=page_size, status=status)

    def list_transactions(self, page: int, page_size: int, search: str | None = None):
        return self.payments.all_transactions(page=page, page_size=page_size, search=search)

    # ---------- settings & audit ----------

    def all_settings(self) -> dict[str, dict]:
        return self.settings.all_settings()

    def update_setting(self, admin: User, key: str, value: str) -> None:
        self.settings.set_value(key, value)
        self.audit.log(
            user_id=admin.id,
            action="setting_updated",
            entity_type="system_setting",
            entity_id=key,
            metadata_json={"value": value},
        )
        self.db.flush()

    def audit_logs(self, page: int, page_size: int, action: str | None = None):
        return self.audit.recent(page=page, page_size=page_size, action=action)
