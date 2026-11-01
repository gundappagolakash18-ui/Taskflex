"""Counter-offer bidding endpoints (Phase 4)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_worker
from app.api.serializers import serialize_task
from app.core.responses import success_response
from app.db.session import get_db
from app.models import TaskBid, User
from app.schemas.marketplace import BidCreate
from app.services import BiddingService, TaskService

router = APIRouter(tags=["bids"])


def _serialize_bid(bid: TaskBid, task) -> dict:
    worker = bid.worker
    profile = worker.worker_profile if worker else None
    distance_km = None
    if profile is not None and profile.latitude is not None and task.latitude is not None:
        from app.matching.geo import haversine_km

        distance_km = round(
            haversine_km(
                float(task.latitude), float(task.longitude),
                float(profile.latitude), float(profile.longitude),
            ),
            2,
        )
    return {
        "id": bid.id,
        "task_id": bid.task_id,
        "worker_id": bid.worker_id,
        "proposed_amount": float(bid.proposed_amount),
        "note": bid.note,
        "estimated_arrival_minutes": bid.estimated_arrival_minutes,
        "status": bid.status,
        "expires_at": bid.expires_at.isoformat() if bid.expires_at else None,
        "responded_at": bid.responded_at.isoformat() if bid.responded_at else None,
        "created_at": bid.created_at.isoformat() if bid.created_at else None,
        "worker_name": worker.full_name if worker else None,
        "worker_avatar": worker.avatar_url if worker else None,
        "worker_rating": float(profile.rating_average or 0) if profile else 0.0,
        "worker_rating_count": int(profile.rating_count or 0) if profile else 0,
        "worker_completed_tasks": int(profile.completed_tasks_count or 0) if profile else 0,
        "worker_tier": profile.tier if profile else None,
        "distance_km": distance_km,
    }


@router.post("/tasks/{task_id}/bids", status_code=201)
def place_bid(
    task_id: str,
    payload: BidCreate,
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    task = TaskService(db).get_task_or_404(task_id)
    bid = BiddingService(db).place_bid(
        task,
        user,
        proposed_amount=payload.proposed_amount,
        note=payload.note,
        estimated_arrival_minutes=payload.estimated_arrival_minutes,
    )
    return success_response(
        {"bid": _serialize_bid(bid, task)},
        message="Counter-offer sent. The customer has 45 seconds to respond.",
        status_code=201,
    )


@router.get("/tasks/{task_id}/bids")
def list_bids(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = TaskService(db).get_task_or_404(task_id)
    service = BiddingService(db)
    bids = service.bids_for_task(task, user)
    return success_response(
        {"items": [_serialize_bid(b, task) for b in bids], "total": len(bids)}
    )


@router.get("/tasks/{task_id}/my-bid")
def my_bid(
    task_id: str,
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    task = TaskService(db).get_task_or_404(task_id)
    bid = BiddingService(db).my_bid(task, user)
    return success_response({"bid": _serialize_bid(bid, task) if bid else None})


@router.post("/bids/{bid_id}/accept")
def accept_bid(
    bid_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = BiddingService(db).accept_bid(bid_id, user)
    return success_response(
        {"task": serialize_task(task, viewer=user)},
        message="Bid accepted — the worker is now assigned at the agreed price.",
    )


@router.post("/bids/{bid_id}/decline")
def decline_bid(
    bid_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bid = BiddingService(db).decline_bid(bid_id, user)
    return success_response({"bid_id": bid.id, "status": bid.status}, message="Counter-offer declined.")


@router.get("/workers/me/bids")
def my_bids(
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = BiddingService(db)
    bids = service.worker_bids(user)
    items = []
    for bid in bids:
        task = service.tasks.get(bid.task_id)
        if task is None:
            continue
        items.append({"bid": _serialize_bid(bid, task), "task": serialize_task(task)})
    return success_response({"items": items, "total": len(items)})
