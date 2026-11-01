"""Unauthenticated endpoints. Nothing here may expose personal data."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.db.session import get_db
from app.services import ShareService

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/track/{token}")
async def public_track(
    token: str,
    db: Session = Depends(get_db),
):
    """Sanitized live-tracking snapshot for a share-link holder."""
    service = ShareService(db)
    task = service.resolve(token)
    snapshot = await service.public_snapshot(task)
    response = success_response({"tracking": snapshot})
    # Positions are live: never let a proxy or browser replay an old fix.
    response.headers["Cache-Control"] = "no-store"
    return response
