from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.core.responses import success_response
from app.models import User
from app.schemas.payment import DisputeCreate, DisputeOut, DisputeResolveRequest
from app.services import DisputeService, TaskService

router = APIRouter(prefix="/disputes", tags=["disputes"])


@router.post("", status_code=201)
def raise_dispute(
    payload: DisputeCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task_service = TaskService(db)
    task = task_service.get_task_or_404(payload.task_id)
    service = DisputeService(db)
    dispute = service.raise_dispute(task, user, reason=payload.reason, description=payload.description)
    return success_response(
        {"dispute": DisputeOut.model_validate(dispute).model_dump(mode="json")},
        message="Dispute filed. Our admin team will review it shortly.",
        status_code=201,
    )


@router.get("")
def list_disputes(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = DisputeService(db)
    if user.role == "ADMIN":
        items, total = service.list_disputes(status=status, page=page, page_size=page_size)
    else:
        items = service.repo.for_user(user.id)
        total = len(items)
        start = (page - 1) * page_size
        items = items[start : start + page_size]
    return success_response(
        {
            "items": [DisputeOut.model_validate(d).model_dump(mode="json") for d in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/{dispute_id}")
def get_dispute(
    dispute_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = DisputeService(db)
    dispute = service.get_dispute_or_404(dispute_id)
    service.assert_can_view(dispute, user)
    return success_response({"dispute": DisputeOut.model_validate(dispute).model_dump(mode="json")})


@router.post("/{dispute_id}/resolve")
def resolve_dispute(
    dispute_id: str,
    payload: DisputeResolveRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = DisputeService(db)
    dispute = service.get_dispute_or_404(dispute_id)
    dispute = service.resolve(
        dispute,
        admin,
        outcome=payload.status.value,
        resolution_note=payload.resolution_note,
    )
    return success_response(
        {"dispute": DisputeOut.model_validate(dispute).model_dump(mode="json")},
        message="Dispute resolved.",
    )
