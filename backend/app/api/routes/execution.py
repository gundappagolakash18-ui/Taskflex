"""Proof-of-execution photos and the incidental expense ledger.

Evidence files live in private storage; every read is permission-checked and
streamed by the backend. List endpoints return metadata only.
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.serializers import serialize_execution_proof, serialize_task_expense
from app.core.responses import success_response
from app.db.session import get_db
from app.models import User
from app.schemas.execution import ExpenseDecisionRequest
from app.services import ExecutionService, TaskService

router = APIRouter(prefix="/tasks", tags=["execution"])


def _private_file(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------------------
# Proof of execution
# ---------------------------------------------------------------------------


@router.post("/{task_id}/proof-of-execution", status_code=201)
def upload_execution_proof(
    task_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Worker uploads a location-tagged photo as evidence of execution."""
    task = TaskService(db).get_task_or_404(task_id)
    content = file.file.read()
    proof = ExecutionService(db).add_proof(
        task,
        user,
        filename=file.filename or "proof.jpg",
        content_type=file.content_type or "",
        content=content,
    )
    return success_response(
        {"proof": serialize_execution_proof(proof)},
        message="Proof photo uploaded. Location and capture time were verified.",
        status_code=201,
    )


@router.get("/{task_id}/proofs")
def list_execution_proofs(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = TaskService(db).get_task_or_404(task_id)
    service = ExecutionService(db)
    service.assert_can_view_evidence(task, user)
    return success_response(
        {"items": [serialize_execution_proof(p) for p in service.list_proofs(task)]}
    )


@router.get("/{task_id}/proofs/{proof_id}/file")
def download_execution_proof(
    task_id: str,
    proof_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = TaskService(db).get_task_or_404(task_id)
    service = ExecutionService(db)
    service.assert_can_view_evidence(task, user)
    content, media_type, filename = service.read_proof(task, proof_id)
    return _private_file(content, media_type, filename)


# ---------------------------------------------------------------------------
# Incidental expenses
# ---------------------------------------------------------------------------


@router.post("/{task_id}/expenses", status_code=201)
def create_task_expense(
    task_id: str,
    amount: float = Form(...),
    category: str = Form("OTHER"),
    description: str = Form(...),
    receipt: UploadFile | None = File(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Worker logs an on-the-spot expense; the customer is notified instantly."""
    task = TaskService(db).get_task_or_404(task_id)
    receipt_payload = None
    if receipt is not None and receipt.filename:
        receipt_payload = (
            receipt.file.read(),
            receipt.filename,
            receipt.content_type or "",
        )
    expense = ExecutionService(db).add_expense(
        task,
        user,
        amount=amount,
        category=category,
        description=description,
        receipt=receipt_payload,
    )
    return success_response(
        {"expense": serialize_task_expense(expense)},
        message="Expense submitted. Your customer has been asked to approve it.",
        status_code=201,
    )


@router.get("/{task_id}/expenses")
def list_task_expenses(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = TaskService(db).get_task_or_404(task_id)
    service = ExecutionService(db)
    service.assert_can_view_evidence(task, user)
    return success_response(
        {
            "items": [serialize_task_expense(e) for e in service.list_expenses(task)],
            "totals": service.expense_totals(task),
        }
    )


@router.get("/{task_id}/expenses/{expense_id}/receipt")
def download_expense_receipt(
    task_id: str,
    expense_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = TaskService(db).get_task_or_404(task_id)
    service = ExecutionService(db)
    service.assert_can_view_evidence(task, user)
    content, media_type, filename = service.read_receipt(task, expense_id)
    return _private_file(content, media_type, filename)


@router.post("/{task_id}/expenses/{expense_id}/approve")
def approve_task_expense(
    task_id: str,
    expense_id: str,
    payload: ExpenseDecisionRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = TaskService(db).get_task_or_404(task_id)
    service = ExecutionService(db)
    expense = service.decide_expense(
        task, user, expense_id, approve=True, note=payload.note if payload else None
    )
    return success_response(
        {
            "expense": serialize_task_expense(expense),
            "totals": service.expense_totals(task),
        },
        message="Expense approved — it will be added to the worker's payout.",
    )


@router.post("/{task_id}/expenses/{expense_id}/reject")
def reject_task_expense(
    task_id: str,
    expense_id: str,
    payload: ExpenseDecisionRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = TaskService(db).get_task_or_404(task_id)
    service = ExecutionService(db)
    expense = service.decide_expense(
        task, user, expense_id, approve=False, note=payload.note if payload else None
    )
    return success_response(
        {
            "expense": serialize_task_expense(expense),
            "totals": service.expense_totals(task),
        },
        message="Expense rejected. The worker has been notified.",
    )
