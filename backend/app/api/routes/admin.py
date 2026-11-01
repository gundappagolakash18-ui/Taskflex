from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.api.serializers import serialize_sos_alert, serialize_task, serialize_worker
from app.db.session import get_db
from app.core.exceptions import NotFoundException
from app.core.responses import success_response
from app.models import RideCheckEvent, Task, User
from app.schemas.admin import (
    AnalyticsResponse,
    AuditLogOut,
    DashboardMetrics,
    SosResolveRequest,
    SystemSettingsUpdate,
)
from app.schemas.payment import PaymentOut
from app.schemas.user import TransactionOut
from app.schemas.worker import DocumentOut
from app.services import AdminService, AnalyticsService, RideCheckMonitor, SafetyService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/dashboard")
def dashboard(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    metrics: DashboardMetrics = service.dashboard_metrics()
    return success_response({"metrics": metrics.model_dump()})


@router.get("/analytics")
def analytics(
    days: int = Query(30, ge=7, le=90),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AnalyticsService(db)
    payload: AnalyticsResponse = service.analytics(days=days)
    return success_response(payload.model_dump(mode="json"))


# ---------- users ----------


@router.get("/users")
def list_users(
    role: str | None = None,
    search: str | None = None,
    is_active: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    items, total = service.list_users(
        role=role, search=search, is_active=is_active, page=page, page_size=page_size
    )
    from app.schemas.user import UserOut

    return success_response(
        {
            "items": [UserOut.model_validate(u).model_dump(mode="json") for u in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.patch("/users/{user_id}/status")
def set_user_status(
    user_id: str,
    is_active: bool,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    user = service.set_user_active(admin, user_id, is_active)
    from app.schemas.user import UserOut

    return success_response(
        {"user": UserOut.model_validate(user).model_dump(mode="json")},
        message="Account deactivated." if not is_active else "Account reactivated.",
    )


# ---------- worker verification ----------


@router.get("/verifications/pending")
def pending_verifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    items, total = service.pending_verifications(page, page_size)

    def doc_dict(d):
        out = DocumentOut.model_validate(d).model_dump(mode="json")
        out["id"] = d.id
        out["worker_user_id"] = d.worker.user_id if d.worker else None
        out["worker_name"] = d.worker.user.full_name if d.worker and d.worker.user else None
        return out

    return success_response({"items": [doc_dict(d) for d in items], "total": total})


@router.post("/verifications/{document_id}/decision")
def decide_verification(
    document_id: str,
    approve: bool,
    reason: str | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    doc = service.decide_verification(admin, document_id, approve=approve, reason=reason)
    return success_response(
        {"document": DocumentOut.model_validate(doc).model_dump(mode="json")},
        message="Document approved." if approve else "Document rejected.",
    )


# ---------- workers ----------


@router.get("/workers")
def list_workers(
    search: str | None = None,
    verified: bool | None = None,
    online: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    items, total = service.list_workers(
        search=search, verified=verified, online=online, page=page, page_size=page_size
    )
    return success_response(
        {
            "items": [serialize_worker(w) for w in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


# ---------- tasks ----------


@router.get("/tasks")
def list_tasks(
    status: str | None = None,
    task_type: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    items, total = service.list_tasks(
        status=status, task_type=task_type, search=search, page=page, page_size=page_size
    )
    return success_response(
        {
            "items": [serialize_task(t) for t in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/tasks/{task_id}/cancel")
def admin_cancel_task(
    task_id: str,
    reason: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    task = service.admin_cancel_task(admin, task_id, reason)
    return success_response({"task": serialize_task(task)}, message="Task cancelled by admin.")


# ---------- payments / transactions ----------


@router.get("/payments")
def list_payments(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    items, total = service.list_payments(page, page_size, status=status)
    return success_response(
        {
            "items": [PaymentOut.model_validate(p).model_dump(mode="json") for p in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/transactions")
def list_transactions(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    items, total = service.list_transactions(page=page, page_size=page_size, search=search)
    return success_response(
        {
            "items": [TransactionOut.model_validate(t).model_dump(mode="json") for t in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


# ---------- settings / audit ----------


@router.get("/settings")
def get_settings(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    service = AdminService(db)
    settings_map = service.all_settings()
    items = [
        {"key": key, "value": v.get("value"), "value_type": v.get("value_type", "string"),
         "description": v.get("description")}
        for key, v in settings_map.items()
    ]
    return success_response({"items": items})


@router.put("/settings")
def update_settings(
    payload: SystemSettingsUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    for key, value in payload.settings.items():
        service.update_setting(admin, key, str(value))
    return success_response({"updated": len(payload.settings)}, message="Settings saved.")


@router.get("/audit-logs")
def audit_logs(
    action: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = AdminService(db)
    items, total = service.audit_logs(page=page, page_size=page_size, action=action)
    return success_response(
        {
            "items": [AuditLogOut.model_validate(a).model_dump(mode="json") for a in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


# ---------- emergency (SOS) alerts ----------


@router.get("/sos-alerts")
def list_sos_alerts(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = SafetyService(db)
    items, total = service.list_alerts(status=status, page=page, page_size=page_size)
    return success_response(
        {
            "items": [serialize_sos_alert(a) for a in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/sos-alerts/{alert_id}/resolve")
def resolve_sos_alert(
    alert_id: str,
    payload: SosResolveRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = SafetyService(db)
    alert = service.get_alert_or_404(alert_id)
    alert = service.resolve_alert(alert, admin, payload.note)
    AdminService(db).audit.log(
        user_id=admin.id,
        action="sos_resolved",
        entity_type="task",
        entity_id=alert.task_id,
        metadata_json={"alert_id": alert.id, "note": alert.resolution_note},
    )
    return success_response(
        {"alert": serialize_sos_alert(alert)}, message="Emergency alert resolved."
    )


# ---------- RideCheck safety incidents ----------


@router.get("/ridecheck")
def list_ridecheck_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Incidents escalated by workers or auto-flagged after 120 s without an
    acknowledgement."""
    monitor = RideCheckMonitor(db)
    items, total = monitor.flagged_events(page=page, page_size=page_size)
    payload = []
    for event in items:
        data = monitor.serialize(event)
        task = db.get(Task, event.task_id)
        worker = db.get(User, event.worker_id)
        data["task_title"] = task.title if task else None
        data["worker_name"] = worker.full_name if worker else None
        payload.append(data)
    return success_response(
        {"items": payload, "total": total, "page": page, "page_size": page_size}
    )


@router.post("/ridecheck/{event_id}/resolve")
def resolve_ridecheck_event(
    event_id: str,
    note: str | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    event = db.get(RideCheckEvent, event_id)
    if event is None:
        raise NotFoundException("RideCheck alert not found.")
    data = RideCheckMonitor(db).admin_resolve(event, admin, note)
    AdminService(db).audit.log(
        user_id=admin.id,
        action="ridecheck_resolved",
        entity_type="task",
        entity_id=event.task_id,
        metadata_json={"event_id": event.id, "note": note},
    )
    return success_response({"event": data}, message="RideCheck incident resolved.")
