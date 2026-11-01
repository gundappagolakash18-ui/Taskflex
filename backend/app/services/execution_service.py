"""Proof-of-execution photos and the incidental expense ledger.

Photos are decoded, GPS-checked against the task location, re-encoded to WebP
(which strips EXIF — including the raw GPS tags) and written to private
storage. The validated fix and capture time are kept on the proof row so the
evidence remains auditable without leaking metadata.

Expense approvals are decisions, not movements of money: approved rows are
reimbursed in full to the worker's wallet during completion settlement.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    ConflictException,
    ErrorCode,
    ForbiddenException,
    InvalidTransitionException,
    NotFoundException,
)
from app.core.logging import get_logger
from app.matching.geo import haversine_km
from app.models import (
    ExpenseCategory,
    ExpenseStatus,
    NotificationType,
    Task,
    TaskExecutionProof,
    TaskExpense,
    TaskStatus,
    User,
    UserRole,
)
from app.notifications.dispatcher import notify_users_sync
from app.storage import get_storage

logger = get_logger("taskflex.execution")

PROOF_STATES = {TaskStatus.IN_PROGRESS.value, TaskStatus.COMPLETION_REQUESTED.value}
EXPENSE_STATES = {
    TaskStatus.WORKER_ON_THE_WAY.value,
    TaskStatus.ARRIVED_AT_LOCATION.value,
    TaskStatus.IN_PROGRESS.value,
    TaskStatus.COMPLETION_REQUESTED.value,
}
CLOSED_STATES = {
    TaskStatus.COMPLETED.value,
    TaskStatus.CANCELLED.value,
    TaskStatus.DISPUTED.value,
    TaskStatus.EMERGENCY_ALERT.value,
}

IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MIME_ALIASES = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg"}
PROOF_MAX_BYTES = settings.max_upload_size_mb * 1024 * 1024
PROOF_MAX_PIXELS = 40_000_000
PROOF_MAX_DIMENSIONS = (1920, 1080)
PROOF_WEBP_QUALITY = 82
RECEIPT_MIME_TYPES = IMAGE_MIME_TYPES | {"application/pdf"}


def sniff_mime(content: bytes) -> str | None:
    """Identify the real file type from magic bytes — never trust the client."""
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def _canonical_mime(value: str | None) -> str | None:
    if not value:
        return None
    base = value.split(";")[0].strip().lower()
    return MIME_ALIASES.get(base, base)


def _rational(value) -> float:
    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        return float(numerator) / float(denominator) if denominator else 0.0
    return float(value)


def _gps_coordinate(parts, ref) -> float | None:
    if not parts or len(parts) != 3:
        return None
    try:
        degrees, minutes, seconds = (_rational(part) for part in parts)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    coordinate = degrees + minutes / 60.0 + seconds / 3600.0
    if str(ref or "").upper() in {"S", "W"}:
        coordinate = -coordinate
    return coordinate


class ExecutionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    def assert_can_view_evidence(self, task: Task, user: User) -> None:
        if user.role == UserRole.ADMIN.value:
            return
        if task.customer_id == user.id:
            return
        if task.assigned_worker_id == user.id:
            return
        raise ForbiddenException("Execution evidence is private to the task participants.")

    def _assert_assigned_worker(self, task: Task, user: User) -> None:
        if task.assigned_worker_id != user.id:
            raise ForbiddenException("Only the assigned worker can add execution evidence.")

    # ------------------------------------------------------------------
    # Proof of execution
    # ------------------------------------------------------------------

    def add_proof(
        self,
        task: Task,
        worker: User,
        *,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> TaskExecutionProof:
        self._assert_assigned_worker(task, worker)
        if task.status not in PROOF_STATES:
            raise InvalidTransitionException(
                "Proof photos can only be uploaded once the task is IN_PROGRESS."
            )
        if not content:
            raise AppException("The uploaded photo is empty.", code=ErrorCode.VALIDATION_ERROR)
        if len(content) > PROOF_MAX_BYTES:
            raise AppException(
                f"Photo exceeds the {settings.max_upload_size_mb} MB limit.",
                code=ErrorCode.FILE_TOO_LARGE,
                status_code=413,
            )
        existing = int(
            self.db.scalar(
                select(func.count())
                .select_from(TaskExecutionProof)
                .where(TaskExecutionProof.task_id == task.id)
            )
            or 0
        )
        if existing >= settings.proof_max_per_task:
            raise AppException(
                f"At most {settings.proof_max_per_task} proof photos are allowed per task.",
                code=ErrorCode.CONFLICT,
                status_code=409,
            )

        webp, latitude, longitude, captured_at = self._normalize_photo(content, content_type)
        if latitude is None or longitude is None:
            raise AppException(
                "The photo has no GPS metadata. Enable location tagging on your camera "
                "and take the photo again at the task location.",
                code=ErrorCode.PROOF_LOCATION_MISSING,
                status_code=422,
            )
        self._assert_location(task, latitude, longitude)

        storage = get_storage()
        stored = storage.save(
            webp,
            f"{Path(filename or 'proof').stem[:80]}.webp",
            "image/webp",
            folder=f"proofs/{task.id}",
        )
        proof = TaskExecutionProof(
            task_id=task.id,
            worker_id=worker.id,
            file_key=stored["path"],
            captured_at=captured_at,
            latitude=latitude,
            longitude=longitude,
            location_source="EXIF",
        )
        self.db.add(proof)
        try:
            self.db.flush()
        except Exception:
            storage.delete(stored["path"])
            raise
        self.db.refresh(proof)
        logger.info(
            "proof_uploaded task=%s worker=%s proof=%s distance_check=ok",
            task.id, worker.id, proof.id,
        )
        return proof

    def _assert_location(self, task: Task, latitude: float, longitude: float) -> None:
        if task.latitude is None or task.longitude is None:
            return
        distance_m = haversine_km(task.latitude, task.longitude, latitude, longitude) * 1000.0
        limit = settings.proof_max_distance_m
        if distance_m > limit:
            raise AppException(
                f"Proof photo was taken about {distance_m:.0f} m from the task location "
                f"(limit {limit} m). Take the photo at the work site.",
                code=ErrorCode.PROOF_OUT_OF_RANGE,
                status_code=422,
                details={
                    "distance_m": round(distance_m, 1),
                    "max_distance_m": limit,
                },
            )

    def _normalize_photo(
        self, content: bytes, declared_type: str
    ) -> tuple[bytes, float | None, float | None, datetime | None]:
        actual = sniff_mime(content)
        if actual not in IMAGE_MIME_TYPES:
            raise AppException(
                "Only JPEG, PNG or WebP photos are accepted.",
                code=ErrorCode.FILE_TYPE_NOT_ALLOWED,
                status_code=415,
            )
        declared = _canonical_mime(declared_type)
        if declared in IMAGE_MIME_TYPES and declared != actual:
            raise AppException(
                "The file content does not match its declared image type.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )

        try:
            with Image.open(io.BytesIO(content)) as image:
                if image.width * image.height > PROOF_MAX_PIXELS:
                    raise AppException(
                        "Photo resolution is too large.",
                        code=ErrorCode.VALIDATION_ERROR,
                        status_code=422,
                    )
                exif = image.getexif()
                latitude, longitude = self._exif_gps(exif)
                captured_at = self._exif_captured_at(exif)
                normalized = ImageOps.exif_transpose(image)
                if normalized.mode != "RGB":
                    normalized = normalized.convert("RGB")
                normalized.thumbnail(PROOF_MAX_DIMENSIONS, Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                normalized.save(buffer, format="WEBP", quality=PROOF_WEBP_QUALITY, method=6)
        except AppException:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise AppException(
                "That file could not be read as a photo.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            ) from exc

        encoded = buffer.getvalue()
        if not encoded:
            raise AppException(
                "The photo could not be processed.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
        return encoded, latitude, longitude, captured_at

    @staticmethod
    def _exif_gps(exif) -> tuple[float | None, float | None]:
        try:
            gps = exif.get_ifd(0x8825)
        except Exception:
            return None, None
        if not gps:
            return None, None
        latitude = _gps_coordinate(gps.get(2), gps.get(1))
        longitude = _gps_coordinate(gps.get(4), gps.get(3))
        if latitude is None or longitude is None:
            return None, None
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            return None, None
        return round(latitude, 7), round(longitude, 7)

    @staticmethod
    def _exif_captured_at(exif) -> datetime | None:
        raw = None
        try:
            raw = exif.get_ifd(0x8769).get(36867)
        except Exception:
            raw = None
        if not raw:
            raw = exif.get(36867)
        if not raw:
            return None
        value = str(raw).replace("\x00", "").strip()
        try:
            parsed = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            return None
        # EXIF timestamps carry no zone; store them as reported.
        return parsed.replace(tzinfo=timezone.utc)

    def list_proofs(self, task: Task) -> list[TaskExecutionProof]:
        return list(
            self.db.scalars(
                select(TaskExecutionProof)
                .where(TaskExecutionProof.task_id == task.id)
                .order_by(TaskExecutionProof.created_at)
            )
        )

    def get_proof_or_404(self, task: Task, proof_id: str) -> TaskExecutionProof:
        proof = self.db.scalar(
            select(TaskExecutionProof).where(
                TaskExecutionProof.id == proof_id,
                TaskExecutionProof.task_id == task.id,
            )
        )
        if proof is None:
            raise NotFoundException("Proof photo not found.")
        return proof

    def read_proof(self, task: Task, proof_id: str) -> tuple[bytes, str, str]:
        proof = self.get_proof_or_404(task, proof_id)
        content = get_storage().read(proof.file_key)
        return content, "image/webp", f"proof-{proof.id[:8]}.webp"

    # ------------------------------------------------------------------
    # Incidental expenses
    # ------------------------------------------------------------------

    def add_expense(
        self,
        task: Task,
        worker: User,
        *,
        amount,
        category: str,
        description: str,
        receipt: tuple[bytes, str, str] | None = None,
    ) -> TaskExpense:
        self._assert_assigned_worker(task, worker)
        if task.status not in EXPENSE_STATES:
            raise InvalidTransitionException(
                "Expenses can only be logged while the task is active."
            )

        amount_value = self._parse_amount(amount)
        category_value = (category or "").strip().upper()
        if category_value not in {item.value for item in ExpenseCategory}:
            raise AppException(
                "Unknown expense category.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
        description_value = (description or "").strip()
        if len(description_value) < 5:
            raise AppException(
                "Describe the expense in at least 5 characters.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
        if len(description_value) > 500:
            raise AppException(
                "Expense description is too long.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
        pending = int(
            self.db.scalar(
                select(func.count())
                .select_from(TaskExpense)
                .where(TaskExpense.task_id == task.id, TaskExpense.status != ExpenseStatus.REJECTED.value)
            )
            or 0
        )
        if pending >= settings.expense_max_per_task:
            raise AppException(
                f"At most {settings.expense_max_per_task} open expenses are allowed per task.",
                code=ErrorCode.EXPENSE_LIMIT_EXCEEDED,
                status_code=409,
            )

        receipt_key = None
        receipt_mime = None
        if receipt is not None:
            content, filename, declared_type = receipt
            receipt_key, receipt_mime = self._store_receipt(task, content, filename, declared_type)

        expense = TaskExpense(
            task_id=task.id,
            worker_id=worker.id,
            amount=amount_value,
            category=category_value,
            description=description_value,
            receipt_url=receipt_key,
            receipt_mime_type=receipt_mime,
            status=ExpenseStatus.PENDING_APPROVAL.value,
        )
        self.db.add(expense)
        try:
            self.db.flush()
        except Exception:
            if receipt_key:
                get_storage().delete(receipt_key)
            raise
        self.db.refresh(expense)

        notify_users_sync(
            [task.customer_id],
            notification_type=NotificationType.EXPENSE_REQUESTED,
            title="Expense approval needed",
            body=(
                f"Your worker paid ₹{float(amount_value):.0f} for "
                f"{category_value.replace('_', ' ').lower()} on '{task.title}'."
            ),
            data={
                "task_id": task.id,
                "expense_id": expense.id,
                "amount": float(amount_value),
                "category": category_value,
            },
            link=f"/app/tasks/{task.id}",
            db=self.db,
        )
        logger.info(
            "expense_logged task=%s worker=%s expense=%s amount=%.2f category=%s",
            task.id, worker.id, expense.id, float(amount_value), category_value,
        )
        return expense

    def _parse_amount(self, amount) -> Decimal:
        try:
            value = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AppException(
                "Enter a valid expense amount.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            ) from exc
        if not value.is_finite() or value <= 0:
            raise AppException(
                "Expense amount must be greater than zero.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
        value = value.quantize(Decimal("0.01"))
        if value > Decimal(str(settings.expense_max_amount)):
            raise AppException(
                f"A single expense cannot exceed ₹{settings.expense_max_amount:.0f}.",
                code=ErrorCode.EXPENSE_LIMIT_EXCEEDED,
                status_code=422,
            )
        return value

    def _store_receipt(
        self, task: Task, content: bytes, filename: str, declared_type: str
    ) -> tuple[str, str]:
        if not content:
            raise AppException("The uploaded receipt is empty.", code=ErrorCode.VALIDATION_ERROR)
        if len(content) > settings.max_upload_size_mb * 1024 * 1024:
            raise AppException(
                f"Receipt exceeds the {settings.max_upload_size_mb} MB limit.",
                code=ErrorCode.FILE_TOO_LARGE,
                status_code=413,
            )
        actual = sniff_mime(content)
        if actual not in RECEIPT_MIME_TYPES:
            raise AppException(
                "Receipts must be a JPEG, PNG, WebP image or a PDF.",
                code=ErrorCode.FILE_TYPE_NOT_ALLOWED,
                status_code=415,
            )
        declared = _canonical_mime(declared_type)
        if declared in RECEIPT_MIME_TYPES and declared != actual:
            raise AppException(
                "The receipt content does not match its declared type.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
        stored = get_storage().save(
            content,
            filename or f"receipt-{Path(task.id).name}",
            actual,
            folder=f"expenses/{task.id}",
        )
        return stored["path"], actual

    def list_expenses(self, task: Task) -> list[TaskExpense]:
        return list(
            self.db.scalars(
                select(TaskExpense)
                .where(TaskExpense.task_id == task.id)
                .order_by(TaskExpense.created_at)
            )
        )

    def get_expense_or_404(self, task: Task, expense_id: str) -> TaskExpense:
        expense = self.db.scalar(
            select(TaskExpense).where(
                TaskExpense.id == expense_id,
                TaskExpense.task_id == task.id,
            )
        )
        if expense is None:
            raise NotFoundException("Expense not found.")
        return expense

    def read_receipt(self, task: Task, expense_id: str) -> tuple[bytes, str, str]:
        expense = self.get_expense_or_404(task, expense_id)
        if not expense.receipt_url:
            raise NotFoundException("This expense has no receipt attached.")
        content = get_storage().read(expense.receipt_url)
        extension = "pdf" if expense.receipt_mime_type == "application/pdf" else "img"
        return content, expense.receipt_mime_type or "application/octet-stream", f"receipt-{expense.id[:8]}.{extension}"

    def decide_expense(
        self,
        task: Task,
        customer: User,
        expense_id: str,
        *,
        approve: bool,
        note: str | None = None,
    ) -> TaskExpense:
        if task.customer_id != customer.id:
            raise ForbiddenException("Only the task's customer can decide on expenses.")
        if task.status in CLOSED_STATES:
            raise ConflictException("The task is closed — expenses can no longer be decided.")

        expense = self.get_expense_or_404(task, expense_id)
        if expense.status != ExpenseStatus.PENDING_APPROVAL.value:
            raise ConflictException(
                f"This expense was already {expense.status.lower().replace('_', ' ')}."
            )

        expense.status = (
            ExpenseStatus.APPROVED.value if approve else ExpenseStatus.REJECTED.value
        )
        expense.decided_by_id = customer.id
        expense.decided_at = datetime.now(timezone.utc)
        expense.decision_note = (note or "").strip()[:500] or None
        self.db.flush()
        self.db.refresh(expense)

        if task.assigned_worker_id:
            amount = float(expense.amount)
            notify_users_sync(
                [task.assigned_worker_id],
                notification_type=(
                    NotificationType.EXPENSE_APPROVED
                    if approve
                    else NotificationType.EXPENSE_REJECTED
                ),
                title=(
                    f"Expense approved: ₹{amount:.0f}"
                    if approve
                    else f"Expense rejected: ₹{amount:.0f}"
                ),
                body=(
                    f"'{expense.description[:120]}' will be added to your payout at completion."
                    if approve
                    else f"'{expense.description[:120]}' was not approved by the customer."
                ),
                data={
                    "task_id": task.id,
                    "expense_id": expense.id,
                    "amount": amount,
                    "category": expense.category,
                },
                link=f"/worker/tasks/{task.id}",
                db=self.db,
            )
        logger.info(
            "expense_decided task=%s expense=%s status=%s by=%s",
            task.id, expense.id, expense.status, customer.id,
        )
        return expense

    def expense_totals(self, task: Task) -> dict:
        expenses = self.list_expenses(task)
        by_status: dict[str, list[float]] = {}
        for expense in expenses:
            by_status.setdefault(expense.status, []).append(float(expense.amount))
        approved = round(sum(by_status.get(ExpenseStatus.APPROVED.value, [])), 2)
        reimbursed = round(sum(by_status.get(ExpenseStatus.REIMBURSED.value, [])), 2)
        return {
            "count": len(expenses),
            "pending_count": len(by_status.get(ExpenseStatus.PENDING_APPROVAL.value, [])),
            "pending_total": round(sum(by_status.get(ExpenseStatus.PENDING_APPROVAL.value, [])), 2),
            "approved_total": approved,
            "rejected_total": round(sum(by_status.get(ExpenseStatus.REJECTED.value, [])), 2),
            "reimbursed_total": reimbursed,
            "worker_reimbursement_total": round(approved + reimbursed, 2),
        }

    def approved_expenses(self, task: Task) -> list[TaskExpense]:
        return list(
            self.db.scalars(
                select(TaskExpense).where(
                    TaskExpense.task_id == task.id,
                    TaskExpense.status == ExpenseStatus.APPROVED.value,
                )
            )
        )

    def close_pending_expenses(self, task: Task) -> int:
        """Completion is the settlement point: unreviewed claims are closed so
        they do not sit in limbo once the task can no longer be decided."""
        pending = list(
            self.db.scalars(
                select(TaskExpense).where(
                    TaskExpense.task_id == task.id,
                    TaskExpense.status == ExpenseStatus.PENDING_APPROVAL.value,
                )
            )
        )
        if not pending:
            return 0
        now = datetime.now(timezone.utc)
        for expense in pending:
            expense.status = ExpenseStatus.REJECTED.value
            expense.decided_at = now
            expense.decision_note = (
                "Closed automatically when the task completed before review."
            )
        self.db.flush()
        if task.assigned_worker_id:
            notify_users_sync(
                [task.assigned_worker_id],
                notification_type=NotificationType.EXPENSE_REJECTED,
                title="Unreviewed expenses closed",
                body=(
                    f"{len(pending)} expense claim(s) were closed without reimbursement "
                    f"because the task completed before the customer reviewed them."
                ),
                data={
                    "task_id": task.id,
                    "expense_ids": [e.id for e in pending],
                },
                link=f"/worker/tasks/{task.id}",
                db=self.db,
            )
        logger.info("expenses_auto_closed task=%s count=%d", task.id, len(pending))
        return len(pending)
