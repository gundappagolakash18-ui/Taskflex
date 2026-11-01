"""Worker-side operations: profile, skills, availability, online status,
verification documents, offers and earnings."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.core.logging import get_logger
from app.models import (
    TaskStatus,
    TaskOffer,
    VerificationDocument,
    WorkerAvailability,
    WorkerProfile,
)
from app.notifications.dispatcher import notify_users_sync
from app.repositories import TaskRepository, UserRepository
from app.schemas.worker import (
    AvailabilityEntry,
    OnlineStatusUpdate,
    WorkerProfileUpdate,
)
from app.storage import get_storage, validate_upload

logger = get_logger("taskflex.workers")

ALLOWED_DOCUMENT_TYPES = {"id_card", "address_proof", "police_clearance", "other"}


class WorkerService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepository(db)
        self.tasks = TaskRepository(db)

    # ---------- profile ----------

    def get_profile(self, worker_user_id: str) -> WorkerProfile:
        profile = self.repo.get_worker_profile(worker_user_id)
        if profile is None:
            raise NotFoundException("Worker profile not found.")
        return profile

    def update_profile(self, worker_user_id: str, payload: WorkerProfileUpdate) -> WorkerProfile:
        profile = self.get_profile(worker_user_id)
        data = payload.model_dump(exclude_unset=True)

        skills = data.pop("skill_slugs", None)
        if skills is not None:
            self.set_skills(profile, skills)

        upi_id = data.pop("upi_id", None)
        if upi_id is not None:
            from app.services.wallet_service import WalletService

            WalletService(self.db).set_upi(profile.user, upi_id)

        availability = data.pop("availability", None)
        if availability is not None:
            self.set_availability(profile, [AvailabilityEntry(**entry) if isinstance(entry, dict) else entry for entry in availability])

        for field, value in data.items():
            if hasattr(profile, field):
                setattr(profile, field, value)

        profile.user.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        return profile

    def set_skills(self, profile: WorkerProfile, skill_slugs: list[str]) -> None:
        skills = self.repo.get_skills_by_slugs(skill_slugs)
        found_slugs = {s.slug for s in skills}
        unknown = [s for s in skill_slugs if s not in found_slugs]
        if unknown:
            raise NotFoundException(f"Unknown skills: {', '.join(unknown)}")
        self.repo.set_worker_skills(profile, skill_slugs)
        self.db.flush()

    def set_availability(self, profile: WorkerProfile, entries: list[AvailabilityEntry]) -> None:
        existing = self.db.scalars(
            select(WorkerAvailability).where(WorkerAvailability.worker_profile_id == profile.id)
        ).all()
        for row in existing:
            self.db.delete(row)

        seen_days: set[int] = set()
        for entry in entries:
            if entry.day_of_week in seen_days:
                raise ConflictException(f"Duplicate availability entry for weekday {entry.day_of_week}.")
            seen_days.add(entry.day_of_week)
            if entry.start_time >= entry.end_time:
                raise ConflictException(
                    f"Availability window on day {entry.day_of_week} ends before it starts."
                )
            self.db.add(
                WorkerAvailability(
                    worker_profile_id=profile.id,
                    day_of_week=entry.day_of_week,
                    start_time=entry.start_time,
                    end_time=entry.end_time,
                )
            )
        self.db.flush()

    # ---------- online toggle ----------

    def set_online_status(self, worker_user_id: str, payload: OnlineStatusUpdate) -> WorkerProfile:
        profile = self.get_profile(worker_user_id)
        profile.is_online = payload.is_online
        if payload.is_online:
            profile.last_online_at = datetime.now(timezone.utc)
        self.db.flush()
        if payload.is_online and profile.is_verified:
            from app.dispatch import dispatch_engine

            dispatch_engine.recover_open_tasks(self.db)
        logger.info(
            "worker_online_toggled",
            extra_fields={"worker_id": worker_user_id, "is_online": payload.is_online},
        )
        return profile

    # ---------- documents ----------

    def list_documents(self, worker_user_id: str) -> list[VerificationDocument]:
        profile = self.get_profile(worker_user_id)
        return list(
            self.db.scalars(
                select(VerificationDocument)
                .where(VerificationDocument.worker_profile_id == profile.id)
                .order_by(VerificationDocument.created_at.desc())
            )
        )

    def add_document(
        self,
        worker_user_id: str,
        *,
        document_type: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> VerificationDocument:
        if document_type not in ALLOWED_DOCUMENT_TYPES:
            raise NotFoundException(f"Unknown document type '{document_type}'.")
        validate_upload(filename=filename, content_type=content_type, size_bytes=len(content))

        profile = self.get_profile(worker_user_id)
        storage = get_storage()
        stored = storage.save(content, filename, content_type, folder=f"documents/{worker_user_id}")
        doc = VerificationDocument(
            worker_profile_id=profile.id,
            document_type=document_type,
            file_path=stored["path"],
            file_name=stored["file_name"],
            mime_type=stored["mime_type"],
            file_size=stored["size"],
            status="PENDING",
        )
        self.db.add(doc)
        profile.verification_status = "PENDING"
        self.db.flush()

        notify_users_sync(
            [worker_user_id],
            notification_type="SYSTEM",
            title="Document uploaded",
            body="Your verification document was received and is pending admin review.",
            db=self.db,
        )
        return doc

    def delete_document(self, worker_user_id: str, document_id: str) -> None:
        profile = self.get_profile(worker_user_id)
        doc = self.db.get(VerificationDocument, document_id)
        if doc is None or doc.worker_profile_id != profile.id:
            raise NotFoundException("Document not found.")
        if doc.status == "APPROVED":
            raise ConflictException("Approved documents cannot be removed; contact support.")
        storage = get_storage()
        try:
            storage.delete(doc.file_path)
        except Exception:
            logger.warning("could not delete stored file %s", doc.file_path)
        self.db.delete(doc)
        self.db.flush()

    # ---------- offers ----------

    def pending_offers(self, worker_user_id: str) -> list[tuple[TaskOffer, object]]:
        self.expire_stale_offers(worker_user_id)
        return self.tasks.pending_offers_for_worker(worker_user_id)

    def expire_stale_offers(self, worker_user_id: str) -> int:
        from app.services.task_service import TaskService

        service = TaskService(self.db)
        stale = self.tasks.expired_pending_offers()
        count = 0
        now = datetime.now(timezone.utc)
        for offer in stale:
            if offer.worker_id != worker_user_id:
                continue
            offer.status = "EXPIRED"
            count += 1
        if count:
            self.db.flush()
        return count

    def get_offer_for_worker(self, offer_id: str, worker_user_id: str) -> TaskOffer:
        offer = self.db.get(TaskOffer, offer_id)
        if offer is None:
            raise NotFoundException("Offer not found.")
        if offer.worker_id != worker_user_id:
            raise ForbiddenException("This offer is not yours.")
        return offer

    # ---------- earnings ----------

    def earnings_summary(self, worker_user_id: str) -> dict:
        from app.models import Task, TaskAssignment

        rows = list(
            self.db.execute(
                select(TaskAssignment, Task.status)
                .join(Task, Task.id == TaskAssignment.task_id)
                .where(TaskAssignment.worker_id == worker_user_id)
            ).all()
        )
        completed = [(a, s) for a, s in rows if s == TaskStatus.COMPLETED.value]
        active = [
            (a, s)
            for a, s in rows
            if s in (TaskStatus.ACCEPTED.value, TaskStatus.WORKER_ON_THE_WAY.value, TaskStatus.IN_PROGRESS.value)
        ]
        total_earned = sum(float(a.earnings_amount) for a, _ in completed)
        total_commission = sum(float(a.commission_amount) for a, _ in completed)
        return {
            "tasks_completed": len(completed),
            "total_earned": round(total_earned, 2),
            "total_commission": round(total_commission, 2),
            "net_earned": round(total_earned - total_commission, 2),
            "active_assignments": len(active),
        }
