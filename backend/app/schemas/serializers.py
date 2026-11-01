"""Convert ORM objects into API-facing dicts. Keeps serialization rules in one place
so sensitive fields (emails, document paths, hashes) never leak into responses."""

from app.models import (
    Conversation,
    Message,
    Payment,
    Rating,
    Task,
    TaskOffer,
    Transaction,
    User,
    VerificationDocument,
    WorkerProfile,
)
from app.models.enums import RatingDirection
from app.schemas.task import WorkerBrief


def worker_brief(user: User | None) -> WorkerBrief | None:
    if not user:
        return None
    profile: WorkerProfile | None = user.worker_profile
    return WorkerBrief(
        id=user.id,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        city=user.city,
        is_verified=bool(profile and profile.is_verified),
        rating_average=round(profile.rating_average, 2) if profile else 0.0,
        rating_count=profile.rating_count if profile else 0,
        completed_tasks_count=profile.completed_tasks_count if profile else 0,
    )


def serialize_task(task: Task, *, viewer_id: str | None = None, include_customer: bool = True) -> dict:
    worker_rel = None
    if task.assigned_worker_id:
        worker_rel = next((a.worker for a in task.assignments if a.worker_id == task.assigned_worker_id), None)

    my_offer_status = None
    if viewer_id:
        for offer in task.offers:
            if offer.worker_id == viewer_id:
                my_offer_status = offer.status
                break

    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "task_type": task.task_type,
        "status": task.status,
        "urgency": task.urgency,
        "scheduled_date": task.scheduled_date.isoformat() if task.scheduled_date else None,
        "scheduled_time": task.scheduled_time.strftime("%H:%M") if task.scheduled_time else None,
        "estimated_duration_minutes": task.estimated_duration_minutes,
        "latitude": task.latitude,
        "longitude": task.longitude,
        "address_text": task.address_text,
        "area_name": task.area_name,
        "city": task.city,
        "budget": float(task.budget),
        "currency": task.currency,
        "special_requirements": task.special_requirements,
        "parsed_by_ai": task.parsed_by_ai,
        "ai_confidence": task.ai_confidence,
        "assigned_worker_id": task.assigned_worker_id,
        "payment_status": task.payment_status,
        "commission_amount": float(task.commission_amount),
        "worker_payout_amount": float(task.worker_payout_amount),
        "worker_completed_at": task.worker_completed_at.isoformat() if task.worker_completed_at else None,
        "customer_confirmed_at": task.customer_confirmed_at.isoformat() if task.customer_confirmed_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "cancelled_at": task.cancelled_at.isoformat() if task.cancelled_at else None,
        "cancellation_reason": task.cancellation_reason,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "customer": worker_brief(task.customer).model_dump() if include_customer else None,
        "worker": worker_brief(worker_rel).model_dump() if worker_rel else None,
        "requirements": [{"skill_name": r.skill_name, "is_required": r.is_required} for r in task.requirements],
        "my_offer_status": my_offer_status,
    }


def serialize_worker_public(profile: WorkerProfile) -> dict:
    user = profile.user
    return {
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
        "rating_average": round(profile.rating_average, 2),
        "rating_count": profile.rating_count,
        "completed_tasks_count": profile.completed_tasks_count,
        "skills": profile.skills_slugs(),
    }


def serialize_worker_private(profile: WorkerProfile) -> dict:
    data = serialize_worker_public(profile)
    data.update(
        {
            "working_radius_km": profile.working_radius_km,
            "max_concurrent_tasks": profile.max_concurrent_tasks,
            "cancelled_tasks_count": profile.cancelled_tasks_count,
            "total_earnings": round(profile.total_earnings, 2),
            "verification_status": profile.verification_status,
            "availability": [
                {
                    "day_of_week": a.day_of_week,
                    "start_time": a.start_time.strftime("%H:%M"),
                    "end_time": a.end_time.strftime("%H:%M"),
                    "is_available": a.is_available,
                }
                for a in sorted(profile.availability, key=lambda x: x.day_of_week)
            ],
        }
    )
    return data


def serialize_offer(offer: TaskOffer, task: Task | None = None) -> dict:
    data = {
        "id": offer.id,
        "task_id": offer.task_id,
        "worker_id": offer.worker_id,
        "status": offer.status,
        "match_score": round(offer.match_score, 4),
        "expires_at": offer.expires_at.isoformat() if offer.expires_at else None,
        "created_at": offer.created_at.isoformat(),
    }
    if task is not None:
        data["task"] = serialize_task(task, viewer_id=offer.worker_id, include_customer=False)
    return data


def serialize_rating(rating: Rating, rater: User | None = None) -> dict:
    return {
        "id": rating.id,
        "task_id": rating.task_id,
        "rater_id": rating.rater_id,
        "ratee_id": rating.ratee_id,
        "direction": rating.direction,
        "score": rating.score,
        "comment": rating.comment,
        "created_at": rating.created_at.isoformat(),
        "rater_name": rater.full_name if rater else None,
        "rater_avatar": rater.avatar_url if rater else None,
    }


def serialize_notification(n) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "title": n.title,
        "body": n.body,
        "data": n.data or {},
        "link": n.link,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat(),
    }


def serialize_transaction(t: Transaction) -> dict:
    return {
        "id": t.id,
        "type": t.type,
        "amount": float(t.amount),
        "balance_after": float(t.balance_after),
        "currency": t.currency,
        "reference_type": t.reference_type,
        "reference_id": t.reference_id,
        "description": t.description,
        "created_at": t.created_at.isoformat(),
    }


def serialize_payment(p: Payment) -> dict:
    return {
        "id": p.id,
        "task_id": p.task_id,
        "provider": p.provider,
        "amount": float(p.amount),
        "currency": p.currency,
        "commission_amount": float(p.commission_amount),
        "worker_payout_amount": float(p.worker_payout_amount),
        "status": p.status,
        "created_at": p.created_at.isoformat(),
        "captured_at": p.captured_at.isoformat() if p.captured_at else None,
    }


def serialize_conversation(conv: Conversation, viewer: User) -> dict:
    counterpart_id = conv.worker_id if viewer.id == conv.customer_id else conv.customer_id
    last_message_body = conv.messages[-1].body if conv.messages else None
    return {
        "id": conv.id,
        "task_id": conv.task_id,
        "task_title": None,  # filled by messaging service (needs Task)
        "counterpart": None,  # filled by messaging service (needs User query)
        "counterpart_id": counterpart_id,
        "last_message": last_message_body,
        "last_message_at": (conv.last_message_at.isoformat() if conv.last_message_at else None),
        "unread_count": sum(1 for m in conv.messages if not m.is_read and m.sender_id != viewer.id),
        "created_at": conv.created_at.isoformat(),
    }


def serialize_message(m: Message) -> dict:
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "sender_id": m.sender_id,
        "body": m.body,
        "is_read": m.is_read,
        "created_at": m.created_at.isoformat(),
    }


def serialize_document(doc: VerificationDocument) -> dict:
    return {
        "id": doc.id,
        "document_type": doc.document_type,
        "file_name": doc.file_name,
        "mime_type": doc.mime_type,
        "file_size": doc.file_size,
        "status": doc.status,
        "rejection_reason": doc.rejection_reason,
        "created_at": doc.created_at.isoformat(),
    }
