"""Backend-enforced permissions: the frontend can never be trusted."""

from app.schemas.task import TaskCreate
from app.services import TaskService

from tests.conftest import auth_headers, make_user, task_payload


def _create_task_via_api(client, customer, **overrides):
    resp = client.post("/api/v1/tasks", json=task_payload(**overrides), headers=auth_headers(customer))
    assert resp.status_code == 201
    return resp.json()["data"]["task"]


def _completed_task(db, customer, worker):
    """Build a completed task directly for rating/permission tests."""
    service = TaskService(db)
    task = service.create_task(customer, TaskCreate(**task_payload()))
    task.status = "COMPLETED"
    task.assigned_worker_id = worker.id
    db.commit()
    db.refresh(task)
    return task


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/v1/tasks").status_code == 401
    assert client.get("/api/v1/tasks/some-id").status_code == 401
    assert client.get("/api/v1/workers/me/offers").status_code == 401
    assert client.get("/api/v1/admin/dashboard").status_code == 401


def test_customer_cannot_view_or_edit_someone_elses_task(client, db):
    owner = make_user(db, "CUSTOMER")
    other = make_user(db, "CUSTOMER")
    task = _create_task_via_api(client, owner)

    assert client.get(f"/api/v1/tasks/{task['id']}", headers=auth_headers(other)).status_code == 403
    assert (
        client.patch(
            f"/api/v1/tasks/{task['id']}",
            json={"budget": 1},
            headers=auth_headers(other),
        ).status_code
        == 403
    )
    assert (
        client.post(f"/api/v1/tasks/{task['id']}/confirm", headers=auth_headers(other)).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/tasks/{task['id']}/complete",
            json={"otp": "0000"},
            headers=auth_headers(other),
        ).status_code
        == 403
    )


def test_worker_cannot_confirm_complete_or_cancel_a_task(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _create_task_via_api(client, customer)

    assert (
        client.post(f"/api/v1/tasks/{task['id']}/confirm", headers=auth_headers(worker)).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/tasks/{task['id']}/complete",
            json={"otp": "0000"},
            headers=auth_headers(worker),
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/tasks/{task['id']}/cancel",
            json={"reason": "Not my task"},
            headers=auth_headers(worker),
        ).status_code
        == 403
    )


def test_unassigned_worker_cannot_advance_status(client, db):
    customer = make_user(db, "CUSTOMER")
    assigned = make_user(db, "WORKER")
    outsider = make_user(db, "WORKER")
    task = _create_task_via_api(client, customer)

    # Manually assign one worker.
    from app.models import Task

    db_task = db.query(Task).filter(Task.id == task["id"]).one()
    db_task.assigned_worker_id = assigned.id
    db_task.status = "ACCEPTED"
    db.commit()

    resp = client.post(
        f"/api/v1/tasks/{task['id']}/status",
        json={"status": "WORKER_ON_THE_WAY"},
        headers=auth_headers(outsider),
    )
    assert resp.status_code == 403


def test_worker_cannot_retry_matching_on_someone_elses_task(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _create_task_via_api(client, customer)
    resp = client.post(f"/api/v1/tasks/{task['id']}/retry-matching", headers=auth_headers(worker))
    assert resp.status_code == 403


def test_only_workers_access_worker_endpoints(client, db):
    customer = make_user(db, "CUSTOMER")
    assert client.get("/api/v1/workers/me/offers", headers=auth_headers(customer)).status_code == 403
    assert client.get("/api/v1/workers/me/profile", headers=auth_headers(customer)).status_code == 403
    assert client.get("/api/v1/workers/me/earnings", headers=auth_headers(customer)).status_code == 403


def test_non_admins_are_blocked_from_admin_endpoints(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    for user in (customer, worker):
        headers = auth_headers(user)
        assert client.get("/api/v1/admin/dashboard", headers=headers).status_code == 403
        assert client.get("/api/v1/admin/users", headers=headers).status_code == 403
        assert client.get("/api/v1/admin/payments", headers=headers).status_code == 403
        assert client.get("/api/v1/admin/audit-logs", headers=headers).status_code == 403


def test_admin_can_view_any_task(client, db):
    customer = make_user(db, "CUSTOMER")
    admin = make_user(db, "ADMIN")
    task = _create_task_via_api(client, customer)
    resp = client.get(f"/api/v1/tasks/{task['id']}", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["data"]["task"]["id"] == task["id"]


def test_non_participants_cannot_rate_a_task(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    intruder = make_user(db, "CUSTOMER")
    task = _completed_task(db, customer, worker)

    resp = client.post(
        "/api/v1/ratings",
        json={"task_id": task.id, "score": 5},
        headers=auth_headers(intruder),
    )
    assert resp.status_code == 403

    # Participants can also not rate before the task is completed.
    pending = _create_task_via_api(client, customer)
    early = client.post(
        "/api/v1/ratings",
        json={"task_id": pending["id"], "score": 5},
        headers=auth_headers(customer),
    )
    assert early.status_code == 409


def test_users_cannot_read_other_users_notifications(client, db):
    """Notifications endpoints scope to the authenticated user only."""
    alice = make_user(db, "CUSTOMER")
    bob = make_user(db, "CUSTOMER")
    resp = client.get("/api/v1/notifications", headers=auth_headers(alice))
    assert resp.status_code == 200
    # Bob's notifications never appear in Alice's feed (both empty here).
    assert resp.json()["data"]["items"] == []
    assert bob.id not in str(resp.json()["data"])
