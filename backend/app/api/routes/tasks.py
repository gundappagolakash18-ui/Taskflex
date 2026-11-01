from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_customer, require_worker
from app.api.serializers import (
    serialize_execution_proof,
    serialize_sos_alert,
    serialize_status_history,
    serialize_task,
    serialize_task_expense,
    serialize_worker,
)
from app.db.session import get_db
from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.core.responses import success_response
from app.matching.engine import MatchingEngine
from app.matching.config import get_matching_config
from app.models import RideCheckEvent, TaskOffer, TaskStatusHistory, User, WorkerProfile
from app.schemas.marketplace import ReadinessConfirmRequest, RideCheckAckRequest, TipRequest
from app.schemas.task import (
    CancelTaskRequest,
    FareEstimateRequest,
    OtpVerifyRequest,
    SosTriggerRequest,
    TaskCompleteRequest,
    TaskCreate,
    TaskParseRequest,
    TaskStatusUpdate,
    TaskUpdate,
)
from app.services import (
    ExecutionService,
    PaymentService,
    RideCheckMonitor,
    SafetyService,
    TaskService,
)
from app.services.pricing_engine import BELOW_FLOOR_HINT, PricingEngine
from app.tracking import hub
from app.tracking.service import route_for_task, tracking_destination, tracking_snapshot

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/parse")
def parse_task_text(
    payload: TaskParseRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI interpretation only — nothing is saved, nothing is dispatched."""
    service = TaskService(db)
    draft = service.parse_request(payload.text)
    return success_response(
        {"draft": draft.model_dump(mode="json")},
        message="Here is how I understood your request. Please review and confirm.",
    )


@router.post("/estimate-fare")
async def estimate_fare(
    payload: FareEstimateRequest,
    user: User = Depends(require_customer),
):
    """Dynamic fare floor preview — road distance via OSRM when both points
    are given. Informational only; the floor is enforced at confirmation."""
    engine = PricingEngine()
    origin = (
        (payload.origin_latitude, payload.origin_longitude)
        if payload.origin_latitude is not None and payload.origin_longitude is not None
        else None
    )
    destination = (
        (payload.destination_latitude, payload.destination_longitude)
        if payload.destination_latitude is not None and payload.destination_longitude is not None
        else None
    )
    quote = await engine.estimate(
        origin=origin,
        destination=destination,
        wait_minutes=payload.wait_minutes,
        urgency=payload.urgency.value,
        is_round_trip=payload.is_round_trip,
    )

    warning = None
    if payload.proposed_budget is not None:
        budget = float(payload.proposed_budget)
        if budget < quote.minimum_fare:
            warning = {
                "code": "BELOW_MINIMUM_FLOOR",
                "your_budget": round(budget, 2),
                "message": (
                    f"Tasks priced below ₹{quote.minimum_fare:.0f} are rejected — "
                    f"your budget of ₹{budget:.0f} is below the minimum fare."
                ),
            }
        elif budget < quote.recommended_fare:
            warning = {
                "code": "BELOW_RECOMMENDED",
                "your_budget": round(budget, 2),
                "message": (
                    f"Tasks priced below ₹{quote.recommended_fare:.0f} experience a 94% "
                    f"rejection rate by nearby workers. {BELOW_FLOOR_HINT}"
                ),
            }

    return success_response(
        {
            "estimate": {
                "currency": quote.currency,
                "minimum_fare": quote.minimum_fare,
                "recommended_fare": quote.recommended_fare,
                "breakdown": quote.to_dict(),
            },
            "warning": warning,
        },
        message="Fare estimate ready.",
    )


@router.post("", status_code=201)
def create_task(
    payload: TaskCreate,
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    task = service.create_task(user, payload)
    return success_response(
        {"task": serialize_task(task)},
        message="Task saved. It will only search for workers after you confirm it.",
        status_code=201,
    )


@router.get("")
def list_tasks(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    if user.role == "ADMIN":
        items, total = service.tasks.search_admin(status=status, page=page, page_size=page_size)
    elif user.role == "WORKER":
        items, total = service.list_for_worker(user, status=status, page=page, page_size=page_size)
    else:
        items, total = service.list_for_customer(user.id, status=status, page=page, page_size=page_size)
    profiles = {}
    if user.role != "CUSTOMER":
        worker_ids = {t.assigned_worker_id for t in items if t.assigned_worker_id}
        if worker_ids:
            rows = db.query(WorkerProfile).filter(WorkerProfile.user_id.in_(worker_ids)).all()
            profiles = {p.user_id: p for p in rows}
    data = [serialize_task(t, worker_profile=profiles.get(t.assigned_worker_id)) for t in items]
    return success_response({"items": data, "total": total, "page": page, "page_size": page_size})


@router.get("/{task_id}")
def get_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    service.assert_can_view(task, user)

    my_offer_status = None
    if user.role == "WORKER":
        offer = (
            db.query(TaskOffer)
            .filter(TaskOffer.task_id == task.id, TaskOffer.worker_id == user.id)
            .order_by(TaskOffer.created_at.desc())
            .first()
        )
        my_offer_status = offer.status if offer else None

    worker_profile = None
    if task.assigned_worker_id:
        worker_profile = (
            db.query(WorkerProfile).filter(WorkerProfile.user_id == task.assigned_worker_id).one_or_none()
        )

    history = (
        db.query(TaskStatusHistory)
        .filter(TaskStatusHistory.task_id == task.id)
        .order_by(TaskStatusHistory.created_at)
        .all()
    )
    data = serialize_task(task, worker_profile=worker_profile, my_offer_status=my_offer_status,
                          viewer=user)
    data["status_history"] = serialize_status_history(history)

    is_participant = (
        user.role == "ADMIN" or task.customer_id == user.id or task.assigned_worker_id == user.id
    )
    if is_participant:
        execution = ExecutionService(db)
        data["execution_proofs"] = [
            serialize_execution_proof(p) for p in execution.list_proofs(task)
        ]
        data["expenses"] = [serialize_task_expense(e) for e in execution.list_expenses(task)]
        data["expense_totals"] = execution.expense_totals(task)
    else:
        data["execution_proofs"] = []
        data["expenses"] = []
        data["expense_totals"] = None
    return success_response({"task": data})


@router.get("/{task_id}/tracking")
async def get_task_tracking(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Live tracking snapshot: OSRM route polyline, latest worker position,
    ETA and remaining distance. Only the customer, assigned worker or admin."""
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    service.assert_can_view(task, user)
    snapshot = await tracking_snapshot(db, task)
    return success_response({"tracking": snapshot})


@router.get("/{task_id}/matches")
def task_matches(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Preview of ranked workers. Visible to the task owner and admins."""
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    if user.role != "ADMIN" and task.customer_id != user.id:
        raise ForbiddenException("Only the task owner can view matching results.")

    from app.schemas.task import MatchBreakdown, MatchOut

    engine = MatchingEngine(config=get_matching_config())
    eligible = engine.find_eligible_workers(db, task)
    ranked = engine.rank_workers(db, task, eligible)[:10]
    matches = []
    for result in ranked:
        matches.append(
            MatchOut(
                worker=serialize_worker(result.worker),
                breakdown=MatchBreakdown(
                    distance=result.scores.get("distance", 0),
                    skill_match=result.scores.get("skill_match", 0),
                    availability=result.scores.get("availability", 0),
                    rating=result.scores.get("rating", 0),
                    reliability=result.scores.get("reliability", 0),
                    workload=result.scores.get("workload", 0),
                    final_score=result.final_score,
                    distance_km=result.scores.get("distance_km", 0),
                ).model_dump(),
            ).model_dump(mode="json")
        )
    return success_response({"matches": matches, "eligible_count": len(eligible)})


@router.patch("/{task_id}")
def update_task(
    task_id: str,
    payload: TaskUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    if task.customer_id != user.id:
        raise ForbiddenException("Only the task owner can edit this task.")
    task = service.update_task(task, payload)
    return success_response({"task": serialize_task(task)}, message="Task updated.")


@router.post("/{task_id}/confirm")
async def confirm_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The explicit user confirmation gate — no dispatch ever happens without
    this. Budgets below the dynamic fare floor are rejected here."""
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    await service.enforce_fare_floor(task)
    task = await run_in_threadpool(service.confirm_task, task, user)
    return success_response(
        {"task": serialize_task(task, viewer=user)},
        message="Task confirmed! We are now matching it with nearby workers.",
    )


@router.post("/{task_id}/accept")
def accept_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Worker accepts the task they were offered (ring-down or surge)."""
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    offer = (
        db.query(TaskOffer)
        .filter(
            TaskOffer.task_id == task.id,
            TaskOffer.worker_id == user.id,
            TaskOffer.status == "PENDING",
        )
        .order_by(TaskOffer.created_at.desc())
        .first()
    )
    if offer is None:
        raise ConflictException("You have no pending offer for this task.")
    task = service.accept_offer(offer, user)
    return success_response(
        {"task": serialize_task(task, viewer=user)},
        message="Offer accepted! Head to the task location as planned.",
    )


@router.post("/{task_id}/reject")
def reject_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Worker declines the task — the engine rings the next candidate."""
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    offer = (
        db.query(TaskOffer)
        .filter(
            TaskOffer.task_id == task.id,
            TaskOffer.worker_id == user.id,
            TaskOffer.status == "PENDING",
        )
        .order_by(TaskOffer.created_at.desc())
        .first()
    )
    if offer is None:
        raise ConflictException("You have no pending offer for this task.")
    service.reject_offer(offer, user)
    return success_response({"rejected": True}, message="Offer declined.")


@router.post("/{task_id}/status")
def update_task_status(
    task_id: str,
    payload: TaskStatusUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    task = service.worker_status_update(task, user, payload.status)
    return success_response({"task": serialize_task(task)}, message=f"Status updated to {payload.status}.")


@router.post("/{task_id}/verify-start-otp")
def verify_start_otp(
    task_id: str,
    payload: OtpVerifyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Worker at the task location enters the start code: ARRIVED_AT_LOCATION → IN_PROGRESS."""
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    task = service.verify_start_otp(task, user, payload.otp)
    return success_response(
        {"task": serialize_task(task, viewer=user)},
        message="Start code verified — the task is now IN_PROGRESS.",
    )


@router.post("/{task_id}/sos", status_code=201)
async def trigger_sos(
    task_id: str,
    payload: SosTriggerRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Emergency trigger (customer or assigned worker): freezes the last 20
    GPS fixes as evidence, flips the task to EMERGENCY_ALERT, and pages every
    admin over WebSocket."""
    task = TaskService(db).get_task_or_404(task_id)
    frozen = await hub.history(task_id)
    service = SafetyService(db)
    alert = await run_in_threadpool(
        service.trigger_sos,
        task,
        user,
        location_history=frozen,
        latitude=payload.latitude if payload else None,
        longitude=payload.longitude if payload else None,
        message=payload.message if payload else None,
    )
    return success_response(
        {"alert": serialize_sos_alert(alert), "task": serialize_task(task, viewer=user)},
        message="Emergency alert raised — support has been notified.",
        status_code=201,
    )


@router.post("/{task_id}/request-completion")
def request_completion(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Worker finished the work (proof photos required): IN_PROGRESS → COMPLETION_REQUESTED.
    The completion code is then shown to the customer."""
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    task = service.request_completion(task, user)
    return success_response(
        {"task": serialize_task(task, viewer=user)},
        message="Completion requested. Ask your customer for the completion code.",
    )


@router.post("/{task_id}/complete")
def complete_with_otp(
    task_id: str,
    payload: TaskCompleteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Worker submits the completion code the customer read out:
    COMPLETION_REQUESTED → COMPLETED and the escrow is released."""
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    task = service.complete_with_otp(task, user, payload.otp)
    return success_response(
        {"task": serialize_task(task, viewer=user)},
        message="Completion code verified — payment released to the worker. Thank you!",
    )


@router.post("/{task_id}/verify-return-otp")
def verify_return_otp(
    task_id: str,
    payload: OtpVerifyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Round-trip handback: worker enters the customer's return code once the
    goods are back at the pickup origin."""
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    task = service.verify_return_otp(task, user, payload.otp)
    return success_response(
        {"task": serialize_task(task, viewer=user)},
        message="Return handback confirmed — you can now close the task.",
    )


@router.post("/{task_id}/tip")
def tip_task(
    task_id: str,
    payload: TipRequest,
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """100% of a tip goes to the worker (no commission). Post-completion tips
    settle immediately; in-flight tips are escrowed until completion."""
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    payment, checkout = PaymentService(db).tip(task, user, payload.amount)
    settled = payment.status == "CAPTURED"
    data = {
        "tip": {
            "task_id": task.id,
            "amount": float(payment.amount),
            "status": payment.status,
            "settled": settled,
        },
        "payment": checkout,
    }
    return success_response(
        data,
        message=(
            "Tip sent — the worker received 100% of it."
            if settled
            else "Tip recorded. Complete the payment checkout to send it."
        ),
    )


# ---------------------------------------------------------------------------
# Scheduled reservations
# ---------------------------------------------------------------------------


@router.post("/{task_id}/claim-reservation")
def claim_reservation(
    task_id: str,
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    task = service.claim_reservation(task, user)
    return success_response(
        {"task": serialize_task(task, viewer=user)},
        message="Slot reserved. Confirm readiness 45 minutes before the start time.",
    )


@router.post("/{task_id}/confirm-readiness")
def confirm_readiness(
    task_id: str,
    payload: ReadinessConfirmRequest | None = None,
    user: User = Depends(require_worker),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    task = service.confirm_readiness(task, user)
    return success_response(
        {"task": serialize_task(task, viewer=user)},
        message="Readiness confirmed — the task activates at its scheduled time.",
    )


# ---------------------------------------------------------------------------
# RideCheck safety alerts
# ---------------------------------------------------------------------------


@router.get("/{task_id}/ridecheck")
def ridecheck_events(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    service.assert_can_view(task, user)
    monitor = RideCheckMonitor(db)
    events = monitor.events_for_task(task.id)
    return success_response(
        {
            "active": monitor.active_for_task(task.id),
            "events": [monitor.serialize(e) for e in events],
        }
    )


@router.post("/ridecheck/{event_id}/acknowledge")
async def acknowledge_ridecheck(
    event_id: str,
    payload: RideCheckAckRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Worker responds to a non-dismissible RideCheck banner. SAFE on a route
    deviation rebuilds the OSRM route from the current fix; HELP escalates to
    every admin."""
    event = db.get(RideCheckEvent, event_id)
    if event is None:
        raise NotFoundException("RideCheck alert not found.")
    if event.worker_id != user.id:
        raise ForbiddenException("Only the worker on this task can acknowledge this alert.")
    task = TaskService(db).get_task_or_404(event.task_id)
    if (
        payload.action == "SAFE"
        and event.type == "ROUTE_DEVIATION"
        and event.latitude is not None
        and event.longitude is not None
    ):
        await route_for_task(
            task.id,
            (float(event.latitude), float(event.longitude)),
            tracking_destination(task),
            force=True,
        )
    data = RideCheckMonitor(db).acknowledge(
        event, user, action=payload.action, reason=payload.reason
    )
    return success_response(
        {"event": data},
        message=(
            "Help requested — the safety team has been alerted."
            if payload.action == "HELP"
            else "Checked in as safe. Your route was refreshed."
        ),
    )


@router.post("/{task_id}/cancel")
def cancel_task(
    task_id: str,
    payload: CancelTaskRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    task = service.cancel_task(task, user, payload.reason)
    return success_response({"task": serialize_task(task)}, message="Task cancelled.")


@router.post("/{task_id}/retry-matching")
def retry_matching(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    task = service.get_task_or_404(task_id)
    if task.customer_id != user.id and user.role != "ADMIN":
        raise ForbiddenException("Only the task owner can retry matching.")
    offered = service.retry_matching(task)
    return success_response(
        {"offers_sent": offered},
        message=f"Matching retried — {offered} new offer(s) sent." if offered
        else "No additional workers matched right now. Try again later.",
    )
