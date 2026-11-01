"""Task CRUD basics. Dispatch must NEVER happen on create — that is the core
TaskFlex safety rule, asserted here at the database level."""

from app.models import Task, TaskOffer

from tests.conftest import auth_headers, make_user, task_payload


def _create_task(client, customer, **overrides):
    resp = client.post("/api/v1/tasks", json=task_payload(**overrides), headers=auth_headers(customer))
    assert resp.status_code == 201
    return resp.json()["data"]["task"]


def test_create_task_lands_in_pending_confirmation(client, db):
    customer = make_user(db, "CUSTOMER")
    task = _create_task(client, customer)

    assert task["status"] == "PENDING_CONFIRMATION"
    assert task["assigned_worker_id"] is None
    assert task["payment_status"] == "PENDING"
    assert task["budget"] == 350
    assert any(r["skill_name"] == "document_submission" for r in task["requirements"])

    # Nothing dispatched: no offers exist for this task.
    assert db.query(TaskOffer).filter(TaskOffer.task_id == task["id"]).count() == 0


def test_create_task_validation_errors(client, db):
    customer = make_user(db, "CUSTOMER")
    assert client.post(
        "/api/v1/tasks", json=task_payload(budget=0), headers=auth_headers(customer)
    ).status_code == 422
    assert client.post(
        "/api/v1/tasks", json=task_payload(title="hi"), headers=auth_headers(customer)
    ).status_code == 422
    assert client.post(
        "/api/v1/tasks",
        json=task_payload(description="too short"),
        headers=auth_headers(customer),
    ).status_code == 422


def test_worker_cannot_create_tasks(client, db):
    worker = make_user(db, "WORKER")
    resp = client.post("/api/v1/tasks", json=task_payload(), headers=auth_headers(worker))
    assert resp.status_code == 403


def test_create_requires_authentication(client):
    assert client.post("/api/v1/tasks", json=task_payload()).status_code == 401


def test_owner_can_view_other_customer_cannot(client, db):
    customer = make_user(db, "CUSTOMER")
    intruder = make_user(db, "CUSTOMER")
    task = _create_task(client, customer)

    ok = client.get(f"/api/v1/tasks/{task['id']}", headers=auth_headers(customer))
    assert ok.status_code == 200
    assert ok.json()["data"]["task"]["status_history"][0]["to_status"] == "PENDING_CONFIRMATION"

    forbidden = client.get(f"/api/v1/tasks/{task['id']}", headers=auth_headers(intruder))
    assert forbidden.status_code == 403


def test_unknown_task_404(client, db):
    customer = make_user(db, "CUSTOMER")
    resp = client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000", headers=auth_headers(customer))
    assert resp.status_code == 404


def test_list_tasks_returns_only_own(client, db):
    alice = make_user(db, "CUSTOMER")
    bob = make_user(db, "CUSTOMER")
    _create_task(client, alice)
    _create_task(client, alice)
    _create_task(client, bob)

    resp = client.get("/api/v1/tasks", headers=auth_headers(alice))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 2
    assert all(item["id"] for item in data["items"])

    bob_resp = client.get("/api/v1/tasks", headers=auth_headers(bob))
    assert bob_resp.json()["data"]["total"] == 1


def test_owner_can_edit_task(client, db):
    customer = make_user(db, "CUSTOMER")
    task = _create_task(client, customer)

    resp = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"title": "Updated: deliver documents to sub-registrar office", "budget": 400},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]["task"]
    assert data["budget"] == 400
    assert data["title"].startswith("Updated:")

    saved = db.query(Task).filter(Task.id == task["id"]).one()
    assert float(saved.budget) == 400


def test_other_customer_cannot_edit_task(client, db):
    owner = make_user(db, "CUSTOMER")
    intruder = make_user(db, "CUSTOMER")
    task = _create_task(client, owner)

    resp = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"budget": 1},
        headers=auth_headers(intruder),
    )
    assert resp.status_code == 403


def test_cancel_task_sets_reason_and_status(client, db):
    customer = make_user(db, "CUSTOMER")
    task = _create_task(client, customer)

    resp = client.post(
        f"/api/v1/tasks/{task['id']}/cancel",
        json={"reason": "Plans changed, no longer needed."},
        headers=auth_headers(customer),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]["task"]
    assert data["status"] == "CANCELLED"
    assert data["cancellation_reason"] == "Plans changed, no longer needed."
    assert data["cancelled_at"] is not None


def test_cancel_requires_reason(client, db):
    customer = make_user(db, "CUSTOMER")
    task = _create_task(client, customer)
    resp = client.post(
        f"/api/v1/tasks/{task['id']}/cancel", json={"reason": ""}, headers=auth_headers(customer)
    )
    assert resp.status_code == 422


def test_status_filter_on_list(client, db):
    customer = make_user(db, "CUSTOMER")
    _create_task(client, customer)

    resp = client.get("/api/v1/tasks?status=COMPLETED", headers=auth_headers(customer))
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0

    resp = client.get("/api/v1/tasks?status=PENDING_CONFIRMATION", headers=auth_headers(customer))
    assert resp.json()["data"]["total"] == 1
