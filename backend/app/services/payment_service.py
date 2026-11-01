"""Payment orchestration: order creation on task confirmation, hosted-checkout
verification, capture after customer confirmation, commission split, worker
wallet credit, tips, bid top-ups, refunds and gateway webhooks.

A task can carry more than one Payment row:

* ``TASK``      — the original escrow hold for the confirmed budget
* ``BID_DELTA`` — the supplemental hold created when a counter-offer raises
                  the budget after the customer accepts a worker bid
* ``TIP``       — an optional 100% pass-through gratuity

``capture_for_task`` settles TASK + BID_DELTA at completion; tips held in
escrow are settled in the same pass, while post-completion tips settle as
soon as their checkout is verified.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppException, ErrorCode, ForbiddenException
from app.core.logging import get_logger
from app.models import (
    CustomerProfile,
    Payment,
    Task,
    TaskAssignment,
    TaskExpense,
    Transaction,
    User,
    Wallet,
    WorkerProfile,
)
from app.models.enums import ExpenseStatus, NotificationType, PaymentStatus, TransactionType
from app.notifications.dispatcher import notify_users_sync
from app.payments import get_payment_provider
from app.repositories import PaymentRepository, SettingsRepository
from app.services.ledger_service import LedgerService

logger = get_logger("payments")

REQUIRED_PURPOSES = ("TASK", "BID_DELTA")
TIP_MAX_AMOUNT = 50_000.0


class PaymentService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = PaymentRepository(db)
        self.settings = SettingsRepository(db)
        self.provider = get_payment_provider()
        self.ledger = LedgerService(db)

    # ---------- commission ----------

    def commission_percent(self) -> float:
        """Platform default rate, used before a worker is assigned."""
        stored = self.settings.get_value("platform_commission_percent", float)
        return stored if stored is not None else settings.platform_commission_percent

    def commission_rate_for(self, worker_user_id: str | None) -> float:
        """The worker's personal rate, driven by their tier (SILVER/GOLD/PLATINUM)."""
        if worker_user_id:
            profile = self.db.scalar(
                select(WorkerProfile).where(WorkerProfile.user_id == worker_user_id)
            )
            if profile is not None and profile.commission_rate is not None:
                return float(profile.commission_rate)
        return self.commission_percent() / 100.0

    def split_for(self, amount: float, rate: float) -> tuple[float, float]:
        commission = round(float(amount) * rate, 2)
        return commission, round(float(amount) - commission, 2)

    def split(self, amount: float) -> tuple[float, float]:
        return self.split_for(amount, self.commission_percent() / 100.0)

    def repricing_for(self, task: Task, amount: float) -> tuple[float, float]:
        rate = self.commission_rate_for(task.assigned_worker_id)
        commission, payout = self.split_for(amount, rate)
        return commission, payout

    def apply_worker_rate(self, task: Task) -> None:
        """Re-price escrow rows once a worker is assigned so their tier rate
        (not the platform default) is what gets deducted."""
        rate = self.commission_rate_for(task.assigned_worker_id)
        payments = self.repo.payments_for_task(task.id, purposes=REQUIRED_PURPOSES)
        total_commission = 0.0
        for payment in payments:
            if payment.status in (PaymentStatus.REFUNDED, PaymentStatus.CANCELLED):
                continue
            commission, payout = self.split_for(float(payment.amount), rate)
            payment.commission_amount = commission
            payment.worker_payout_amount = payout
            total_commission += commission
        if payments:
            task.commission_amount = round(total_commission, 2)
            task.worker_payout_amount = round(float(task.budget or 0) - total_commission, 2)
        self.db.flush()

    # ---------- lifecycle ----------

    def initiate_for_task(self, task: Task) -> Payment:
        """Called when the customer confirms a task: create the gateway order and,
        when the provider authorizes instantly (mock), record the hold right away."""
        commission, payout = self.split(float(task.budget))
        intent = self.provider.create_payment(float(task.budget), task.currency, f"task:{task.id}")
        status = PaymentStatus.AUTHORIZED if intent.status == "AUTHORIZED" else PaymentStatus.INITIATED
        payment = Payment(
            task_id=task.id,
            customer_id=task.customer_id,
            provider=self.provider.name,
            provider_reference=intent.provider_reference,
            amount=float(task.budget),
            currency=task.currency,
            purpose="TASK",
            commission_amount=commission,
            worker_payout_amount=payout,
            status=status,
            authorized_at=datetime.now(timezone.utc) if status == PaymentStatus.AUTHORIZED else None,
        )
        self.repo.add_payment(payment)
        task.payment_status = payment.status
        task.commission_amount = commission
        task.worker_payout_amount = payout
        if status == PaymentStatus.AUTHORIZED:
            self.ledger.hold_payment(payment, task)
        self.db.flush()
        logger.info(
            "payment_initiated task=%s payment=%s provider=%s status=%s amount=%.2f",
            task.id, payment.id, payment.provider, payment.status, payment.amount,
        )
        return payment

    def adjust_for_budget(self, task: Task, previous_budget: float) -> Payment | None:
        """A customer accepted a bid above the original budget: hold the delta.

        With the mock provider the supplemental hold is authorized instantly;
        with Razorpay a second order is created and the customer completes it
        through the normal checkout screen before completion can be confirmed.
        """
        delta = round(float(task.budget or 0) - float(previous_budget or 0), 2)
        if delta <= 0:
            return None
        rate = self.commission_rate_for(task.assigned_worker_id)
        commission, payout = self.split_for(delta, rate)
        intent = self.provider.create_payment(
            delta, task.currency, f"task:{task.id}:bid-delta:{int(datetime.now(timezone.utc).timestamp())}"
        )
        status = PaymentStatus.AUTHORIZED if intent.status == "AUTHORIZED" else PaymentStatus.INITIATED
        payment = Payment(
            task_id=task.id,
            customer_id=task.customer_id,
            provider=self.provider.name,
            provider_reference=intent.provider_reference,
            amount=delta,
            currency=task.currency,
            purpose="BID_DELTA",
            commission_amount=commission,
            worker_payout_amount=payout,
            status=status,
            authorized_at=datetime.now(timezone.utc) if status == PaymentStatus.AUTHORIZED else None,
        )
        self.repo.add_payment(payment)
        self._refresh_task_payment_state(task)
        if status == PaymentStatus.AUTHORIZED:
            self.ledger.hold_payment(payment, task)
        self.db.flush()
        logger.info(
            "bid_delta_hold task=%s payment=%s old=%.2f new=%.2f delta=%.2f status=%s",
            task.id, payment.id, previous_budget, task.budget, delta, payment.status,
        )
        return payment

    def tip(self, task: Task, customer: User, amount: float) -> tuple[Payment, dict | None]:
        """Record a gratuity. 100% goes to the worker; no commission is taken."""
        amount = round(float(amount), 2)
        if not 1.0 <= amount <= TIP_MAX_AMOUNT:
            raise AppException(
                f"Tips must be between ₹1 and ₹{TIP_MAX_AMOUNT:.0f}.",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
        if task.customer_id != customer.id:
            raise ForbiddenException("Only the task owner can tip this worker.")
        if task.status in ("CANCELLED", "EMERGENCY_ALERT"):
            raise AppException(
                "A cancelled task cannot be tipped.",
                code=ErrorCode.INVALID_TRANSITION,
                status_code=422,
            )
        if task.assigned_worker_id is None:
            raise AppException(
                "A worker must accept this task before you can tip them.",
                code=ErrorCode.INVALID_TRANSITION,
                status_code=422,
            )

        intent = self.provider.create_payment(
            amount, task.currency, f"task:{task.id}:tip:{int(datetime.now(timezone.utc).timestamp())}"
        )
        status = PaymentStatus.AUTHORIZED if intent.status == "AUTHORIZED" else PaymentStatus.INITIATED
        payment = Payment(
            task_id=task.id,
            customer_id=task.customer_id,
            provider=self.provider.name,
            provider_reference=intent.provider_reference,
            amount=amount,
            currency=task.currency,
            purpose="TIP",
            commission_amount=0.0,
            worker_payout_amount=amount,
            status=status,
            authorized_at=datetime.now(timezone.utc) if status == PaymentStatus.AUTHORIZED else None,
        )
        self.repo.add_payment(payment)
        task.tip_amount = round(float(task.tip_amount or 0) + amount, 2)
        self.db.flush()

        checkout = None
        if status == PaymentStatus.AUTHORIZED and task.status == "COMPLETED":
            # Post-task tip with an instantly authorized provider: settle now.
            self.ledger.hold_payment(payment, task)
            self.settle_tip(payment, task)
        elif status == PaymentStatus.INITIATED:
            checkout = self._checkout_payload(payment, task, customer)
        logger.info(
            "tip_recorded task=%s payment=%s amount=%.2f status=%s",
            task.id, payment.id, amount, payment.status,
        )
        return payment, checkout

    def checkout_for_task(self, task: Task, user: User) -> dict[str, Any]:
        """Checkout details for the customer to complete or retry payment.

        Checks the original escrow first, then any bid top-up. Returns
        ``{"required": false, ...}`` when every mandatory hold is secured."""
        payments = self.repo.payments_for_task(task.id, purposes=REQUIRED_PURPOSES)
        if not payments:
            raise AppException(
                "Confirm the task first — no payment has been initiated.",
                code=ErrorCode.PAYMENT_FAILED,
                status_code=409,
            )
        outstanding = [
            p for p in payments
            if p.status in (PaymentStatus.INITIATED, PaymentStatus.FAILED)
        ]
        if not outstanding:
            if all(
                p.status in (PaymentStatus.CANCELLED, PaymentStatus.REFUNDED)
                for p in payments
            ):
                raise AppException(
                    "This payment was cancelled or refunded — there is nothing left to pay.",
                    code=ErrorCode.PAYMENT_FAILED,
                    status_code=409,
                )
            primary = payments[0]
            return {
                "required": False,
                "provider": primary.provider,
                "status": primary.status,
            }
        payment = outstanding[0]
        if payment.status == PaymentStatus.FAILED:
            payment.status = PaymentStatus.INITIATED
            payment.failure_reason = None
            self.db.flush()
        if payment.provider != "razorpay" or self.provider.name != "razorpay":
            return {
                "required": False,
                "provider": payment.provider,
                "status": payment.status,
                "purpose": payment.purpose,
                "amount": float(payment.amount),
            }

        # Razorpay: make sure a payable order exists.
        order = (
            self.provider.fetch_order(payment.provider_reference)
            if payment.provider_reference
            else None
        )
        if order and order.get("status") == "paid":
            paid = next(
                (
                    p for p in self.provider.payments_for_order(payment.provider_reference or "")
                    if p.get("status") in ("authorized", "captured")
                ),
                None,
            )
            if paid:
                self._record_gateway_payment(payment, paid)
                self.db.flush()
                return {"required": False, "provider": "razorpay", "status": payment.status,
                        "purpose": payment.purpose}
        if order is None or order.get("status") != "created":
            intent = self.provider.create_payment(
                float(payment.amount), payment.currency,
                f"task:{task.id}:{payment.purpose.lower()}",
            )
            payment.provider_reference = intent.provider_reference
            payment.provider_payment_id = None
            payment.status = PaymentStatus.INITIATED
            payment.failure_reason = None
            self._refresh_task_payment_state(task)
            self.db.flush()
            logger.info(
                "payment_order_recreated task=%s purpose=%s order=%s",
                task.id, payment.purpose, payment.provider_reference,
            )
        return self._checkout_payload(payment, task, user)

    def _checkout_payload(self, payment: Payment, task: Task, user: User) -> dict[str, Any]:
        return {
            "required": True,
            "provider": "razorpay",
            "purpose": payment.purpose,
            "key_id": settings.razorpay_key_id,
            "order_id": payment.provider_reference,
            "amount": int(round(float(payment.amount) * 100)),
            "currency": payment.currency,
            "name": settings.app_name,
            "description": (
                f"Tip for: {task.title[:70]}" if payment.purpose == "TIP"
                else f"Task: {task.title[:80]}"
            ),
            "prefill": {"name": user.full_name or "", "email": user.email or ""},
        }

    def verify_checkout(self, user: User, order_id: str, payment_id: str, signature: str) -> Payment:
        """Verify the signature returned by the hosted checkout and record the payment."""
        if self.provider.name != "razorpay":
            raise AppException(
                "Online checkout is not enabled on this deployment.",
                code=ErrorCode.PAYMENT_FAILED,
                status_code=400,
            )
        payment = self.repo.payment_by_reference(order_id)
        if payment is None:
            details = self.provider.fetch_payment(payment_id)
            if details and details.get("order_id"):
                payment = self.repo.payment_by_reference(details["order_id"])
        if payment is None:
            raise AppException("No payment matches this checkout.", code=ErrorCode.PAYMENT_FAILED, status_code=404)
        if payment.customer_id != user.id:
            raise ForbiddenException("This payment does not belong to you.")
        if not self.provider.verify_checkout_signature(order_id, payment_id, signature):
            logger.warning("checkout signature mismatch order=%s user=%s", order_id, user.id)
            raise AppException(
                "Payment verification failed — the signature is invalid.",
                code=ErrorCode.PAYMENT_FAILED,
                status_code=400,
            )
        self._record_gateway_payment(payment, {"id": payment_id})
        task = self.db.get(Task, payment.task_id)
        if payment.purpose == "TIP" and task is not None and task.status == "COMPLETED":
            self.settle_tip(payment, task)
        elif payment.purpose == "TASK" and task is not None:
            from app.services.task_service import TaskService

            TaskService(self.db).on_payment_secured(task)
        self.db.flush()
        logger.info(
            "checkout_verified task=%s payment=%s purpose=%s",
            payment.task_id, payment.id, payment.purpose,
        )
        body = (
            f"Your tip of {payment.currency} {payment.amount:.2f} was sent to your worker."
            if payment.purpose == "TIP"
            else f"Your payment of {payment.currency} {payment.amount:.2f} is held securely "
                 f"until you confirm task completion."
        )
        notify_users_sync(
            [payment.customer_id],
            notification_type=NotificationType.PAYMENT_SUCCESSFUL,
            title="Payment secured" if payment.purpose != "TIP" else "Tip sent",
            body=body,
            data={"task_id": payment.task_id, "purpose": payment.purpose},
            db=self.db,
        )
        return payment

    def apply_webhook(self, event: dict[str, Any]) -> str:
        """Apply a Razorpay webhook event. Returns a short outcome label."""
        event_type = str(event.get("event", ""))
        entity = (
            ((event.get("payload") or {}).get("payment") or {}).get("entity") or {}
        )
        order_id = entity.get("order_id")
        if not order_id:
            return "ignored"
        payment = self.repo.payment_by_reference(order_id)
        if payment is None:
            logger.warning("webhook for unknown order order=%s event=%s", order_id, event_type)
            return "unknown_order"
        if payment.status in (PaymentStatus.REFUNDED, PaymentStatus.CANCELLED):
            return "ignored_state"

        if event_type in ("payment.authorized", "payment.captured"):
            self._record_gateway_payment(payment, entity)
            task = self.db.get(Task, payment.task_id)
            if payment.purpose == "TIP" and task is not None and task.status == "COMPLETED":
                self.settle_tip(payment, task)
            elif payment.purpose == "TASK" and task is not None:
                from app.services.task_service import TaskService

                TaskService(self.db).on_payment_secured(task)
            self.db.flush()
            logger.info("webhook_applied event=%s payment=%s status=%s", event_type, payment.id, payment.status)
            return "updated"
        if event_type == "payment.failed":
            if payment.status == PaymentStatus.INITIATED:
                payment.status = PaymentStatus.FAILED
                payment.failure_reason = str(entity.get("error_description") or "Payment failed at the gateway.")[:500]
                task = self.db.get(Task, payment.task_id)
                if task and payment.purpose != "TIP":
                    task.payment_status = PaymentStatus.FAILED
                self.db.flush()
                logger.info("webhook_applied event=payment.failed payment=%s", payment.id)
                return "failed"
            return "ignored_state"
        return "ignored_event"

    def capture_for_task(self, task: Task) -> Payment:
        """Called after customer confirms completion: capture every mandatory
        hold (base + bid top-ups), pay the worker once, then settle escrowed tips."""
        required = self.repo.payments_for_task(task.id, purposes=REQUIRED_PURPOSES)
        if not required:
            raise AppException("No payment found for this task.", code=ErrorCode.PAYMENT_FAILED, status_code=409)
        outstanding = [
            p for p in required
            if p.status in (PaymentStatus.INITIATED, PaymentStatus.FAILED)
        ]
        if outstanding:
            raise AppException(
                "An additional payment is still pending for this task. "
                "Complete the checkout before finishing the task.",
                code=ErrorCode.PAYMENT_FAILED,
                status_code=402,
                details={"purpose": outstanding[0].purpose, "amount": float(outstanding[0].amount)},
            )

        primary = required[0]
        if any(p.status == PaymentStatus.CAPTURED for p in required):
            # Retry-safe: a previous pass captured but failed later. Make the
            # whole set consistent, then ensure tips were settled.
            for payment in required:
                if payment.status != PaymentStatus.CAPTURED:
                    self._capture_required(payment)
            self.settle_tips(task)
            self._refresh_task_payment_state(task)
            self._release_escrow(task, required)
            self.db.flush()
            return primary

        for payment in required:
            if payment.status != PaymentStatus.AUTHORIZED:
                raise AppException(
                    f"Payment is in state {payment.status} and cannot be captured.",
                    code=ErrorCode.PAYMENT_FAILED,
                    status_code=409,
                )
            self._capture_required(payment)

        assignment = self.db.scalar(
            select(TaskAssignment).where(
                TaskAssignment.task_id == task.id,
                TaskAssignment.worker_id == task.assigned_worker_id,
            )
        )
        payout = (
            round(float(assignment.earnings_amount) - float(assignment.commission_amount), 2)
            if assignment is not None
            else round(sum(float(p.worker_payout_amount) for p in required), 2)
        )
        commission = (
            round(float(assignment.commission_amount), 2)
            if assignment is not None
            else round(sum(float(p.commission_amount) for p in required), 2)
        )
        task.commission_amount = commission
        task.worker_payout_amount = payout
        self._credit_worker(
            task,
            payout=payout,
            currency=primary.currency,
            description=f"Base earnings for task: {task.title[:80]}",
        )
        base_amount = round(sum(float(p.amount) for p in required), 2)
        self.ledger.release_task(
            task, amount=base_amount, commission=commission, payout=payout
        )
        self._debit_customer_ledger(
            task,
            amount=round(sum(float(p.amount) for p in required), 2),
            currency=primary.currency,
            description=f"Payment for task: {task.title[:80]}",
        )
        self.settle_tips(task)
        self._refresh_task_payment_state(task)
        task.payment_status = PaymentStatus.CAPTURED
        self.db.flush()
        logger.info(
            "payment_captured task=%s payments=%d payout=%.2f commission=%.2f",
            task.id, len(required), payout, commission,
        )
        return primary

    def _capture_required(self, payment: Payment) -> None:
        result = self.provider.capture(
            payment.provider_reference or "",
            float(payment.amount),
            payment_id=payment.provider_payment_id,
            currency=payment.currency,
        )
        if not result.success:
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = result.failure_reason
            self.db.flush()
            raise AppException(
                "Payment capture failed — ask the customer to complete the payment, then try again.",
                code=ErrorCode.PAYMENT_FAILED,
                status_code=402,
            )
        if result.provider_reference and not payment.provider_payment_id:
            payment.provider_payment_id = result.provider_reference
        payment.status = PaymentStatus.CAPTURED
        payment.captured_at = datetime.now(timezone.utc)

    def _release_escrow(self, task: Task, required: list[Payment]) -> None:
        """Record the escrow release for a completed task (idempotent)."""
        assignment = self.db.scalar(
            select(TaskAssignment).where(
                TaskAssignment.task_id == task.id,
                TaskAssignment.worker_id == task.assigned_worker_id,
            )
        )
        payout = (
            round(float(assignment.earnings_amount) - float(assignment.commission_amount), 2)
            if assignment is not None
            else round(sum(float(p.worker_payout_amount) for p in required), 2)
        )
        commission = (
            round(float(assignment.commission_amount), 2)
            if assignment is not None
            else round(sum(float(p.commission_amount) for p in required), 2)
        )
        amount = round(sum(float(p.amount) for p in required), 2)
        self.ledger.release_task(task, amount=amount, commission=commission, payout=payout)

    def settle_tip(self, payment: Payment, task: Task) -> float:
        """Capture and credit one tip in full (no commission)."""
        if payment.status == PaymentStatus.CAPTURED:
            return 0.0
        if payment.status != PaymentStatus.AUTHORIZED:
            return 0.0
        if task.assigned_worker_id is None:
            return 0.0
        result = self.provider.capture(
            payment.provider_reference or "",
            float(payment.amount),
            payment_id=payment.provider_payment_id,
            currency=payment.currency,
        )
        if not result.success:
            logger.warning("tip_capture_failed task=%s payment=%s", task.id, payment.id)
            return 0.0
        payment.status = PaymentStatus.CAPTURED
        payment.captured_at = datetime.now(timezone.utc)
        amount = round(float(payment.amount), 2)
        self._credit_worker(
            task,
            payout=amount,
            currency=payment.currency,
            description=f"Tip for task: {task.title[:80]}",
            tx_type=TransactionType.TIP,
            reference_type="task_tip",
            reference_id=payment.id,
        )
        self.ledger.release_tip(payment, task)
        notify_users_sync(
            [task.assigned_worker_id],
            notification_type=NotificationType.TIP_RECEIVED,
            title="You received a tip",
            body=f"₹{amount:.0f} tip from the customer for '{task.title[:60]}'.",
            data={"task_id": task.id, "amount": amount},
            link="/worker/earnings",
            db=self.db,
        )
        self.db.flush()
        logger.info("tip_settled task=%s payment=%s amount=%.2f", task.id, payment.id, amount)
        return amount

    def settle_tips(self, task: Task) -> float:
        total = 0.0
        for payment in self.repo.payments_for_task(task.id, purposes=("TIP",)):
            if payment.status == PaymentStatus.AUTHORIZED:
                total = round(total + self.settle_tip(payment, task), 2)
        return total

    def refund_task(self, task: Task, reason: str = "Task cancelled") -> Payment | None:
        payments = self.repo.payments_for_task(
            task.id, purposes=("TASK", "BID_DELTA", "TIP")
        )
        primary = next((p for p in payments if p.purpose == "TASK"), None)
        if not payments:
            return primary
        refunded_any = False
        for payment in payments:
            if payment.status in (PaymentStatus.REFUNDED, PaymentStatus.CANCELLED):
                continue
            if payment.status == PaymentStatus.INITIATED and not payment.provider_payment_id:
                payment.status = PaymentStatus.CANCELLED
                continue
            if payment.status == PaymentStatus.FAILED:
                payment.status = PaymentStatus.CANCELLED
                continue
            result = self.provider.refund(
                payment.provider_reference or "",
                float(payment.amount),
                payment_id=payment.provider_payment_id,
            )
            if not result.success:
                logger.error(
                    "refund_failed task=%s payment=%s reason=%s",
                    task.id, payment.id, result.failure_reason,
                )
                raise AppException("Refund failed at the gateway.", code=ErrorCode.PAYMENT_FAILED, status_code=502)
            payment.status = PaymentStatus.REFUNDED
            payment.failure_reason = reason
            self.ledger.refund_payment(payment)
            refunded_any = True
        task.payment_status = PaymentStatus.REFUNDED if refunded_any else PaymentStatus.CANCELLED
        self.db.flush()
        logger.info("payment_refunded task=%s payments=%d", task.id, len(payments))
        return primary

    # ---------- internals ----------

    def _refresh_task_payment_state(self, task: Task) -> None:
        payments = self.repo.payments_for_task(task.id, purposes=REQUIRED_PURPOSES)
        active = [p for p in payments if p.status not in (PaymentStatus.REFUNDED, PaymentStatus.CANCELLED)]
        if not active:
            return
        if any(p.status in (PaymentStatus.INITIATED, PaymentStatus.FAILED) for p in active):
            task.payment_status = PaymentStatus.INITIATED
        elif all(p.status in (PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED) for p in active):
            task.payment_status = (
                PaymentStatus.CAPTURED
                if all(p.status == PaymentStatus.CAPTURED for p in active)
                else PaymentStatus.AUTHORIZED
            )
        else:
            task.payment_status = active[0].status
        task.commission_amount = round(sum(float(p.commission_amount) for p in active), 2)
        task.worker_payout_amount = round(sum(float(p.worker_payout_amount) for p in active), 2)

    def _record_gateway_payment(self, payment: Payment, gateway_payment: dict[str, Any]) -> None:
        """Money is secured at the gateway (authorized, or auto-captured e.g. UPI).
        Marked AUTHORIZED either way — the worker payout still happens only on
        completion confirmation via capture_for_task."""
        payment.provider_payment_id = gateway_payment.get("id") or payment.provider_payment_id
        if payment.status != PaymentStatus.CAPTURED:
            payment.status = PaymentStatus.AUTHORIZED
            payment.authorized_at = payment.authorized_at or datetime.now(timezone.utc)
            payment.failure_reason = None
        task = self.db.get(Task, payment.task_id)
        if task is not None and payment.purpose != "TIP":
            self._refresh_task_payment_state(task)
        if payment.status == PaymentStatus.AUTHORIZED:
            self.ledger.hold_payment(payment, task)

    def _credit_worker(
        self,
        task: Task,
        *,
        payout: float,
        currency: str,
        description: str,
        tx_type: str = TransactionType.PAYOUT.value,
        reference_type: str = "task",
        reference_id: str | None = None,
    ) -> None:
        if task.assigned_worker_id is None:
            raise AppException(
                "No worker is assigned to this task.",
                code=ErrorCode.PAYMENT_FAILED,
                status_code=409,
            )
        wallet: Wallet = self.repo.ensure_wallet(task.assigned_worker_id)
        wallet.balance = round(wallet.balance + payout, 2)
        wallet.total_earned = round(wallet.total_earned + payout, 2)
        self.repo.add_transaction(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            type=tx_type,
            amount=payout,
            balance_after=wallet.balance,
            currency=currency,
            reference_type=reference_type,
            reference_id=reference_id or task.id,
            description=description,
        )
        profile = self.db.scalar(
            select(WorkerProfile).where(WorkerProfile.user_id == wallet.user_id)
        )
        if profile:
            profile.total_earnings = round(profile.total_earnings + payout, 2)

    def reimburse_expenses(self, task: Task, expenses: list[TaskExpense]) -> float:
        """Pay approved incidental expenses in full (no commission) once the
        task completes. Each expense gets its own signed ledger entry."""
        approved = [e for e in expenses if e.status == ExpenseStatus.APPROVED.value]
        if not approved:
            return 0.0
        if not task.assigned_worker_id:
            raise AppException(
                "No worker is assigned to this task.",
                code=ErrorCode.PAYMENT_FAILED,
                status_code=409,
            )

        worker_wallet = self.repo.ensure_wallet(task.assigned_worker_id)
        customer_wallet = self.repo.ensure_wallet(task.customer_id)
        total = 0.0
        for expense in approved:
            amount = round(float(expense.amount), 2)
            if amount <= 0:
                continue
            total = round(total + amount, 2)

            worker_wallet.balance = round(worker_wallet.balance + amount, 2)
            worker_wallet.total_earned = round(worker_wallet.total_earned + amount, 2)
            self.repo.add_transaction(
                user_id=worker_wallet.user_id,
                wallet_id=worker_wallet.id,
                type=TransactionType.PAYOUT,
                amount=amount,
                balance_after=worker_wallet.balance,
                currency=task.currency,
                reference_type="task_expense",
                reference_id=expense.id,
                description=f"Expense reimbursement ({expense.category}): {expense.description[:80]}",
            )

            customer_wallet.total_spent = round(customer_wallet.total_spent + amount, 2)
            self.repo.add_transaction(
                user_id=customer_wallet.user_id,
                wallet_id=customer_wallet.id,
                type=TransactionType.DEBIT,
                amount=amount,
                balance_after=customer_wallet.balance,
                currency=task.currency,
                reference_type="task_expense",
                reference_id=expense.id,
                description=f"Expense reimbursement for task: {task.title[:60]}",
            )
            self.ledger.reimburse_expense(task, expense.id, amount)
            expense.status = ExpenseStatus.REIMBURSED.value

        customer_profile = (
            self.db.query(CustomerProfile)
            .filter(CustomerProfile.user_id == task.customer_id)
            .one_or_none()
        )
        if customer_profile and total:
            customer_profile.total_spent = round(customer_profile.total_spent + total, 2)
        self.db.flush()
        logger.info(
            "expenses_reimbursed task=%s total=%.2f count=%d",
            task.id, total, len(approved),
        )
        return total

    def _debit_customer_ledger(
        self, task: Task, *, amount: float, currency: str, description: str
    ) -> None:
        wallet = self.repo.ensure_wallet(task.customer_id)
        wallet.total_spent = round(wallet.total_spent + amount, 2)
        # Customers pay through the gateway; the wallet ledger records spend history.
        self.repo.add_transaction(
            user_id=wallet.user_id,
            wallet_id=wallet.id,
            type=TransactionType.DEBIT,
            amount=amount,
            balance_after=wallet.balance,
            currency=currency,
            reference_type="task",
            reference_id=task.id,
            description=description,
        )
        profile = self.db.query(CustomerProfile).filter(CustomerProfile.user_id == task.customer_id).one_or_none()
        if profile:
            profile.total_spent = round(profile.total_spent + amount, 2)
