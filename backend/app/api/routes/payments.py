import json

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.exceptions import AppException, ErrorCode, ForbiddenException, NotFoundException
from app.core.logging import get_logger
from app.core.responses import success_response
from app.db.session import get_db
from app.models import Task, User
from app.repositories import PaymentRepository
from app.schemas.payment import CheckoutVerifyRequest, PaymentOut
from app.services.payment_service import PaymentService

logger = get_logger("payments.api")

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("")
def my_payments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repo = PaymentRepository(db)
    items, total = repo.payments_for(user.id, page=page, page_size=page_size)
    return success_response(
        {
            "items": [PaymentOut.model_validate(p).model_dump(mode="json") for p in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/checkout/{task_id}")
def checkout_details(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Checkout parameters for the task owner to pay (or retry paying) the task budget."""
    task = db.get(Task, task_id)
    if task is None:
        raise NotFoundException("Task not found.")
    if task.customer_id != user.id:
        raise ForbiddenException("Only the task owner can pay for this task.")
    service = PaymentService(db)
    return success_response(service.checkout_for_task(task, user))


@router.post("/verify")
def verify_checkout(
    payload: CheckoutVerifyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify the signature returned by the Razorpay checkout and record the payment."""
    service = PaymentService(db)
    payment = service.verify_checkout(
        user,
        payload.razorpay_order_id,
        payload.razorpay_payment_id,
        payload.razorpay_signature,
    )
    return success_response(
        {"payment": PaymentOut.model_validate(payment).model_dump(mode="json")},
        message="Payment verified — the amount is held until you confirm completion.",
    )


@router.post("/webhook/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(default="", alias="X-Razorpay-Signature"),
    db: Session = Depends(get_db),
):
    """Razorpay server-to-server notification. Unauthenticated by design —
    the HMAC signature over the raw body is the authentication."""
    if not settings.razorpay_webhook_secret:
        raise AppException(
            "Razorpay webhooks are not configured on this deployment.",
            code=ErrorCode.PAYMENT_FAILED,
            status_code=503,
        )
    # Read the raw bytes: the signature is HMAC'd over the exact payload, and
    # Razorpay sends Content-Type: application/json, which would make FastAPI
    # parse (and re-serialize differently) any JSON-typed body parameter.
    body = await request.body()
    service = PaymentService(db)
    if not service.provider.verify_webhook_signature(body, x_razorpay_signature):
        logger.warning("razorpay webhook signature mismatch")
        raise AppException("Invalid webhook signature.", code=ErrorCode.PAYMENT_FAILED, status_code=400)
    try:
        event = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppException("Malformed webhook payload.", code=ErrorCode.VALIDATION_ERROR, status_code=400) from exc
    outcome = service.apply_webhook(event)
    logger.info("razorpay webhook processed event=%s outcome=%s", event.get("event"), outcome)
    return success_response({"outcome": outcome})


@router.get("/for-task/{task_id}")
def payment_for_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repo = PaymentRepository(db)
    payment = repo.payment_for_task(task_id)
    if payment is None:
        raise NotFoundException("No payment recorded for this task yet.")
    task = db.get(Task, task_id)
    is_worker = task is not None and task.assigned_worker_id == user.id
    if user.role != "ADMIN" and payment.customer_id != user.id and not is_worker:
        raise ForbiddenException("You cannot view this payment.")
    return success_response({"payment": PaymentOut.model_validate(payment).model_dump(mode="json")})
