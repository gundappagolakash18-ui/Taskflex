"""Worker wallet: UPI cashout, payout history and earnings statements."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import require_worker
from app.core.responses import success_response
from app.db.session import get_db
from app.models import User
from app.schemas.marketplace import UpiUpdateRequest, WithdrawRequest
from app.services import WalletService

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.put("/upi")
def set_upi(
    payload: UpiUpdateRequest,
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    profile = WalletService(db).set_upi(user, payload.upi_id)
    return success_response(
        {"upi_id": profile.upi_id}, message="UPI ID saved — withdrawals will use it."
    )


@router.post("/withdraw")
def withdraw(
    payload: WithdrawRequest,
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    result = WalletService(db).request_withdrawal(user, payload.amount, payload.upi_id)
    payout = result["payout"]
    return success_response(
        result,
        message=f"₹{payout['amount']:.0f} sent to {payout['upi_id']} (UTR {payout['reference_utr']}).",
    )


@router.get("/payouts")
def payouts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = WalletService(db)
    items, total = service.payouts(user, page=page, page_size=page_size)
    return success_response(
        {
            "items": [service.payout_payload(p) for p in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/statement")
def statement(
    format: str = Query("json", pattern="^(json|csv)$"),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = WalletService(db)
    end = datetime.now(timezone.utc)
    data = service.statement(user, start=end - timedelta(days=days), end=end)
    if format == "csv":
        csv_body = service.statement_csv(data)
        return Response(
            content=csv_body,
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="taskflex-statement-{end.date().isoformat()}.csv"'
                )
            },
        )
    return success_response({"statement": data})
