"""Public live-tracking share links.

The customer mints an opaque token for a task in flight; anyone holding the
token can watch the sanitized tracking snapshot without signing in. Tokens can
be rotated or revoked, expire automatically, and never unlock the task API.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ShareLinkExpiredException,
)
from app.core.timeutils import as_aware, utcnow
from app.models import Task, User, WorkerProfile
from app.models.enums import TaskStatus
from app.services.messaging_service import TASK_CLOSED_STATUSES
from app.tracking.service import tracking_snapshot

SHAREABLE_STATUSES = {
    TaskStatus.ACCEPTED.value,
    TaskStatus.WORKER_ON_THE_WAY.value,
    TaskStatus.ARRIVED_AT_LOCATION.value,
    TaskStatus.IN_PROGRESS.value,
    TaskStatus.COMPLETION_REQUESTED.value,
    TaskStatus.EMERGENCY_ALERT.value,
}

# Fields from the telemetry payload that are safe for an anonymous viewer.
PUBLIC_TELEMETRY_FIELDS = (
    "latitude",
    "longitude",
    "heading",
    "speed_kmph",
    "remaining_km",
    "eta_minutes",
    "recorded_at",
)


class ShareService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Owner side
    # ------------------------------------------------------------------

    def create_link(
        self,
        task: Task,
        requester: User,
        *,
        expires_in_hours: int | None = None,
        rotate: bool = False,
    ) -> dict:
        if task.customer_id != requester.id:
            raise ForbiddenException("Only the task owner can create a tracking link.")
        if task.status not in SHAREABLE_STATUSES:
            raise ConflictException(
                "A live tracking link becomes available once a worker accepts the task."
            )

        hours = expires_in_hours or settings.tracking_share_default_hours
        hours = max(1, min(int(hours), settings.tracking_share_max_hours))
        now = utcnow()

        existing_valid = (
            task.share_token is not None
            and task.share_token_expires_at is not None
            and as_aware(task.share_token_expires_at) > now
        )
        if rotate or not existing_valid:
            task.share_token = secrets.token_urlsafe(32)[:64]
            task.share_token_expires_at = now + timedelta(hours=hours)
            self.db.flush()
        return self.link_payload(task)

    def active_link(self, task: Task, requester: User) -> dict | None:
        if task.customer_id != requester.id:
            raise ForbiddenException("Only the task owner can view its tracking link.")
        if not task.share_token or not task.share_token_expires_at:
            return None
        if as_aware(task.share_token_expires_at) <= utcnow():
            return None
        return self.link_payload(task)

    def revoke_link(self, task: Task, requester: User) -> bool:
        if task.customer_id != requester.id:
            raise ForbiddenException("Only the task owner can revoke its tracking link.")
        had_link = bool(task.share_token)
        task.share_token = None
        task.share_token_expires_at = None
        self.db.flush()
        return had_link

    def link_payload(self, task: Task) -> dict:
        base = settings.frontend_origin.rstrip("/")
        path = f"/track/{task.share_token}"
        return {
            "token": task.share_token,
            "path": path,
            "url": f"{base}{path}",
            "expires_at": (
                task.share_token_expires_at.isoformat() if task.share_token_expires_at else None
            ),
        }

    # ------------------------------------------------------------------
    # Anonymous side
    # ------------------------------------------------------------------

    def resolve(self, token: str) -> Task:
        cleaned = (token or "").strip()
        if not cleaned or len(cleaned) > 64:
            raise NotFoundException("This tracking link is invalid or has been revoked.")
        task = self.db.scalar(select(Task).where(Task.share_token == cleaned))
        if task is None:
            raise NotFoundException("This tracking link is invalid or has been revoked.")
        if task.share_token_expires_at is None:
            raise NotFoundException("This tracking link is invalid or has been revoked.")
        if as_aware(task.share_token_expires_at) <= utcnow():
            raise ShareLinkExpiredException()
        return task

    async def public_snapshot(self, task: Task) -> dict:
        """Anonymous tracking payload: destination, route, ETA and worker
        display details only. No task id, customer identity, contact details
        or private address text."""
        snapshot = await tracking_snapshot(self.db, task)

        latest = None
        if snapshot.get("latest"):
            source = snapshot["latest"]
            latest = {field: source.get(field) for field in PUBLIC_TELEMETRY_FIELDS}

        worker_payload = None
        if task.assigned_worker_id:
            worker = task.assigned_worker
            profile = self.db.scalar(
                select(WorkerProfile).where(WorkerProfile.user_id == task.assigned_worker_id)
            )
            worker_payload = {
                "full_name": worker.full_name if worker else None,
                "avatar_url": worker.avatar_url if worker else None,
                "rating_average": float(profile.rating_average or 0) if profile else 0.0,
                "rating_count": int(profile.rating_count or 0) if profile else 0,
                "is_verified": bool(profile.is_verified) if profile else False,
            }

        return {
            "status": task.status,
            "tracking_active": bool(snapshot.get("tracking_active"))
            and task.status not in TASK_CLOSED_STATUSES,
            "destination": {
                "latitude": float(task.latitude) if task.latitude is not None else None,
                "longitude": float(task.longitude) if task.longitude is not None else None,
                "area_name": task.area_name,
                "city": task.city,
            },
            "route": snapshot.get("route"),
            "latest": latest,
            "eta_minutes": snapshot.get("eta_minutes"),
            "remaining_km": snapshot.get("remaining_km"),
            "worker": worker_payload,
            "shared_until": (
                task.share_token_expires_at.isoformat() if task.share_token_expires_at else None
            ),
        }
