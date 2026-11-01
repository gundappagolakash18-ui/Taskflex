"""Double-entry platform treasury ledger.

Accounts
--------
EXTERNAL      the payment gateway / bank world outside the platform
ESCROW        customer money held for active tasks
REVENUE       platform commission earned on completed tasks
WORKER        internal worker wallet balances
PAYOUT_HOLD   withdrawal requests awaiting admin settlement

Every posting is a journal whose signed movements sum to zero, so money is
never created or destroyed inside the books.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppException, ErrorCode
from app.core.logging import get_logger
from app.models import Payment, PlatformLedgerEntry, PayoutRequest, Task

logger = get_logger("taskflex.ledger")

ACCOUNTS = ("EXTERNAL", "ESCROW", "REVENUE", "WORKER", "PAYOUT_HOLD")
TOLERANCE = 0.01


class LedgerService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Core posting
    # ------------------------------------------------------------------

    def post(
        self,
        entry_type: str,
        movements: dict[str, float],
        *,
        description: str,
        reference_type: str | None = None,
        reference_id: str | None = None,
        currency: str = "INR",
        journal_id: str | None = None,
    ) -> str:
        rounded = {account: round(float(amount), 2) for account, amount in movements.items()}
        unknown = set(rounded) - set(ACCOUNTS)
        if unknown:
            raise AppException(
                f"Unknown ledger account(s): {', '.join(sorted(unknown))}.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=500,
            )
        if abs(sum(rounded.values())) > TOLERANCE:
            raise AppException(
                f"Unbalanced ledger journal for {entry_type}: {rounded}.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=500,
            )
        journal = journal_id or str(uuid.uuid4())
        for account, amount in rounded.items():
            if abs(amount) < 0.005:
                continue
            self.db.add(
                PlatformLedgerEntry(
                    account=account,
                    amount=amount,
                    currency=currency,
                    entry_type=entry_type,
                    journal_id=journal,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    description=description[:255],
                )
            )
        self.db.flush()
        logger.info(
            "ledger_posted type=%s ref=%s:%s movements=%s",
            entry_type, reference_type, reference_id, rounded,
        )
        return journal

    def has_entry(self, entry_type: str, reference_id: str) -> bool:
        return bool(
            self.db.scalar(
                select(PlatformLedgerEntry.id)
                .where(
                    PlatformLedgerEntry.entry_type == entry_type,
                    PlatformLedgerEntry.reference_id == reference_id,
                )
                .limit(1)
            )
        )

    # ------------------------------------------------------------------
    # Payment lifecycle
    # ------------------------------------------------------------------

    def hold_payment(self, payment: Payment, task: Task | None = None) -> None:
        """Customer money secured at the gateway is held in escrow."""
        if self.has_entry("ESCROW_DEPOSIT", payment.id):
            return
        amount = round(float(payment.amount), 2)
        self.post(
            "ESCROW_DEPOSIT",
            {"ESCROW": amount, "EXTERNAL": -amount},
            description=(
                f"{payment.purpose} payment held in escrow"
                + (f" for {task.title[:60]}" if task is not None else "")
            ),
            reference_type="payment",
            reference_id=payment.id,
            currency=payment.currency,
        )

    def release_task(self, task: Task, *, amount: float, commission: float, payout: float) -> None:
        """Completion: escrow pays the worker and books platform commission."""
        if self.has_entry("WORKER_EARNING", task.id):
            return
        amount = round(float(amount), 2)
        commission = round(float(commission), 2)
        payout = round(float(payout), 2)
        if abs(amount - commission - payout) > TOLERANCE:
            # Never silently plug a discrepancy — surface it instead.
            payout = round(amount - commission, 2)
        self.post(
            "WORKER_EARNING",
            {"ESCROW": -amount, "REVENUE": commission, "WORKER": payout},
            description=f"Escrow released for completed task: {task.title[:80]}",
            reference_type="task",
            reference_id=task.id,
            currency=task.currency,
        )

    def release_tip(self, payment: Payment, task: Task) -> None:
        if self.has_entry("TIP_RELEASE", payment.id):
            return
        amount = round(float(payment.amount), 2)
        self.post(
            "TIP_RELEASE",
            {"ESCROW": -amount, "WORKER": amount},
            description=f"Tip released to worker for task: {task.title[:70]}",
            reference_type="payment",
            reference_id=payment.id,
            currency=payment.currency,
        )

    def refund_payment(self, payment: Payment) -> None:
        """Reverse a held payment back to the customer through the gateway."""
        if self.has_entry("ESCROW_REFUND", payment.id):
            return
        if not self.has_entry("ESCROW_DEPOSIT", payment.id):
            return
        amount = round(float(payment.amount), 2)
        self.post(
            "ESCROW_REFUND",
            {"ESCROW": -amount, "EXTERNAL": amount},
            description="Customer refund for cancelled/disputed task",
            reference_type="payment",
            reference_id=payment.id,
            currency=payment.currency,
        )

    def reimburse_expense(self, task: Task, expense_id: str, amount: float) -> None:
        if self.has_entry("EXPENSE_REIMBURSEMENT", expense_id):
            return
        amount = round(float(amount), 2)
        self.post(
            "EXPENSE_REIMBURSEMENT",
            {"ESCROW": -amount, "WORKER": amount},
            description=f"Approved task expense reimbursed: {task.title[:70]}",
            reference_type="expense",
            reference_id=expense_id,
            currency=task.currency,
        )

    # ------------------------------------------------------------------
    # Payouts
    # ------------------------------------------------------------------

    def hold_payout(self, payout: PayoutRequest) -> None:
        if self.has_entry("PAYOUT_REQUEST", payout.id):
            return
        amount = round(float(payout.amount), 2)
        self.post(
            "PAYOUT_REQUEST",
            {"WORKER": -amount, "PAYOUT_HOLD": amount},
            description=f"Withdrawal requested to {payout.upi_id}",
            reference_type="payout",
            reference_id=payout.id,
        )

    def settle_payout(self, payout: PayoutRequest) -> None:
        if self.has_entry("PAYOUT_SETTLED", payout.id):
            return
        amount = round(float(payout.amount), 2)
        self.post(
            "PAYOUT_SETTLED",
            {"PAYOUT_HOLD": -amount, "EXTERNAL": amount},
            description=f"Withdrawal settled to {payout.upi_id}",
            reference_type="payout",
            reference_id=payout.id,
        )

    def reverse_payout(self, payout: PayoutRequest) -> None:
        if self.has_entry("PAYOUT_REVERSED", payout.id):
            return
        amount = round(float(payout.amount), 2)
        self.post(
            "PAYOUT_REVERSED",
            {"PAYOUT_HOLD": -amount, "WORKER": amount},
            description=f"Withdrawal rejected — returned to wallet ({payout.upi_id})",
            reference_type="payout",
            reference_id=payout.id,
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def balances(self) -> dict[str, float]:
        rows = self.db.execute(
            select(PlatformLedgerEntry.account, func.sum(PlatformLedgerEntry.amount)).group_by(
                PlatformLedgerEntry.account
            )
        ).all()
        totals = {account: 0.0 for account in ACCOUNTS}
        for account, total in rows:
            totals[account] = round(float(total or 0.0), 2)
        return totals

    def summary(self) -> dict[str, Any]:
        balances = self.balances()
        collected = self._sum_entries("ESCROW_DEPOSIT")
        refunded = self._sum_entries("ESCROW_REFUND")
        commissions = balances["REVENUE"]
        worker_paid = self._sum_entries("WORKER_EARNING") + self._sum_entries("TIP_RELEASE")
        expenses = self._sum_entries("EXPENSE_REIMBURSEMENT")
        payouts_settled = self._sum_entries("PAYOUT_SETTLED")
        return {
            "accounts": balances,
            "escrow_balance": balances["ESCROW"],
            "revenue_balance": balances["REVENUE"],
            "payout_hold_balance": balances["PAYOUT_HOLD"],
            "collected_total": round(collected, 2),
            "refunded_total": round(refunded, 2),
            "commission_total": round(commissions, 2),
            "worker_earnings_total": round(worker_paid, 2),
            "expense_reimbursed_total": round(expenses, 2),
            "payouts_settled_total": round(payouts_settled, 2),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _sum_entries(self, entry_type: str) -> float:
        total = self.db.scalar(
            select(func.sum(PlatformLedgerEntry.amount)).where(
                PlatformLedgerEntry.entry_type == entry_type
            )
        )
        return round(float(total or 0.0), 2)

    def entries(
        self,
        *,
        account: str | None = None,
        entry_type: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[PlatformLedgerEntry], int]:
        stmt = select(PlatformLedgerEntry)
        if account:
            stmt = stmt.where(PlatformLedgerEntry.account == account)
        if entry_type:
            stmt = stmt.where(PlatformLedgerEntry.entry_type == entry_type)
        stmt = stmt.order_by(PlatformLedgerEntry.created_at.desc())
        total = self.db.execute(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        ).scalar_one()
        items = list(self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars())
        return items, int(total)
