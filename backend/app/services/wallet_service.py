"""Worker wallet: UPI cashout, payout requests and earnings statements.

Withdrawals are instant for the supported simulated UPI rail: the balance is
deducted atomically (row lock), a ``WITHDRAWAL`` ledger entry is written and a
``PayoutRequest`` is completed with a generated UTR. Statements aggregate the
ledger into the marketplace's earnings categories and can be rendered as JSON
or CSV.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppException, ErrorCode, NotFoundException
from app.core.logging import get_logger
from app.core.timeutils import as_aware
from app.models import (
    NotificationType,
    PayoutRequest,
    PayoutStatus,
    Task,
    TaskAssignment,
    Transaction,
    TransactionType,
    User,
    Wallet,
    WorkerProfile,
)
from app.notifications.dispatcher import notify_users_sync
from app.repositories import PaymentRepository
from app.websocket.manager import fire_and_forget, manager

logger = get_logger("taskflex.wallet")

UPI_PATTERN = re.compile(r"^[\w.\-]+@[\w]+$")
MIN_WITHDRAWAL = 100.0
IST = timezone(timedelta(hours=5, minutes=30))


class WalletService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = PaymentRepository(db)

    # ------------------------------------------------------------------
    # UPI
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_upi(upi_id: str) -> str:
        upi = (upi_id or "").strip()
        if not UPI_PATTERN.match(upi):
            raise AppException(
                "Enter a valid UPI ID such as name@bank.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
        return upi

    def set_upi(self, worker_user: User, upi_id: str) -> WorkerProfile:
        profile = self.db.scalar(
            select(WorkerProfile).where(WorkerProfile.user_id == worker_user.id)
        )
        if profile is None:
            raise NotFoundException("Worker profile not found.")
        profile.upi_id = self.normalize_upi(upi_id)
        self.db.flush()
        logger.info("worker_upi_set worker=%s", worker_user.id)
        return profile

    # ------------------------------------------------------------------
    # Withdrawal
    # ------------------------------------------------------------------

    def request_withdrawal(self, worker_user: User, amount: float, upi_id: str | None = None) -> dict:
        amount = round(float(amount), 2)
        if amount < MIN_WITHDRAWAL:
            raise AppException(
                f"The minimum withdrawal is ₹{MIN_WITHDRAWAL:.0f}. "
                f"Keep earning — your balance stays safe in the wallet.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
        profile = self.db.scalar(
            select(WorkerProfile).where(WorkerProfile.user_id == worker_user.id)
        )
        if profile is None:
            raise NotFoundException("Worker profile not found.")
        destination = self.normalize_upi(upi_id or profile.upi_id or "")

        wallet = self.repo.get_wallet_for_update(worker_user.id)
        if wallet is None:
            wallet = self.repo.ensure_wallet(worker_user.id)
        if round(wallet.balance, 2) < amount:
            raise AppException(
                f"Your wallet balance is ₹{wallet.balance:.2f} — you cannot withdraw ₹{amount:.2f}.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )

        wallet.balance = round(wallet.balance - amount, 2)
        reference = self._generate_utr()
        payout = PayoutRequest(
            worker_id=worker_user.id,
            amount=amount,
            upi_id=destination,
            reference_utr=reference,
            status=PayoutStatus.COMPLETED.value,
            completed_at=datetime.now(timezone.utc),
        )
        self.db.add(payout)
        self.db.flush()
        self.repo.add_transaction(
            user_id=worker_user.id,
            wallet_id=wallet.id,
            type=TransactionType.WITHDRAWAL,
            amount=amount,
            balance_after=wallet.balance,
            currency=wallet.currency,
            reference_type="payout",
            reference_id=payout.id,
            description=f"UPI withdrawal to {destination} (UTR {reference})",
        )
        profile.upi_id = destination
        notify_users_sync(
            [worker_user.id],
            notification_type=NotificationType.PAYOUT_PROCESSED,
            title="Withdrawal processed",
            body=f"₹{amount:.0f} was sent to {destination}. UTR: {reference}.",
            data={
                "payout_id": payout.id,
                "amount": amount,
                "upi_id": destination,
                "reference_utr": reference,
            },
            link="/worker/earnings",
            db=self.db,
        )
        fire_and_forget(
            manager.send_to_user(
                worker_user.id,
                "PAYOUT_PROCESSED",
                {
                    "payout_id": payout.id,
                    "amount": amount,
                    "upi_id": destination,
                    "reference_utr": reference,
                    "status": payout.status,
                },
            )
        )
        self.db.flush()
        logger.info(
            "payout_completed worker=%s amount=%.2f payout=%s",
            worker_user.id, amount, payout.id,
        )
        return {
            "payout": self.payout_payload(payout),
            "wallet": {
                "balance": wallet.balance,
                "currency": wallet.currency,
                "total_earned": wallet.total_earned,
            },
        }

    @staticmethod
    def _generate_utr() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"TFX{stamp}{uuid.uuid4().hex[:6].upper()}"

    def payouts(self, worker_user: User, page: int = 1, page_size: int = 20) -> tuple[list[PayoutRequest], int]:
        stmt = (
            select(PayoutRequest)
            .where(PayoutRequest.worker_id == worker_user.id)
            .order_by(PayoutRequest.created_at.desc())
        )
        total = self.db.execute(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        ).scalar_one()
        items = list(
            self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars()
        )
        return items, int(total)

    @staticmethod
    def payout_payload(payout: PayoutRequest) -> dict:
        return {
            "id": payout.id,
            "amount": float(payout.amount),
            "upi_id": payout.upi_id,
            "reference_utr": payout.reference_utr,
            "status": payout.status,
            "failure_reason": payout.failure_reason,
            "created_at": payout.created_at.isoformat() if payout.created_at else None,
            "completed_at": payout.completed_at.isoformat() if payout.completed_at else None,
        }

    # ------------------------------------------------------------------
    # Statement
    # ------------------------------------------------------------------

    def statement(
        self,
        worker_user: User,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc)
        period_end = end or now
        period_start = start or (period_end - timedelta(days=30))
        # SQLite stores naive UTC; normalise the bounds for both engines.
        start_naive = as_aware(period_start).astimezone(timezone.utc).replace(tzinfo=None)
        end_naive = as_aware(period_end).astimezone(timezone.utc).replace(tzinfo=None)

        txs = self.repo.transactions_between(worker_user.id, start_naive, end_naive)
        categories = {
            "base_earnings": 0.0,
            "overtime_earnings": 0.0,
            "reimbursed_expenses": 0.0,
            "tips": 0.0,
            "quest_bonuses": 0.0,
            "withdrawals": 0.0,
            "other_credits": 0.0,
        }
        entries = []
        for tx in txs:
            category = self._categorize(tx)
            amount = round(float(tx.amount), 2)
            if category in categories:
                categories[category] = round(categories[category] + amount, 2)
            entries.append(
                {
                    "id": tx.id,
                    "type": tx.type,
                    "category": category,
                    "amount": amount,
                    "currency": tx.currency,
                    "description": tx.description,
                    "reference_type": tx.reference_type,
                    "reference_id": tx.reference_id,
                    "created_at": tx.created_at.isoformat() if tx.created_at else None,
                }
            )

        platform_fees = float(
            self.db.scalar(
                select(func.coalesce(func.sum(TaskAssignment.commission_amount), 0))
                .select_from(TaskAssignment)
                .join(Task, Task.id == TaskAssignment.task_id)
                .where(
                    TaskAssignment.worker_id == worker_user.id,
                    TaskAssignment.completed_at.is_not(None),
                    TaskAssignment.completed_at >= start_naive,
                    TaskAssignment.completed_at < end_naive,
                )
            )
            or 0.0
        )
        platform_fees = round(platform_fees, 2)
        gross = round(
            categories["base_earnings"]
            + categories["overtime_earnings"]
            + categories["reimbursed_expenses"]
            + categories["tips"]
            + categories["quest_bonuses"],
            2,
        )
        wallet = self.repo.get_wallet(worker_user.id)
        return {
            "worker_id": worker_user.id,
            "period": {
                "from": as_aware(period_start).isoformat(),
                "to": as_aware(period_end).isoformat(),
            },
            "currency": wallet.currency if wallet else "INR",
            "categories": categories,
            "platform_fees": platform_fees,
            "gross_earnings": round(gross + platform_fees, 2),
            # Ledger credits already carry payouts net of commission, so the
            # net figure equals the sum of the credited categories.
            "net_earnings": gross,
            "withdrawn": categories["withdrawals"],
            "wallet_balance": round(float(wallet.balance), 2) if wallet else 0.0,
            "transaction_count": len(entries),
            "transactions": entries,
        }

    @staticmethod
    def _categorize(tx: Transaction) -> str:
        if tx.type == TransactionType.TIP.value:
            return "tips"
        if tx.type == TransactionType.QUEST_BONUS.value:
            return "quest_bonuses"
        if tx.type == TransactionType.WITHDRAWAL.value:
            return "withdrawals"
        if tx.type == TransactionType.PAYOUT.value:
            if tx.reference_type == "task_expense":
                return "reimbursed_expenses"
            return "base_earnings"
        if tx.type == TransactionType.CREDIT.value and tx.reference_type == "overtime":
            return "overtime_earnings"
        return "other_credits"

    @staticmethod
    def statement_csv(statement: dict) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["TASKFLEX EARNINGS STATEMENT"])
        writer.writerow(["Worker", statement["worker_id"]])
        writer.writerow(["From", statement["period"]["from"]])
        writer.writerow(["To", statement["period"]["to"]])
        writer.writerow(["Currency", statement["currency"]])
        writer.writerow([])
        writer.writerow(["Category", "Amount"])
        labels = {
            "base_earnings": "Base Earnings",
            "overtime_earnings": "Overtime",
            "reimbursed_expenses": "Reimbursed Expenses",
            "tips": "Tips",
            "quest_bonuses": "Quest Bonuses",
            "withdrawals": "Withdrawals",
            "other_credits": "Other Credits",
        }
        for key, label in labels.items():
            writer.writerow([label, f"{statement['categories'][key]:.2f}"])
        writer.writerow(["Gross Earnings (before fees)", f"{statement['gross_earnings']:.2f}"])
        writer.writerow(["Platform Fees (already deducted)", f"{statement['platform_fees']:.2f}"])
        writer.writerow(["Net Earnings (credited)", f"{statement['net_earnings']:.2f}"])
        writer.writerow(["Wallet Balance", f"{statement['wallet_balance']:.2f}"])
        writer.writerow([])
        writer.writerow(["Date", "Category", "Type", "Description", "Amount", "Currency"])
        category_labels = {v: k for k, v in labels.items()}
        for entry in statement["transactions"]:
            writer.writerow(
                [
                    entry["created_at"] or "",
                    category_labels.get(entry["category"], entry["category"]),
                    entry["type"],
                    entry["description"],
                    f"{entry['amount']:.2f}",
                    entry["currency"],
                ]
            )
        return buffer.getvalue()
