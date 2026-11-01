from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.core.responses import success_response
from app.models import User
from app.services import UploadService

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.get("/documents/{document_id}")
def download_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Private document download — only the owning worker or an admin may fetch it."""
    service = UploadService(db)
    document = service.document_or_404(document_id)
    service.assert_can_view(document, user)
    content, mime_type, file_name = service.read_document(document)
    return Response(
        content=content,
        media_type=mime_type,
        headers={"Content-Disposition": f'inline; filename="{file_name}"'},
    )
