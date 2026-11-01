"""Admin analytics: the daily series and metrics the reports screen needs."""

from datetime import datetime, timezone

from app.models import Task
from tests.conftest import auth_headers, make_user, task_payload


def _task(db, customer, worker, *, status: str, completed_at=None) -> Task:
    payload = task_payload()
    task = Task(
        customer_id=customer.id,
        title=payload["title"],
        description=payload["description"],
        task_type=payload["task_type"],
        status=status,
        urgency=payload["urgency"],
        latitude=payload["latitude"],
        longitude=payload["longitude"],
        address_text=payload["address_text"],
        area_name=payload["area_name"],
        city=payload["city"],
        budget=payload["budget"],
        assigned_worker_id=worker.id,
        completed_at=completed_at,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_admin_analytics_series_and_metrics(client, db):
    admin = make_user(db, "ADMIN", full_name="Akash G")
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    _task(db, customer, worker, status="COMPLETED", completed_at=datetime.now(timezone.utc))
    _task(db, customer, worker, status="IN_PROGRESS")

    response = client.get(
        "/api/v1/admin/analytics?days=7", headers=auth_headers(admin)
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    for key in ("dau", "mau", "tasks_created", "tasks_completed"):
        assert len(data[key]) == 7, key
    assert data["tasks_created"][-1]["value"] == 2
    assert data["tasks_completed"][-1]["value"] == 1
    assert data["metrics"]["completed_tasks"] == 1
    assert data["metrics"]["active_tasks"] == 1

    forbidden = client.get(
        "/api/v1/admin/analytics?days=7", headers=auth_headers(customer)
    )
    assert forbidden.status_code == 403
