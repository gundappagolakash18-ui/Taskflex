"""SOS safety flow: a durable alert, a frozen GPS trail, admin paging, and
resolution that hands the task back to its previous state."""

import asyncio

import pytest

from app.dispatch.engine import dispatch_engine
from app.models import Notification, Task, TaskSosAlert, TaskStatusHistory
from app.tracking import hub

from tests.conftest import auth_headers, make_user, task_payload


@pytest.fixture(autouse=True)
def _clean_tracking_hub():
    def _wipe():
        hub._latest_local.clear()
        hub._history_local.clear()
        hub._subs.clear()

    _wipe()
    yield
    _wipe()


def _accepted_task(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER", skills=("document_submission",))
    created = client.post("/api/v1/tasks", json=task_payload(), headers=auth_headers(customer))
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["task"]["id"]
    confirmed = client.post(f"/api/v1/tasks/{task_id}/confirm", headers=auth_headers(customer))
    assert confirmed.status_code == 200, confirmed.text
    accepted = client.post(f"/api/v1/tasks/{task_id}/accept", headers=auth_headers(worker))
    assert accepted.status_code == 200, accepted.text
    return customer, worker, task_id


def _publish_positions(task_id: str, count: int) -> None:
    for i in range(count):
        asyncio.run(
            hub.publish(
                task_id,
                {
                    "task_id": task_id,
                    "latitude": 15.8497 + i * 0.0001,
                    "longitude": 74.4977,
                    "heading": 90.0,
                    "recorded_at": f"2026-10-14T15:{i:02d}:00+00:00",
                },
            )
        )


def test_worker_sos_freezes_the_gps_ring_and_pages_admins(client, db):
    admin = make_user(db, "ADMIN", full_name="Akash G")
    customer, worker, task_id = _accepted_task(client, db)
    _publish_positions(task_id, 25)

    try:
        res = client.post(
            f"/api/v1/tasks/{task_id}/sos",
            json={"message": "Unsafe area - please check on me."},
            headers=auth_headers(worker),
        )
        assert res.status_code == 201, res.text
        assert res.json()["data"]["alert"]["status"] == "OPEN"

        db.expire_all()
        alert = db.query(TaskSosAlert).filter_by(task_id=task_id).one()
        assert alert.raised_by_id == worker.id
        assert alert.raised_by_role == "WORKER"
        assert alert.previous_status == "ACCEPTED"
        # The ring keeps only the newest 20 fixes; the 25th is the last one.
        assert len(alert.location_history) == 20
        assert alert.location_history[-1]["latitude"] == pytest.approx(15.8497 + 24 * 0.0001)
        assert alert.latitude == pytest.approx(15.8497 + 24 * 0.0001)
        assert alert.message.startswith("Unsafe area")

        task = db.get(Task, task_id)
        assert task.status == "EMERGENCY_ALERT"

        trail = (
            db.query(TaskStatusHistory)
            .filter_by(task_id=task_id)
            .order_by(TaskStatusHistory.created_at)
            .all()
        )
        assert trail[-1].to_status == "EMERGENCY_ALERT"
        assert trail[-1].changed_by_id == worker.id

        assert db.query(Notification).filter_by(user_id=admin.id, type="SOS_TRIGGERED").count() == 1
        assert db.query(Notification).filter_by(user_id=customer.id, type="SOS_TRIGGERED").count() == 1
    finally:
        dispatch_engine.clear(task_id)


def test_second_sos_on_the_same_task_is_rejected(client, db):
    _, worker, task_id = _accepted_task(client, db)
    try:
        first = client.post(f"/api/v1/tasks/{task_id}/sos", json={}, headers=auth_headers(worker))
        assert first.status_code == 201, first.text
        second = client.post(f"/api/v1/tasks/{task_id}/sos", json={}, headers=auth_headers(worker))
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "CONFLICT"
        assert db.query(TaskSosAlert).filter_by(task_id=task_id).count() == 1
    finally:
        dispatch_engine.clear(task_id)


def test_non_participant_cannot_raise_sos(client, db):
    outsider = make_user(db, "WORKER", full_name="Outsider")
    _, _, task_id = _accepted_task(client, db)
    try:
        res = client.post(f"/api/v1/tasks/{task_id}/sos", json={}, headers=auth_headers(outsider))
        assert res.status_code == 404
    finally:
        dispatch_engine.clear(task_id)


def test_sos_is_rejected_on_a_closed_task(client, db):
    customer, _, task_id = _accepted_task(client, db)
    try:
        task = db.get(Task, task_id)
        task.status = "COMPLETED"
        db.commit()

        res = client.post(f"/api/v1/tasks/{task_id}/sos", json={}, headers=auth_headers(customer))
        assert res.status_code == 409
    finally:
        dispatch_engine.clear(task_id)


def test_admin_lists_and_resolves_the_alert_restoring_the_task(client, db):
    admin = make_user(db, "ADMIN", full_name="Akash G")
    _, worker, task_id = _accepted_task(client, db)
    try:
        triggered = client.post(
            f"/api/v1/tasks/{task_id}/sos", json={}, headers=auth_headers(worker)
        )
        assert triggered.status_code == 201, triggered.text
        alert_id = triggered.json()["data"]["alert"]["id"]

        listed = client.get(
            "/api/v1/admin/sos-alerts?status=OPEN", headers=auth_headers(admin)
        )
        assert listed.status_code == 200, listed.text
        assert alert_id in [item["id"] for item in listed.json()["data"]["items"]]

        not_admin = client.get(
            f"/api/v1/admin/sos-alerts?status=OPEN", headers=auth_headers(worker)
        )
        assert not_admin.status_code == 403

        resolved = client.post(
            f"/api/v1/admin/sos-alerts/{alert_id}/resolve",
            json={"note": "Called the worker; they are safe."},
            headers=auth_headers(admin),
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["data"]["alert"]["status"] == "RESOLVED"
        assert resolved.json()["data"]["alert"]["resolution_note"] == "Called the worker; they are safe."

        db.expire_all()
        assert db.get(Task, task_id).status == "ACCEPTED"
        alert = db.get(TaskSosAlert, alert_id)
        assert alert.resolved_by_id == admin.id
        assert alert.resolved_at is not None

        again = client.post(
            f"/api/v1/admin/sos-alerts/{alert_id}/resolve",
            json={"note": "second attempt"},
            headers=auth_headers(admin),
        )
        assert again.status_code == 409
    finally:
        dispatch_engine.clear(task_id)
