import json

from fastapi import APIRouter, Depends, Form, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_worker
from app.api.serializers import serialize_task, serialize_worker
from app.db.session import get_db
from app.core.exceptions import ConflictException
from app.core.responses import success_response
from app.models import User, WorkerProfile
from app.schemas.worker import (
    AvailabilityEntry,
    DocumentOut,
    OfferOut,
    OnlineStatusUpdate,
    WorkerProfileUpdate,
)
from app.services import GamificationService, TaskService, WorkerService

router = APIRouter(prefix="/workers", tags=["workers"])


# ---------- public directory ----------


@router.get("")
def list_workers(
    search: str | None = None,
    city: str | None = None,
    skill: str | None = None,
    online_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=50),
    db: Session = Depends(get_db),
):
    from sqlalchemy import func, select

    from app.models import Skill, WorkerSkill

    stmt = (
        select(WorkerProfile)
        .join(User, User.id == WorkerProfile.user_id)
        .options(
            selectinload(WorkerProfile.user),
            selectinload(WorkerProfile.skills).selectinload(WorkerSkill.skill),
        )
        .where(WorkerProfile.is_verified.is_(True))
    )
    if online_only:
        stmt = stmt.where(WorkerProfile.is_online.is_(True))
    if city:
        stmt = stmt.where(WorkerProfile.city.ilike(f"%{city}%"))
    if search:
        stmt = stmt.where(or_(User.full_name.ilike(f"%{search}%"), WorkerProfile.bio.ilike(f"%{search}%")))
    if skill:
        slugs = [s.strip().lower() for s in skill.split(",") if s.strip()]
        if slugs:
            matched = (
                select(WorkerSkill.worker_profile_id)
                .join(Skill, Skill.id == WorkerSkill.skill_id)
                .where(Skill.slug.in_(slugs))
            )
            stmt = stmt.where(WorkerProfile.id.in_(matched))
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(WorkerProfile.rating_average.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        .scalars()
        .unique()
        .all()
    )
    return success_response(
        {"items": [serialize_worker(w) for w in rows], "total": total, "page": page, "page_size": page_size}
    )


@router.get("/scheduled-board")
def scheduled_board(
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    """Upcoming scheduled reservations open to verified workers."""
    items = TaskService(db).scheduled_board(user)
    return success_response({"items": items, "total": len(items)})


@router.get("/{worker_user_id}")
def get_worker_public(worker_user_id: str, db: Session = Depends(get_db)):
    service = WorkerService(db)
    profile = service.get_profile(worker_user_id)
    return success_response({"worker": serialize_worker(profile)})


# ---------- worker self-service ----------


@router.get("/me/profile")
def my_worker_profile(
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = WorkerService(db)
    profile = service.get_profile(user.id)
    return success_response({"worker": serialize_worker(profile, private=True)})


@router.patch("/me/profile")
def update_worker_profile(
    payload: WorkerProfileUpdate,
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = WorkerService(db)
    profile = service.update_profile(user.id, payload)
    return success_response({"worker": serialize_worker(profile, private=True)}, message="Profile updated.")


@router.put("/me/availability")
def set_availability(
    entries: list[AvailabilityEntry],
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = WorkerService(db)
    profile = service.get_profile(user.id)
    service.set_availability(profile, entries)
    return success_response({"worker": serialize_worker(profile, private=True)}, message="Availability saved.")


@router.post("/me/online")
def set_online(
    payload: OnlineStatusUpdate,
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = WorkerService(db)
    profile = service.set_online_status(user.id, payload)
    return success_response(
        {"worker": serialize_worker(profile, private=True)},
        message="You are online and visible for new offers." if payload.is_online else "You are now offline.",
    )


@router.get("/me/offers")
def my_offers(
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = WorkerService(db)
    pairs = service.pending_offers(user.id)
    items = []
    for offer, task in pairs:
        payload = OfferOut.model_validate(offer).model_dump(mode="json")
        # Candidate metadata persisted at dispatch time (preferred repeat
        # customer, back-to-back chain, earnings estimate).
        try:
            breakdown = json.loads(offer.match_breakdown) if offer.match_breakdown else {}
        except ValueError:
            breakdown = {}
        preferred = bool(breakdown.get("preferred"))
        chained = bool(breakdown.get("chained"))
        payload.update(
            {
                "distance_km": breakdown.get("distance_km"),
                "estimated_earnings": breakdown.get("estimated_earnings"),
                "preferred": preferred,
                "chained": chained,
                "chain_task_id": breakdown.get("chain_task_id"),
                "badge": (
                    "⭐ Repeat Customer Request!"
                    if preferred
                    else ("Wrapping up a nearby job" if chained else None)
                ),
            }
        )
        items.append({"offer": payload, "task": serialize_task(task)})
    return success_response({"items": items, "total": len(items)})


@router.post("/offers/{offer_id}/accept")
def accept_offer(
    offer_id: str,
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = WorkerService(db)
    offer = service.get_offer_for_worker(offer_id, user.id)
    task_service = TaskService(db)
    task = task_service.accept_offer(offer, user)
    return success_response(
        {"task": serialize_task(task)},
        message="Offer accepted! Head to the task location as planned.",
    )


@router.post("/offers/{offer_id}/reject")
def reject_offer(
    offer_id: str,
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = WorkerService(db)
    offer = service.get_offer_for_worker(offer_id, user.id)
    task_service = TaskService(db)
    task_service.reject_offer(offer, user)
    return success_response({"rejected": True}, message="Offer declined.")


@router.get("/me/earnings")
def my_earnings(
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = WorkerService(db)
    return success_response({"earnings": service.earnings_summary(user.id)})


@router.get("/me/tier")
def my_tier(
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    """Tier, commission rate, rolling stats, next-tier thresholds and today's quests."""
    data = GamificationService(db).worker_overview(user.id)
    return success_response(data)


# ---------- verification documents ----------


@router.get("/me/documents")
def list_documents(
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = WorkerService(db)
    docs = service.list_documents(user.id)
    return success_response(
        {"items": [DocumentOut.model_validate(d).model_dump(mode="json") for d in docs]}
    )


@router.post("/me/documents", status_code=201)
async def upload_document(
    file: UploadFile,
    document_type: str = Form("id_card"),
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    content = await file.read()
    if not content:
        raise ConflictException("The uploaded file is empty.")
    service = WorkerService(db)
    doc = service.add_document(
        user.id,
        document_type=document_type,
        filename=file.filename or "upload.bin",
        content=content,
        content_type=file.content_type or "application/octet-stream",
    )
    return success_response(
        {"document": DocumentOut.model_validate(doc).model_dump(mode="json")},
        message="Document uploaded and queued for verification.",
        status_code=201,
    )


@router.delete("/me/documents/{document_id}")
def delete_document(
    document_id: str,
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = WorkerService(db)
    service.delete_document(user.id, document_id)
    return success_response({"deleted": True}, message="Document removed.")
