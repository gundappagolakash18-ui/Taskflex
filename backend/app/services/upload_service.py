"""Authorized access to private uploads (worker verification documents).

Files live outside the web root; every read goes through permission checks
and is streamed back as a response — never a public URL.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenException, NotFoundException
from app.models import User, UserRole, VerificationDocument, WorkerProfile
from app.storage import get_storage


class UploadService:
    def __init__(self, db: Session):
        self.db = db

    def document_or_404(self, document_id: str) -> VerificationDocument:
        doc = self.db.get(VerificationDocument, document_id)
        if doc is None:
            raise NotFoundException("Document not found.")
        return doc

    def assert_can_view(self, document: VerificationDocument, viewer: User) -> None:
        if viewer.role == UserRole.ADMIN.value:
            return
        profile = self.db.scalar(
            select(WorkerProfile).where(WorkerProfile.id == document.worker_profile_id)
        )
        if profile is None:
            raise NotFoundException("Worker profile not found.")
        if profile.user_id != viewer.id:
            raise ForbiddenException("Documents are private to the worker and admins.")

    def read_document(self, document: VerificationDocument) -> tuple[bytes, str, str]:
        storage = get_storage()
        content = storage.read(document.file_path)
        return content, document.mime_type, document.file_name
