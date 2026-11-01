"""Customer-managed public tracking links."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.responses import success_response
from app.db.session import get_db
from app.models import User
from app.schemas.share import ShareLinkCreate
from app.services import ShareService, TaskService

router = APIRouter(prefix="/tasks", tags=["tracking-share"])


@router.post("/{task_id}/share")
def create_share_link(
    task_id: str,
    payload: ShareLinkCreate | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mint (or return) the public tracking link for a task in flight."""
    task = TaskService(db).get_task_or_404(task_id)
    service = ShareService(db)
    link = service.create_link(
        task,
        user,
        expires_in_hours=payload.expires_in_hours if payload else None,
        rotate=payload.rotate if payload else False,
    )
    return success_response(
        {"share": link},
        message="Live tracking link ready. Anyone with this link can follow the worker.",
    )


@router.get("/{task_id}/share")
def get_share_link(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = TaskService(db).get_task_or_404(task_id)
    link = ShareService(db).active_link(task, user)
    return success_response({"share": link})


@router.delete("/{task_id}/share")
def revoke_share_link(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = TaskService(db).get_task_or_404(task_id)
    had_link = ShareService(db).revoke_link(task, user)
    return success_response(
        {"revoked": had_link},
        message="Tracking link revoked." if had_link else "No active tracking link to revoke.",
    )
