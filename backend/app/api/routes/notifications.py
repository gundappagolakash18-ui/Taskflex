from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.core.exceptions import NotFoundException
from app.core.responses import success_response
from app.models import User
from app.repositories import NotificationRepository
from app.schemas.notification import NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repo = NotificationRepository(db)
    items, total = repo.for_user(user.id, unread_only=unread_only, page=page, page_size=page_size)
    return success_response(
        {
            "items": [NotificationOut.model_validate(n).model_dump(mode="json") for n in items],
            "total": total,
            "unread": repo.unread_count(user.id),
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/unread-count")
def unread_count(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repo = NotificationRepository(db)
    return success_response({"count": repo.unread_count(user.id)})


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models import Notification

    repo = NotificationRepository(db)
    row = db.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise NotFoundException("Notification not found.")
    repo.mark_read(row)
    return success_response({"marked": True})


@router.post("/read-all")
def mark_all_read(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repo = NotificationRepository(db)
    count = repo.mark_all_read(user.id)
    return success_response({"marked": count}, message="All notifications marked as read.")
