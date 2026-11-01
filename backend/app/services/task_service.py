"""Task lifecycle orchestration — the heart of TaskFlex."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.task_parser import get_task_parser
from app.ai.schemas import ParsedTaskDraft
from app.core.exceptions import (
    AIParseException,
    AppException,
    ConflictException,
    ErrorCode,
    ForbiddenException,
    InvalidTransitionException,
    NotFoundException,
)
from app.core.logging import get_logger
from app.core.timeutils import as_aware, utcnow
from app.dispatch.engine import dispatch_engine
from app.matching.engine import MatchingEngine
from app.matching.config import get_matching_config
from app.matching.geo import haversine_km
from app.models import (
    AffinityType,
    CustomerProfile,
    CustomerWorkerAffinity,
    Task,
    TaskAssignment,
    TaskBid,
    TaskExecutionProof,
    TaskLocation,
    TaskOffer,
    TaskRequirement,
    TaskStatus,
    TaskStatusHistory,
    User,
    UserRole,
    WorkerProfile,
    BidStatus,
    NotificationType,
    WORKER_STATUS_FLOW,
)
from app.notifications.dispatcher import notify_users_sync
from app.repositories import TaskRepository, UserRepository
from app.schemas.common import paginate
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.execution_service import ExecutionService
from app.services.gamification_service import GamificationService
from app.services.otp_service import (
    PURPOSE_COMPLETION,
    PURPOSE_RETURN,
    PURPOSE_START,
    issue_otp,
    verify_otp,
)
from app.services.payment_service import PaymentService
from app.services.pricing_engine import FareQuote, PricingEngine, enforce_budget
from app.services.ridecheck_monitor import RideCheckMonitor
from app.websocket.manager import fire_and_forget, manager

logger = get_logger("taskflex.tasks")

MAX_OFFERS_PER_TASK = 5
OFFER_TTL_MINUTES = 30

IST = timezone(timedelta(hours=5, minutes=30))
SCHEDULED_THRESHOLD_MINUTES = 60
RETURN_TO_ORIGIN_LABEL = "Return to Origin / Customer Handback"


def broadcast_task_status(task: Task) -> None:
    """Push a TASK_STATUS event to the customer, worker and every admin."""
    payload = {"task_id": task.id, "status": task.status}
    user_ids = [task.customer_id]
    if task.assigned_worker_id:
        user_ids.append(task.assigned_worker_id)
    user_ids.extend(admin_recipient_ids())
    fire_and_forget(_send_status_ws(list(dict.fromkeys(user_ids)), payload))


_admin_cache: dict[str, object] = {"at": 0.0, "ids": []}


def admin_recipient_ids() -> list[str]:
    """Active admin ids for dashboard fan-out (cached briefly)."""
    import time

    if time.time() - float(_admin_cache["at"]) < 60:
        return list(_admin_cache["ids"])  # type: ignore[arg-type]
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        ids = list(
            db.scalars(
                select(User.id).where(
                    User.role == UserRole.ADMIN.value, User.is_active.is_(True)
                )
            )
        )
    except Exception:
        logger.warning("admin_recipient_query_failed")
        ids = []
    finally:
        db.close()
    _admin_cache["at"] = time.time()
    _admin_cache["ids"] = ids
    return ids


async def _send_status_ws(user_ids: list[str], payload: dict) -> None:
    try:
        await manager.send_to_users(user_ids, "TASK_STATUS", payload)
    except Exception:
        logger.warning("task_status_ws_failed task=%s", payload.get("task_id"))


class TaskService:
    """Owns every state transition of a task.

    Flow: DRAFT → PENDING_CONFIRMATION → CONFIRMED → SEARCHING_WORKER
        → OFFERED → ACCEPTED → WORKER_ON_THE_WAY → ARRIVED_AT_LOCATION
        → (start OTP) IN_PROGRESS → (proof + completion OTP) COMPLETED
        (or CANCELLED / DISPUTED / EMERGENCY_ALERT from compatible states).
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.tasks = TaskRepository(db)
        self.workers = UserRepository(db)
        self.payment_service = PaymentService(db)
        self.matching = MatchingEngine(config=get_matching_config())
        self.pricing = PricingEngine()

    # ------------------------------------------------------------------
    # Parse (AI, read-only)
    # ------------------------------------------------------------------

    def parse_request(self, raw_text: str) -> ParsedTaskDraft:
        parser = get_task_parser()
        if not raw_text or not raw_text.strip():
            raise AIParseException("Request text is empty — tell us what you need done.")
        try:
            return parser.parse(raw_text.strip())
        except AIParseException:
            raise
        except Exception:
            logger.exception("task parse blew up")
            raise AIParseException("The AI assistant could not process that request.")

    # ------------------------------------------------------------------
    # Create / read / update
    # ------------------------------------------------------------------

    def create_task(self, customer: User, payload: TaskCreate) -> Task:
        if payload.is_round_trip:
            if (
                payload.pickup_latitude is None
                or payload.pickup_longitude is None
                or payload.latitude is None
                or payload.longitude is None
            ):
                raise AppException(
                    "A round-trip errand needs both pickup coordinates and the errand destination.",
                    code=ErrorCode.VALIDATION_ERROR,
                    status_code=422,
                )
        task = Task(
            customer_id=customer.id,
            title=payload.title.strip()[:160],
            description=payload.description.strip(),
            task_type=payload.task_type.value if hasattr(payload.task_type, "value") else payload.task_type,
            status=TaskStatus.PENDING_CONFIRMATION.value,
            urgency=payload.urgency.value if hasattr(payload.urgency, "value") else payload.urgency,
            scheduled_date=payload.scheduled_date,
            scheduled_time=payload.scheduled_time,
            estimated_duration_minutes=payload.estimated_duration_minutes,
            latitude=payload.latitude,
            longitude=payload.longitude,
            address_text=payload.address_text,
            area_name=payload.area_name,
            city=payload.city,
            budget=payload.budget,
            special_requirements=payload.special_requirements,
            parsed_by_ai=payload.parsed_by_ai,
            ai_confidence=payload.ai_confidence,
            payment_status="PENDING",
            is_round_trip=payload.is_round_trip,
        )
        self.db.add(task)
        self.db.flush()

        seen_skills: set[str] = set()
        for skill_name in payload.required_skills or []:
            name = skill_name.strip()[:100]
            if name and name.lower() not in seen_skills:
                seen_skills.add(name.lower())
                self.db.add(TaskRequirement(task_id=task.id, skill_name=name, is_required=True))

        if payload.is_round_trip:
            pickup = (payload.pickup_latitude, payload.pickup_longitude)
            self.db.add(
                TaskLocation(
                    task_id=task.id,
                    label="pickup",
                    sequence=1,
                    latitude=pickup[0],
                    longitude=pickup[1],
                    address=payload.pickup_address or "Customer pickup point",
                )
            )
            self.db.add(
                TaskLocation(
                    task_id=task.id,
                    label="dropoff",
                    sequence=2,
                    latitude=payload.latitude,
                    longitude=payload.longitude,
                    address=payload.address_text or payload.area_name or payload.city,
                )
            )
            self.db.add(
                TaskLocation(
                    task_id=task.id,
                    label="return",
                    sequence=3,
                    latitude=pickup[0],
                    longitude=pickup[1],
                    address=RETURN_TO_ORIGIN_LABEL,
                )
            )
        elif payload.latitude is not None and payload.longitude is not None:
            self.db.add(
                TaskLocation(
                    task_id=task.id,
                    label="primary",
                    sequence=1,
                    latitude=payload.latitude,
                    longitude=payload.longitude,
                    address=payload.address_text or payload.area_name or payload.city,
                )
            )

        self._record_history(task, None, TaskStatus.PENDING_CONFIRMATION.value, actor=customer)
        self.db.flush()
        logger.info("task created", extra_fields={"task_id": task.id, "customer_id": customer.id})
        return task

    def get_task_or_404(self, task_id: str) -> Task:
        task = self.tasks.get(task_id)
        if task is None:
            raise NotFoundException("Task not found.")
        return task

    def assert_can_view(self, task: Task, user: User) -> None:
        if user.role == UserRole.ADMIN.value:
            return
        if user.role == UserRole.CUSTOMER.value and task.customer_id == user.id:
            return
        if user.role == UserRole.WORKER.value:
            if task.assigned_worker_id == user.id:
                return
            offer = self.db.scalar(
                select(TaskOffer.id).where(
                    TaskOffer.task_id == task.id, TaskOffer.worker_id == user.id
                )
            )
            if offer:
                return
            bid = self.db.scalar(
                select(TaskBid.id).where(
                    TaskBid.task_id == task.id, TaskBid.worker_id == user.id
                )
            )
            if bid:
                return
        raise ForbiddenException("You do not have access to this task.")

    def update_task(self, task: Task, payload: TaskUpdate) -> Task:
        editable = {
            "title", "description", "urgency", "scheduled_date", "scheduled_time",
            "latitude", "longitude", "address_text", "budget",
        }
        for field, value in payload.model_dump(exclude_unset=True).items():
            if field in editable:
                setattr(task, field, value)
        self.db.flush()
        return task

    # ------------------------------------------------------------------
    # Confirm — the gate that turns an AI draft into a live task
    # ------------------------------------------------------------------

    async def enforce_fare_floor(self, task: Task) -> FareQuote:
        """Reject budgets below the dynamic fare floor (BUDGET_BELOW_MINIMUM_FLOOR)."""
        quote = await self.pricing.floor_for_task(task)
        enforce_budget(float(task.budget or 0), quote, task_id=task.id)
        return quote

    def confirm_task(self, task: Task, customer: User) -> Task:
        if task.status != TaskStatus.PENDING_CONFIRMATION.value:
            raise InvalidTransitionException(
                f"Only tasks in PENDING_CONFIRMATION can be confirmed (current: {task.status})."
            )
        if task.customer_id != customer.id:
            raise ForbiddenException("You can only confirm your own tasks.")

        task.status = TaskStatus.CONFIRMED.value
        task.confirmed_at = datetime.now(timezone.utc)
        self._record_history(task, TaskStatus.PENDING_CONFIRMATION.value,
                             TaskStatus.CONFIRMED.value, actor=customer, reason="customer confirmed")

        # The start handshake code is minted the moment the task goes live.
        issue_otp(task, PURPOSE_START)
        if task.is_round_trip:
            # The handback code is minted up front too; the customer reads it
            # out only when the worker returns with the goods/document.
            issue_otp(task, PURPOSE_RETURN)

        # Create the payment hold up-front: instant for the mock provider, a
        # gateway order awaiting customer checkout for Razorpay.
        try:
            self.payment_service.initiate_for_task(task)
        except Exception:
            logger.exception("payment authorization failed; task stays confirmed without payment")
            task.payment_status = "FAILED"

        profile = self.db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == customer.id))
        if profile:
            profile.total_tasks_posted = (profile.total_tasks_posted or 0) + 1

        scheduled_for = self._resolve_scheduled_for(task)
        if scheduled_for is not None:
            task.scheduled_for = scheduled_for
        starts_later = (
            scheduled_for is not None
            and (scheduled_for - datetime.now(timezone.utc)).total_seconds()
            > SCHEDULED_THRESHOLD_MINUTES * 60
        )
        if starts_later:
            task.is_scheduled = True
            previous = task.status
            task.status = TaskStatus.SCHEDULED_OPEN.value
            self._record_history(
                task, previous, TaskStatus.SCHEDULED_OPEN.value, actor=customer,
                reason="scheduled more than 60 minutes ahead — opened for reservation",
            )
            notify_users_sync(
                [customer.id],
                notification_type=NotificationType.TASK_CONFIRMED,
                title=f"Reservation open: {task.title}",
                body=(
                    "Verified workers can now reserve this scheduled task. "
                    "You'll be notified when someone claims it, and again when they confirm readiness."
                ),
                data={"task_id": task.id, "scheduled_for": scheduled_for.isoformat()},
                link=f"/customer/tasks/{task.id}",
                db=self.db,
            )
            self._broadcast_task_status(task)
            self.db.flush()
            logger.info("task scheduled task=%s scheduled_for=%s", task.id, scheduled_for)
            return task

        # STRICT GATE: no worker is ever offered a task until the customer's
        # money is secured at the gateway (authorized or captured).
        if not self.payments_secured(task):
            notify_users_sync(
                [customer.id],
                notification_type=NotificationType.PAYMENT_SUCCESSFUL,
                title="Complete payment to start matching",
                body=(
                    f"Your task is confirmed. Pay {task.currency} {float(task.budget):.2f} "
                    "to release it to nearby runners — funds are held until you confirm completion."
                ),
                data={"task_id": task.id, "amount": float(task.budget)},
                link=f"/app/tasks/{task.id}",
                deliver_email=True,
                db=self.db,
            )
            self._broadcast_task_status(task)
            self.db.flush()
            logger.info("task awaiting_payment task=%s status=%s", task.id, task.payment_status)
            return task

        dispatched = self._dispatch_offers(task)
        self._broadcast_task_status(task)
        self.db.flush()
        logger.info(
            "task confirmed",
            extra_fields={"task_id": task.id, "offers_sent": dispatched},
        )
        return task

    def payments_secured(self, task: Task) -> bool:
        """True when every mandatory hold (base + bid top-ups) is secured."""
        payments = self.payment_service.repo.payments_for_task(
            task.id, purposes=("TASK", "BID_DELTA")
        )
        if not payments:
            return False
        return all(
            p.status in ("AUTHORIZED", "CAPTURED") for p in payments
        )

    def on_payment_secured(self, task: Task) -> bool:
        """Called after a checkout/webhook verifies payment. Starts matching
        for a confirmed task that was waiting on money."""
        if task.status != TaskStatus.CONFIRMED.value:
            return False
        if not self.payments_secured(task):
            return False
        self.payment_service._refresh_task_payment_state(task)
        dispatched = self._dispatch_offers(task)
        self._broadcast_task_status(task)
        self.db.flush()
        logger.info("task_activated_after_payment task=%s offers=%d", task.id, dispatched)
        return True

    def _resolve_scheduled_for(self, task: Task) -> datetime | None:
        """Combine the customer's chosen date/time (interpreted as IST) into an
        aware UTC instant. Tasks without a full date+time are not scheduled."""
        if task.scheduled_date is None or task.scheduled_time is None:
            return None
        local = datetime.combine(task.scheduled_date, task.scheduled_time, tzinfo=IST)
        return local.astimezone(timezone.utc)

    # ------------------------------------------------------------------
    # Matching → offers
    # ------------------------------------------------------------------

    def _dispatch_offers(self, task: Task) -> int:
        """Sequential ring-down: queue ranked candidates, offer to the best
        one with a 30s countdown, then escalate on misses."""
        previous = task.status
        task.status = TaskStatus.SEARCHING_WORKER.value
        if previous != TaskStatus.SEARCHING_WORKER.value:
            self._record_history(task, previous,
                                 TaskStatus.SEARCHING_WORKER.value, reason="matching started")

        candidates = dispatch_engine.start(self.db, task)

        if candidates == 0:
            self._notify_customer(
                task,
                notification_type=NotificationType.SYSTEM,
                title="No workers available right now",
                body=(
                    "We could not find an eligible worker near your location. "
                    "Your task stays open and will be offered as workers come online."
                ),
            )
        else:
            self._notify_customer(
                task,
                notification_type=NotificationType.TASK_CONFIRMED,
                title=f"Task confirmed: {task.title}",
                body=(
                    "We are offering your task to the best-ranked worker nearby. "
                    "You will be notified as soon as someone accepts."
                ),
            )
        return candidates

    def _notify_customer(
        self,
        task: Task,
        notification_type: str,
        title: str,
        body: str,
        *,
        deliver_email: bool = False,
        data: dict | None = None,
    ) -> None:
        notify_users_sync(
            [task.customer_id],
            notification_type=notification_type,
            title=title,
            body=body,
            data={"task_id": task.id, **(data or {})},
            link=f"/customer/tasks/{task.id}",
            deliver_email=deliver_email,
            db=self.db,
        )

    def retry_matching(self, task: Task) -> int:
        """Re-run matching for tasks still searching (used when offers expire)."""
        if task.status not in (TaskStatus.SEARCHING_WORKER.value, TaskStatus.OFFERED.value):
            raise InvalidTransitionException("Matching can only be retried while searching for workers.")
        return self._dispatch_offers(task)

    # ------------------------------------------------------------------
    # Worker offer decisions
    # ------------------------------------------------------------------

    def accept_offer(self, offer: TaskOffer, worker_user: User) -> Task:
        task = self.get_task_or_404(offer.task_id)
        if offer.worker_id != worker_user.id:
            raise ForbiddenException("This offer is not yours.")
        if offer.status != "PENDING":
            raise ConflictException("This offer is no longer pending.")
        if offer.expires_at and as_aware(offer.expires_at) < utcnow():
            offer.status = "EXPIRED"
            raise ConflictException("This offer has expired.")
        if task.status not in (TaskStatus.SEARCHING_WORKER.value, TaskStatus.OFFERED.value):
            raise ConflictException("This task is no longer accepting workers.")
        if not dispatch_engine.try_acquire_lock(task.id, worker_user.id):
            raise ConflictException("Another worker just accepted this task.")
        try:
            return self._accept_locked(offer, task, worker_user)
        except Exception:
            dispatch_engine.release_lock(task.id)
            raise

    def _accept_locked(self, offer: TaskOffer, task: Task, worker_user: User) -> Task:
        profile = self.workers.get_worker_profile(worker_user.id)
        if profile is None:
            raise ForbiddenException("Worker profile missing.")
        if profile.queued_task_id is not None and profile.queued_task_id != task.id:
            raise ConflictException("You already have another task queued as your next job.")

        # Back-to-back chaining: a worker whose current job is near its final
        # waypoint may accept the next task even at max concurrency; accepting
        # queues it and it auto-promotes when the current task completes.
        chain_task, _chain_origin = self.matching.chaining_state(self.db, profile)
        chained = chain_task is not None
        active_count = self.tasks.worker_active_task_count(worker_user.id)
        if not chained and active_count >= (profile.max_concurrent_tasks or 1):
            raise ConflictException("You are already at your concurrent task limit.")

        # Assignment — priced at the worker's tier commission.
        earnings = task.budget if task.budget is not None else Decimal("0")
        rate = self.payment_service.commission_rate_for(worker_user.id)
        commission_amount, _payout = self.payment_service.split_for(float(earnings), rate)
        commission = Decimal(str(commission_amount))
        now = datetime.now(timezone.utc)
        assignment = TaskAssignment(
            task_id=task.id,
            worker_id=worker_user.id,
            earnings_amount=earnings,
            commission_amount=commission,
            accepted_at=now,
        )
        self.db.add(assignment)

        previous_status = task.status
        task.assigned_worker_id = worker_user.id
        new_status = TaskStatus.QUEUED_NEXT.value if chained else TaskStatus.ACCEPTED.value
        task.status = new_status
        self._record_history(
            task, previous_status, new_status, actor=worker_user,
            reason=(
                f"chained behind active task {chain_task.id}" if chained
                else "worker accepted the offer"
            ),
        )
        if chained:
            profile.queued_task_id = task.id
            task.bids_close_at = None

        # Expire sibling offers and any outstanding counter-offers.
        siblings = self.db.scalars(
            select(TaskOffer).where(
                TaskOffer.task_id == task.id,
                TaskOffer.id != offer.id,
                TaskOffer.status == "PENDING",
            )
        )
        for sibling in siblings:
            sibling.status = "EXPIRED"
        offer.status = "ACCEPTED"
        offer.responded_at = now
        self._expire_task_bids(task, responded_at=now)

        # Winner found: kill the countdown and drain the ring queue.
        dispatch_engine.finalize_accept(task.id)
        self.payment_service.apply_worker_rate(task)

        if chained:
            self._notify_customer(
                task,
                notification_type=NotificationType.WORKER_ACCEPTED,
                title=f"Next runner locked in: {task.title}",
                body=(
                    f"{worker_user.full_name} is finishing a nearby task and will take yours "
                    f"back-to-back. We'll start the route the moment their current job wraps up."
                ),
                deliver_email=True,
                data={"status": new_status},
            )
            notify_users_sync(
                [worker_user.id],
                notification_type=NotificationType.WORKER_ACCEPTED,
                title=f"Next job queued: {task.title}",
                body=(
                    "You're chained! Finish your current task, then head straight to this one. "
                    "The route to the new pickup starts automatically."
                ),
                data={"task_id": task.id, "status": new_status},
                link="/worker/tasks",
                db=self.db,
            )
        else:
            self._notify_customer(
                task,
                notification_type=NotificationType.WORKER_ACCEPTED,
                title=f"Worker assigned: {task.title}",
                body=f"{worker_user.full_name} accepted your task and will start soon.",
                deliver_email=True,
                data={"status": new_status},
            )
        notify_users_sync(
            [w.user_id for w in self._other_offered_workers(task, exclude=worker_user.id)],
            notification_type=NotificationType.SYSTEM,
            title="Offer filled",
            body=f"The task '{task.title}' was just accepted by another worker.",
            data={"task_id": task.id},
            db=self.db,
        )
        self._broadcast_task_status(task)
        self.db.flush()
        return task

    def _expire_task_bids(self, task: Task, *, responded_at: datetime | None = None) -> None:
        now = responded_at or datetime.now(timezone.utc)
        for bid in self.db.scalars(
            select(TaskBid).where(
                TaskBid.task_id == task.id,
                TaskBid.status == BidStatus.PENDING.value,
            )
        ):
            bid.status = BidStatus.EXPIRED.value
            bid.responded_at = now

    def _other_offered_workers(self, task: Task, exclude: str) -> list[WorkerProfile]:
        rows = self.db.scalars(
            select(WorkerProfile)
            .join(TaskOffer, TaskOffer.worker_id == WorkerProfile.user_id)
            .where(TaskOffer.task_id == task.id, TaskOffer.status == "PENDING")
        ).all()
        return [w for w in rows if w.user_id != exclude]

    def reject_offer(self, offer: TaskOffer, worker_user: User) -> None:
        if offer.worker_id != worker_user.id:
            raise ForbiddenException("This offer is not yours.")
        if offer.status != "PENDING":
            raise ConflictException("This offer is no longer pending.")
        offer.status = "DECLINED"
        offer.responded_at = datetime.now(timezone.utc)

        task = self.get_task_or_404(offer.task_id)
        if task.status in (TaskStatus.SEARCHING_WORKER.value, TaskStatus.OFFERED.value) \
                and task.assigned_worker_id is None:
            dispatch_engine.on_declined(self.db, task, offer)
        self.db.flush()

    # ------------------------------------------------------------------
    # Worker progress transitions
    # ------------------------------------------------------------------

    def worker_status_update(self, task: Task, worker_user: User, new_status: TaskStatus) -> Task:
        if task.assigned_worker_id != worker_user.id:
            raise ForbiddenException("You are not assigned to this task.")
        current = TaskStatus(task.status)
        allowed_next = WORKER_STATUS_FLOW.get(current)
        if allowed_next is None or new_status != allowed_next:
            raise InvalidTransitionException(
                f"From {current.value} the only allowed next step is "
                f"{allowed_next.value if allowed_next else 'none'}."
            )

        task.status = new_status.value
        self._record_history(task, current.value, new_status.value, actor=worker_user)

        assignment = self.db.scalar(
            select(TaskAssignment).where(
                TaskAssignment.task_id == task.id, TaskAssignment.worker_id == worker_user.id
            )
        )
        if assignment is not None:
            if new_status == TaskStatus.IN_PROGRESS and assignment.started_at is None:
                assignment.started_at = datetime.now(timezone.utc)
            if new_status == TaskStatus.COMPLETED and assignment.completed_at is None:
                assignment.completed_at = datetime.now(timezone.utc)

        destination = task.area_name or task.city or "the task location"
        if new_status == TaskStatus.COMPLETED:
            task.worker_completed_at = datetime.now(timezone.utc)
            self._notify_customer(
                task,
                notification_type=NotificationType.TASK_COMPLETED,
                title=f"Work completed: {task.title}",
                body="Please review and confirm completion so the worker gets paid.",
                deliver_email=True,
                data={"status": new_status.value},
            )
        elif new_status == TaskStatus.WORKER_ON_THE_WAY:
            self._notify_customer(
                task,
                notification_type=NotificationType.WORKER_ARRIVING,
                title=f"Runner on the way: {task.title}",
                body=(
                    f"{worker_user.full_name} is on the way to {destination}. "
                    "Open the task to follow the route live."
                ),
                deliver_email=True,
                data={"status": new_status.value},
            )
        elif new_status == TaskStatus.ARRIVED_AT_LOCATION:
            self._notify_customer(
                task,
                notification_type=NotificationType.WORKER_ARRIVING,
                title=f"Runner arrived: {task.title}",
                body=(
                    f"{worker_user.full_name} has reached {destination}. Open the task "
                    "and read them your 4-digit start code so the work can begin."
                ),
                deliver_email=True,
                data={"status": new_status.value},
            )
        else:
            self._notify_customer(
                task,
                notification_type=NotificationType.SYSTEM,
                title=f"Status update: {task.title}",
                body=f"Status changed to {new_status.value}.",
                data={"status": new_status.value},
            )
        self._broadcast_task_status(task)
        self.db.flush()
        return task

    # ------------------------------------------------------------------
    # OTP handshake — start verification and completion release
    # ------------------------------------------------------------------

    def verify_start_otp(self, task: Task, worker_user: User, code: str) -> Task:
        """Worker at the location enters the customer's start code:
        ARRIVED_AT_LOCATION → IN_PROGRESS."""
        if task.assigned_worker_id != worker_user.id:
            raise ForbiddenException("You are not assigned to this task.")
        current = TaskStatus(task.status)
        if current != TaskStatus.ARRIVED_AT_LOCATION:
            raise InvalidTransitionException(
                f"Mark yourself ARRIVED_AT_LOCATION before verifying the start code (current: {current.value})."
            )

        verify_otp(self.db, task, PURPOSE_START, code)

        task.status = TaskStatus.IN_PROGRESS.value
        self._record_history(task, current.value, TaskStatus.IN_PROGRESS.value,
                             actor=worker_user, reason="start OTP verified")
        assignment = self.db.scalar(
            select(TaskAssignment).where(
                TaskAssignment.task_id == task.id, TaskAssignment.worker_id == worker_user.id
            )
        )
        if assignment is not None and assignment.started_at is None:
            assignment.started_at = datetime.now(timezone.utc)

        if task.is_round_trip:
            # The navigation target flips to the return origin once underway.
            from app.tracking.service import reset_task_route

            reset_task_route(task.id)

        self._notify_customer(
            task,
            notification_type=NotificationType.OTP_VERIFIED,
            title=f"Task started: {task.title}",
            body="Your worker verified the start code and has begun the task.",
        )
        self._broadcast_task_status(task)
        self.db.flush()
        logger.info("start_otp_verified task=%s worker=%s", task.id, worker_user.id)
        return task

    def request_completion(self, task: Task, worker_user: User) -> Task:
        """Worker finished the work: IN_PROGRESS → COMPLETION_REQUESTED.
        Requires at least one proof-of-execution photo, then mints the
        completion code the customer reads out."""
        if task.assigned_worker_id != worker_user.id:
            raise ForbiddenException("You are not assigned to this task.")
        current = TaskStatus(task.status)
        if current != TaskStatus.IN_PROGRESS:
            raise InvalidTransitionException(
                f"Only tasks IN_PROGRESS can request completion (current: {current.value})."
            )
        if self._execution_proof_count(task) < 1:
            raise AppException(
                "Upload at least one proof-of-execution photo before requesting completion.",
                code=ErrorCode.PROOF_REQUIRED,
                status_code=422,
            )

        issue_otp(task, PURPOSE_COMPLETION)
        task.worker_completed_at = datetime.now(timezone.utc)
        task.status = TaskStatus.COMPLETION_REQUESTED.value
        self._record_history(task, current.value, TaskStatus.COMPLETION_REQUESTED.value,
                             actor=worker_user, reason="worker finished; completion OTP issued")

        self._notify_customer(
            task,
            notification_type=NotificationType.TASK_COMPLETED,
            title=f"Work finished: {task.title}",
            body=(
                "Review the proof photos and share the completion code with your worker "
                "to release the payment."
            ),
        )
        self._broadcast_task_status(task)
        self.db.flush()
        return task

    def complete_with_otp(self, task: Task, worker_user: User, code: str) -> Task:
        """Worker submits the completion code the customer read out:
        COMPLETION_REQUESTED → COMPLETED and the escrow is released."""
        if task.assigned_worker_id != worker_user.id:
            raise ForbiddenException("You are not assigned to this task.")
        current = TaskStatus(task.status)
        if current != TaskStatus.COMPLETION_REQUESTED:
            raise InvalidTransitionException(
                f"Only tasks in COMPLETION_REQUESTED can be completed with a code (current: {current.value})."
            )

        if task.is_round_trip and task.return_otp_verified_at is None:
            raise AppException(
                "This is a round-trip errand. Verify the customer's return handback code "
                "before releasing the payment.",
                code=ErrorCode.OTP_INVALID,
                status_code=422,
                details={"purpose": PURPOSE_RETURN},
            )

        verify_otp(self.db, task, PURPOSE_COMPLETION, code)

        if self._execution_proof_count(task) < 1:
            raise AppException(
                "Proof of execution is missing — upload at least one photo.",
                code=ErrorCode.PROOF_REQUIRED,
                status_code=422,
            )

        now = datetime.now(timezone.utc)
        task.status = TaskStatus.COMPLETED.value
        task.completed_at = now
        task.customer_confirmed_at = now  # the code handshake is the customer's confirmation
        self._record_history(task, current.value, TaskStatus.COMPLETED.value,
                             actor=worker_user, reason="completion OTP verified; escrow released")

        assignment = self.db.scalar(
            select(TaskAssignment).where(
                TaskAssignment.task_id == task.id, TaskAssignment.worker_id == worker_user.id
            )
        )
        if assignment is not None:
            assignment.status = "COMPLETED"
            if assignment.completed_at is None:
                assignment.completed_at = now

        self.payment_service.capture_for_task(task)
        execution = ExecutionService(self.db)
        execution.close_pending_expenses(task)
        expense_total = self.payment_service.reimburse_expenses(
            task, execution.approved_expenses(task)
        )

        self._notify_customer(
            task,
            notification_type=NotificationType.COMPLETION_CONFIRMED,
            title=f"Task completed: {task.title}",
            body="Completion code verified. Payment released to the worker. Thank you!",
        )
        worker_body = f"Earnings for '{task.title}' were credited to your wallet."
        if expense_total:
            worker_body = (
                f"Earnings for '{task.title}' plus ₹{expense_total:.0f} in approved "
                f"expense reimbursements were credited to your wallet."
            )
        notify_users_sync(
            [task.assigned_worker_id],
            notification_type=NotificationType.PAYMENT_SUCCESSFUL,
            title="Payment credited",
            body=worker_body,
            data={"task_id": task.id, "expense_reimbursed": expense_total},
            link="/worker/earnings",
            db=self.db,
        )

        # Safety telemetry for this task is no longer needed.
        RideCheckMonitor(self.db).clear_task(task.id)

        # Quests, tier recalculation and the confetti event.
        try:
            GamificationService(self.db).on_task_completed(task, worker_user)
        except Exception:
            logger.exception("gamification_failed task=%s worker=%s", task.id, worker_user.id)

        # Chained job: promote the worker's queued task immediately.
        try:
            self._promote_queued_task(worker_user, completed_task=task)
        except Exception:
            logger.exception("queued_promotion_failed worker=%s", worker_user.id)

        self._broadcast_task_status(task)
        self.db.flush()
        logger.info("completion_otp_verified task=%s worker=%s", task.id, worker_user.id)
        return task

    def _promote_queued_task(self, worker_user: User, *, completed_task: Task) -> Task | None:
        """The worker's current task just finished: start the queued one."""
        profile = self.workers.get_worker_profile(worker_user.id)
        if profile is None or not profile.queued_task_id:
            return None
        queued = self.tasks.get(profile.queued_task_id)
        profile.queued_task_id = None
        if queued is None or queued.status != TaskStatus.QUEUED_NEXT.value:
            return None

        previous = queued.status
        queued.status = TaskStatus.ACCEPTED.value
        self._record_history(
            queued, previous, TaskStatus.ACCEPTED.value, actor=worker_user,
            reason=f"auto-promoted after completing chained task {completed_task.id}",
        )
        self.payment_service.apply_worker_rate(queued)

        # Fresh route: the worker now heads to the queued task's pickup.
        from app.tracking.service import reset_task_route

        reset_task_route(queued.id)

        notify_users_sync(
            [worker_user.id],
            notification_type=NotificationType.SYSTEM,
            title=f"Your queued job is live: {queued.title}",
            body=(
                f"'{completed_task.title[:60]}' is done — your next task "
                f"'{queued.title[:60]}' is now active. Head to the pickup."
            ),
            data={"task_id": queued.id, "promoted_from": completed_task.id},
            link=f"/worker/tasks/{queued.id}",
            db=self.db,
        )
        self._notify_customer(
            queued,
            notification_type=NotificationType.WORKER_FOUND,
            title=f"Your worker is on the way: {queued.title}",
            body=(
                f"{worker_user.full_name} just finished their previous task and is now "
                f"heading to you for the queued job."
            ),
        )
        broadcast_task_status(queued)
        logger.info("queued_task_promoted task=%s worker=%s", queued.id, worker_user.id)
        return queued

    def verify_return_otp(self, task: Task, worker_user: User, code: str) -> Task:
        """Round-trip handback: the worker is back at the origin with the goods
        and enters the customer's return code. Escrow can only be released
        once this handshake has happened."""
        if not task.is_round_trip:
            raise InvalidTransitionException("This task is not a round-trip errand.")
        if task.assigned_worker_id != worker_user.id:
            raise ForbiddenException("You are not assigned to this task.")
        if task.status not in (TaskStatus.IN_PROGRESS.value, TaskStatus.COMPLETION_REQUESTED.value):
            raise InvalidTransitionException(
                f"The return handback code can only be verified while the task is in progress "
                f"(current: {task.status})."
            )
        if task.return_otp_verified_at is not None:
            raise ConflictException("The return handback code was already verified for this task.")

        verify_otp(self.db, task, PURPOSE_RETURN, code)
        task.return_otp_verified_at = datetime.now(timezone.utc)
        self._notify_customer(
            task,
            notification_type=NotificationType.OTP_VERIFIED,
            title=f"Handback confirmed: {task.title}",
            body=(
                "Your return handback code was verified. Your worker can now close the task "
                "and release the payment."
            ),
        )
        self.db.flush()
        logger.info("return_otp_verified task=%s worker=%s", task.id, worker_user.id)
        return task

    def _execution_proof_count(self, task: Task) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(TaskExecutionProof)
                .where(TaskExecutionProof.task_id == task.id)
            )
            or 0
        )

    def _broadcast_task_status(self, task: Task) -> None:
        broadcast_task_status(task)

    # ------------------------------------------------------------------
    # Customer cancellation / dispute handoff
    # ------------------------------------------------------------------

    def cancel_task(self, task: Task, actor: User, reason: str) -> Task:
        cancellable = {
            TaskStatus.DRAFT.value,
            TaskStatus.PENDING_CONFIRMATION.value,
            TaskStatus.CONFIRMED.value,
            TaskStatus.SEARCHING_WORKER.value,
            TaskStatus.OFFERED.value,
            TaskStatus.SCHEDULED_OPEN.value,
            TaskStatus.SCHEDULED_ASSIGNED.value,
            TaskStatus.QUEUED_NEXT.value,
            TaskStatus.ACCEPTED.value,
            TaskStatus.WORKER_ON_THE_WAY.value,
        }
        if task.status not in cancellable:
            raise InvalidTransitionException(
                f"A task in {task.status} cannot be cancelled."
            )
        is_customer = actor.role == UserRole.CUSTOMER.value and task.customer_id == actor.id
        is_worker = actor.role == UserRole.WORKER.value and task.assigned_worker_id == actor.id
        is_admin = actor.role == UserRole.ADMIN.value
        if not (is_customer or is_worker or is_admin):
            raise ForbiddenException("You cannot cancel this task.")

        previous = task.status
        task.status = TaskStatus.CANCELLED.value
        task.cancelled_at = datetime.now(timezone.utc)
        task.cancellation_reason = reason
        self._record_history(task, previous, TaskStatus.CANCELLED.value, actor=actor, reason=reason)

        # Stop any in-flight ring-down dispatch for this task.
        dispatch_engine.clear(task.id)

        # Expire outstanding offers/counter-offers, free the worker.
        for offer in self.db.scalars(
            select(TaskOffer).where(TaskOffer.task_id == task.id, TaskOffer.status == "PENDING")
        ):
            offer.status = "EXPIRED"
        self._expire_task_bids(task)
        for assignment in self.db.scalars(
            select(TaskAssignment).where(TaskAssignment.task_id == task.id)
        ):
            assignment.status = "CANCELLED"

        # If this task was the worker's chained next job, release the queue slot.
        if task.assigned_worker_id:
            profile = self.workers.get_worker_profile(task.assigned_worker_id)
            if profile is not None and profile.queued_task_id == task.id:
                profile.queued_task_id = None
        task.worker_confirmed_readiness = False
        RideCheckMonitor(self.db).clear_task(task.id)

        # A worker walking away from a committed task counts against their
        # rolling cancellation rate (which feeds the tier calculation).
        if is_worker:
            try:
                GamificationService(self.db).on_task_cancelled(task)
            except Exception:
                logger.exception("worker_cancellation_count_failed task=%s", task.id)

        # Refund any secured money; unpaid gateway orders are simply cancelled.
        if task.payment_status in ("AUTHORIZED", "CAPTURED", "INITIATED"):
            try:
                self.payment_service.refund_task(task)
            except Exception:
                logger.exception("refund failed for task %s", task.id)
                task.payment_status = "REFUND_FAILED"
        elif task.payment_status == "PENDING":
            task.payment_status = "CANCELLED"

        notify_users_sync(
            [w.user_id for w in self._other_offered_workers(task, exclude=None)],
            notification_type=NotificationType.SYSTEM,
            title="Task cancelled",
            body=f"The task '{task.title}' was cancelled.",
            data={"task_id": task.id},
            db=self.db,
        )
        if task.assigned_worker_id and task.assigned_worker_id != actor.id:
            notify_users_sync(
                [task.assigned_worker_id],
                notification_type=NotificationType.SYSTEM,
                title="Task cancelled",
                body=f"'{task.title}' was cancelled by the customer. Reason: {reason or 'not provided'}",
                data={"task_id": task.id},
                db=self.db,
            )
        self.db.flush()
        return task

    # ------------------------------------------------------------------
    # Scheduled reservations
    # ------------------------------------------------------------------

    def _blacklisted_customer_ids(self, worker_id: str) -> set[str]:
        return set(
            self.db.scalars(
                select(CustomerWorkerAffinity.customer_id).where(
                    CustomerWorkerAffinity.worker_id == worker_id,
                    CustomerWorkerAffinity.affinity_type == AffinityType.BLACKLISTED.value,
                )
            )
        )

    def scheduled_board(self, worker_user: User) -> list[dict]:
        """Upcoming reservation slots a verified worker can claim (T-60+)."""
        profile = self.workers.get_worker_profile(worker_user.id)
        if profile is None:
            raise ForbiddenException("Worker profile missing.")
        if not profile.is_verified:
            raise ForbiddenException("Only verified workers can reserve scheduled tasks.")

        blacklisted = self._blacklisted_customer_ids(worker_user.id)
        now = datetime.now(timezone.utc)
        tasks = self.db.scalars(
            select(Task)
            .where(
                Task.status == TaskStatus.SCHEDULED_OPEN.value,
                Task.is_scheduled.is_(True),
                Task.scheduled_for.is_not(None),
                Task.scheduled_for > now,
            )
            .order_by(Task.scheduled_for.asc())
            .limit(100)
        ).all()

        board: list[dict] = []
        for task in tasks:
            if task.customer_id in blacklisted:
                continue
            distance_km = None
            if (
                profile.latitude is not None
                and profile.longitude is not None
                and task.latitude is not None
                and task.longitude is not None
            ):
                distance_km = round(
                    haversine_km(
                        float(profile.latitude), float(profile.longitude),
                        float(task.latitude), float(task.longitude),
                    ),
                    2,
                )
            board.append(
                {
                    "task_id": task.id,
                    "title": task.title,
                    "task_type": task.task_type,
                    "description": (task.description or "")[:180],
                    "budget": float(task.budget or 0),
                    "currency": task.currency,
                    "city": task.city,
                    "area_name": task.area_name,
                    "address_text": task.address_text,
                    "scheduled_for": task.scheduled_for.isoformat() if task.scheduled_for else None,
                    "estimated_duration_minutes": task.estimated_duration_minutes,
                    "is_round_trip": bool(task.is_round_trip),
                    "distance_km": distance_km,
                }
            )
        return board

    def claim_reservation(self, task: Task, worker_user: User) -> Task:
        """Worker reserves a scheduled slot. The task stays SCHEDULED_ASSIGNED
        until readiness is confirmed and the start time arrives."""
        if task.status != TaskStatus.SCHEDULED_OPEN.value or not task.is_scheduled:
            raise ConflictException("This scheduled task is no longer open for reservations.")
        if task.scheduled_for is not None and as_aware(task.scheduled_for) <= datetime.now(timezone.utc):
            raise ConflictException("This scheduled window has already started.")
        profile = self.workers.get_worker_profile(worker_user.id)
        if profile is None:
            raise ForbiddenException("Worker profile missing.")
        if not profile.is_verified:
            raise ForbiddenException("Only verified workers can reserve scheduled tasks.")
        if profile.queued_task_id is not None:
            raise ConflictException("Finish or release your queued job before reserving a scheduled slot.")
        if task.customer_id in self._blacklisted_customer_ids(worker_user.id):
            raise ForbiddenException("This customer has blocked you from their tasks.")
        active_count = self.tasks.worker_active_task_count(worker_user.id)
        if active_count >= (profile.max_concurrent_tasks or 1):
            raise ConflictException("You are already at your concurrent task limit.")

        if not dispatch_engine.try_acquire_lock(task.id, worker_user.id):
            raise ConflictException("Another worker just reserved this slot.")
        try:
            rate = self.payment_service.commission_rate_for(worker_user.id)
            commission_amount, _payout = self.payment_service.split_for(
                float(task.budget or 0), rate
            )
            now = datetime.now(timezone.utc)
            self.db.add(
                TaskAssignment(
                    task_id=task.id,
                    worker_id=worker_user.id,
                    earnings_amount=task.budget,
                    commission_amount=Decimal(str(commission_amount)),
                    accepted_at=now,
                )
            )
            previous = task.status
            task.assigned_worker_id = worker_user.id
            task.status = TaskStatus.SCHEDULED_ASSIGNED.value
            task.worker_confirmed_readiness = False
            self._record_history(
                task, previous, TaskStatus.SCHEDULED_ASSIGNED.value, actor=worker_user,
                reason="worker reserved the scheduled slot",
            )
            self.payment_service.apply_worker_rate(task)

            notify_users_sync(
                [worker_user.id],
                notification_type=NotificationType.TASK_CONFIRMED,
                title=f"Reservation confirmed: {task.title}",
                body=(
                    "You're booked. Confirm readiness in the app 45 minutes before the start "
                    "time or the slot is released at T-30."
                ),
                data={"task_id": task.id, "scheduled_for": task.scheduled_for.isoformat()
                      if task.scheduled_for else None},
                link="/worker/reserved",
                db=self.db,
            )
            notify_users_sync(
                [task.customer_id],
                notification_type=NotificationType.WORKER_FOUND,
                title=f"Scheduled worker booked: {task.title}",
                body=f"{worker_user.full_name} reserved your scheduled task. "
                     f"You'll get another confirmation once they confirm readiness.",
                data={"task_id": task.id},
                link=f"/customer/tasks/{task.id}",
                db=self.db,
            )
            self._broadcast_task_status(task)
            self.db.flush()
            logger.info("reservation_claimed task=%s worker=%s", task.id, worker_user.id)
            return task
        except Exception:
            dispatch_engine.release_lock(task.id)
            raise

    def confirm_readiness(self, task: Task, worker_user: User) -> Task:
        """Worker confirms they will be available for the reserved slot."""
        if task.status != TaskStatus.SCHEDULED_ASSIGNED.value:
            raise InvalidTransitionException("This reservation is not awaiting readiness confirmation.")
        if task.assigned_worker_id != worker_user.id:
            raise ForbiddenException("You are not assigned to this reservation.")
        if task.worker_confirmed_readiness:
            return task

        task.worker_confirmed_readiness = True
        self.db.flush()
        notify_users_sync(
            [worker_user.id],
            notification_type=NotificationType.SYSTEM,
            title="Readiness confirmed",
            body=f"You're confirmed for '{task.title[:60]}'. Head over at the scheduled time.",
            data={"task_id": task.id},
            link="/worker/reserved",
            db=self.db,
        )
        notify_users_sync(
            [task.customer_id],
            notification_type=NotificationType.WORKER_FOUND,
            title="Your worker confirmed readiness",
            body=f"{worker_user.full_name} is confirmed for '{task.title[:60]}'.",
            data={"task_id": task.id},
            link=f"/customer/tasks/{task.id}",
            db=self.db,
        )

        if task.scheduled_for is not None and as_aware(task.scheduled_for) <= datetime.now(timezone.utc):
            return self.activate_reservation(task, reason="readiness confirmed after the start time")
        self.db.flush()
        return task

    def activate_reservation(self, task: Task, *, reason: str) -> Task:
        """Readiness confirmed + start time reached → the task goes live."""
        if task.status != TaskStatus.SCHEDULED_ASSIGNED.value:
            return task
        previous = task.status
        task.status = TaskStatus.ACCEPTED.value
        self._record_history(
            task, previous, TaskStatus.ACCEPTED.value, reason=reason,
        )
        self.db.flush()

        from app.tracking.service import reset_task_route

        reset_task_route(task.id)
        if task.assigned_worker_id:
            notify_users_sync(
                [task.assigned_worker_id],
                notification_type=NotificationType.SYSTEM,
                title="Your reserved task is ready",
                body=f"'{task.title[:60]}' is scheduled now. Head to the task location.",
                data={"task_id": task.id},
                link="/worker/tasks",
                db=self.db,
            )
            self._notify_customer(
                task,
                notification_type=NotificationType.WORKER_FOUND,
                title="Your scheduled worker is on the way",
                body="Your reserved worker confirmed readiness and is heading to you now.",
            )
        self._broadcast_task_status(task)
        logger.info("reservation_activated task=%s worker=%s", task.id, task.assigned_worker_id)
        return task

    def mark_disputed(self, task: Task) -> None:
        previous = task.status
        task.status = TaskStatus.DISPUTED.value
        self._record_history(task, previous, TaskStatus.DISPUTED.value, reason="dispute opened")

    # ------------------------------------------------------------------
    # Listings
    # ------------------------------------------------------------------

    def list_for_customer(
        self, customer_id: str, status: Optional[str], page: int, page_size: int
    ) -> tuple[list[Task], int]:
        items = self.tasks.tasks_for_customer(customer_id, status=status)
        return paginate(items, page, page_size)

    def list_for_worker(
        self, worker_user: User, status: Optional[str], page: int, page_size: int
    ) -> tuple[list[Task], int]:
        items = self.tasks.tasks_for_worker(worker_user.id)
        return paginate(items, page, page_size)

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _record_history(
        self,
        task: Task,
        from_status: Optional[str],
        to_status: str,
        actor: Optional[User] = None,
        reason: Optional[str] = None,
    ) -> None:
        self.db.add(
            TaskStatusHistory(
                task_id=task.id,
                from_status=from_status,
                to_status=to_status,
                changed_by_id=actor.id if actor else None,
                note=reason,
            )
        )

    def expire_stale_offers(self) -> int:
        """Housekeeping: flip expired PENDING offers to EXPIRED."""
        stale = self.tasks.expired_pending_offers()
        for offer in stale:
            offer.status = "EXPIRED"
        if stale:
            self.db.flush()
        return len(stale)
