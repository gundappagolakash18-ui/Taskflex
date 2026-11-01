"""Shared model->dict serializers for API responses.

Kept explicit (rather than pydantic from_attributes) so we control exactly
which user fields are exposed — never email/phone of other users.
"""

from app.core.config import settings
from app.models import Task, TaskExecutionProof, TaskExpense, TaskSosAlert, User, WorkerProfile
from app.schemas.auth import AuthUser


def serialize_sos_alert(alert: TaskSosAlert) -> dict:
    return {
        "id": alert.id,
        "task_id": alert.task_id,
        "status": alert.status,
        "raised_by_id": alert.raised_by_id,
        "raised_by_role": alert.raised_by_role,
        "previous_status": alert.previous_status,
        "latitude": alert.latitude,
        "longitude": alert.longitude,
        "message": alert.message,
        "location_history": alert.location_history or [],
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        "resolution_note": alert.resolution_note,
    }


def serialize_execution_proof(proof: TaskExecutionProof) -> dict:
    return {
        "id": proof.id,
        "task_id": proof.task_id,
        "worker_id": proof.worker_id,
        "captured_at": proof.captured_at.isoformat() if proof.captured_at else None,
        "latitude": proof.latitude,
        "longitude": proof.longitude,
        "location_source": proof.location_source,
        "created_at": proof.created_at.isoformat() if proof.created_at else None,
        "file_url": (
            f"{settings.api_v1_prefix}/tasks/{proof.task_id}/proofs/{proof.id}/file"
        ),
    }


def serialize_task_expense(expense: TaskExpense) -> dict:
    return {
        "id": expense.id,
        "task_id": expense.task_id,
        "worker_id": expense.worker_id,
        "amount": float(expense.amount or 0),
        "category": expense.category,
        "description": expense.description,
        "status": expense.status,
        "receipt_available": bool(expense.receipt_url),
        "receipt_url": (
            f"{settings.api_v1_prefix}/tasks/{expense.task_id}/expenses/{expense.id}/receipt"
            if expense.receipt_url
            else None
        ),
        "decided_by_id": expense.decided_by_id,
        "decided_at": expense.decided_at.isoformat() if expense.decided_at else None,
        "decision_note": expense.decision_note,
        "created_at": expense.created_at.isoformat() if expense.created_at else None,
    }


def serialize_auth_user(user: User) -> dict:
    """The signed-in user's own profile — phone/email are safe here because the
    caller is the owner. Never use this for another user's payload."""
    return AuthUser(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        role=user.role,
        avatar_url=user.avatar_url,
        city=user.city,
        is_email_verified=user.is_email_verified,
        created_at=user.created_at.isoformat() if user.created_at else "",
    ).model_dump()


def public_user(user: User | None) -> dict | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
        "city": user.city,
        "role": user.role,
    }


def worker_brief(user: User | None, profile: WorkerProfile | None = None) -> dict | None:
    if user is None:
        return None
    brief = public_user(user)
    brief.update(
        {
            "is_verified": bool(profile.is_verified) if profile else False,
            "rating_average": float(profile.rating_average or 0) if profile else 0.0,
            "rating_count": int(profile.rating_count or 0) if profile else 0,
            "completed_tasks_count": int(profile.completed_tasks_count or 0) if profile else 0,
            "tier": profile.tier if profile else None,
        }
    )
    return brief


def serialize_task(task: Task, *, worker_profile: WorkerProfile | None = None,
                   my_offer_status: str | None = None, viewer: User | None = None) -> dict:
    data = {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "task_type": task.task_type,
        "status": task.status,
        "urgency": task.urgency,
        "scheduled_date": task.scheduled_date.isoformat() if task.scheduled_date else None,
        "scheduled_time": task.scheduled_time.isoformat() if task.scheduled_time else None,
        "estimated_duration_minutes": task.estimated_duration_minutes,
        "latitude": task.latitude,
        "longitude": task.longitude,
        "address_text": task.address_text,
        "area_name": task.area_name,
        "city": task.city,
        "budget": float(task.budget or 0),
        "currency": task.currency,
        "special_requirements": task.special_requirements,
        "parsed_by_ai": task.parsed_by_ai,
        "ai_confidence": float(task.ai_confidence or 0),
        "assigned_worker_id": task.assigned_worker_id,
        "payment_status": task.payment_status,
        "commission_amount": float(task.commission_amount or 0),
        "worker_payout_amount": float(task.worker_payout_amount or 0),
        "tip_amount": float(task.tip_amount or 0),
        "is_scheduled": bool(task.is_scheduled),
        "scheduled_for": task.scheduled_for.isoformat() if task.scheduled_for else None,
        "worker_confirmed_readiness": bool(task.worker_confirmed_readiness),
        "is_round_trip": bool(task.is_round_trip),
        "return_otp_required": bool(task.return_otp_hash),
        "return_otp_verified_at": task.return_otp_verified_at.isoformat() if task.return_otp_verified_at else None,
        "bids_close_at": task.bids_close_at.isoformat() if task.bids_close_at else None,
        "worker_completed_at": task.worker_completed_at.isoformat() if task.worker_completed_at else None,
        "customer_confirmed_at": task.customer_confirmed_at.isoformat() if task.customer_confirmed_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "cancelled_at": task.cancelled_at.isoformat() if task.cancelled_at else None,
        "cancellation_reason": task.cancellation_reason,
        "confirmed_at": task.confirmed_at.isoformat() if task.confirmed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "customer": public_user(task.customer),
        "worker": worker_brief(task.assigned_worker, worker_profile),
        "requirements": [
            {"skill_name": r.skill_name, "is_required": r.is_required} for r in (task.requirements or [])
        ],
        "my_offer_status": my_offer_status,
        "start_otp_required": bool(task.start_otp_hash),
        "completion_otp_required": bool(task.completion_otp_hash),
    }
    # Handshake display codes are readable ONLY by the task's own customer.
    if viewer is not None and viewer.id == task.customer_id:
        data["start_otp_display"] = task.start_otp_display
        data["completion_otp_display"] = task.completion_otp_display
        data["start_otp_locked"] = bool(task.start_otp_locked_at)
        data["completion_otp_locked"] = bool(task.completion_otp_locked_at)
        if task.is_round_trip:
            data["return_otp_display"] = task.return_otp_display
            data["return_otp_locked"] = bool(task.return_otp_locked_at)
    return data


def serialize_worker(profile: WorkerProfile, *, private: bool = False) -> dict:
    user = profile.user
    data = {
        "id": user.id,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
        "city": profile.city or user.city,
        "area": profile.area,
        "bio": profile.bio,
        "experience_years": profile.experience_years,
        "languages": profile.languages,
        "is_online": profile.is_online,
        "is_verified": profile.is_verified,
        "rating_average": float(profile.rating_average or 0),
        "rating_count": profile.rating_count,
        "completed_tasks_count": profile.completed_tasks_count,
        "tier": profile.tier,
        "skills": [ws.skill.name for ws in (profile.skills or []) if ws.skill],
    }
    if private:
        data.update(
            {
                "working_radius_km": profile.working_radius_km,
                "max_concurrent_tasks": profile.max_concurrent_tasks,
                "cancelled_tasks_count": profile.cancelled_tasks_count,
                "total_earnings": float(profile.total_earnings or 0),
                "verification_status": profile.verification_status,
                "commission_rate": float(profile.commission_rate or 0),
                "upi_id": profile.upi_id,
                "queued_task_id": profile.queued_task_id,
                "wrapping_up_soon": bool(profile.wrapping_up_soon),
                "missed_offers": int(profile.missed_offers or 0),
                "availability": [
                    {
                        "day_of_week": a.day_of_week,
                        "start_time": a.start_time.isoformat(timespec="minutes") if a.start_time else "08:00",
                        "end_time": a.end_time.isoformat(timespec="minutes") if a.end_time else "20:00",
                        "is_available": a.is_available,
                    }
                    for a in (profile.availability or [])
                ],
            }
        )
    return data


def serialize_status_history(entries: list) -> list[dict]:
    return [
        {
            "from_status": e.from_status,
            "to_status": e.to_status,
            "note": e.note,
            "changed_by_role": e.changed_by_role,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]
