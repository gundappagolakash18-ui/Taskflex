"""Sequential ring-down dispatch: one offer at a time with a 30s countdown,
miss accounting, surge escalation after 3 failures, and the first-accept-wins
lock. Workers here share a location and skill set, so ring order follows
creation order (stable sort on equal scores)."""

from datetime import timedelta

from app.dispatch.engine import (
    OFFER_SECONDS,
    REDISPATCH_COOLDOWN_SECONDS,
    dispatch_engine,
)
from app.core.timeutils import as_aware, utcnow, utcnow_naive
from app.models import TaskOffer, WorkerProfile

from tests.conftest import auth_headers, make_user, task_payload


def _confirmed_task(client, customer) -> str:
    created = client.post("/api/v1/tasks", json=task_payload(), headers=auth_headers(customer))
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["task"]["id"]
    confirmed = client.post(f"/api/v1/tasks/{task_id}/confirm", headers=auth_headers(customer))
    assert confirmed.status_code == 200, confirmed.text
    return task_id


def _pending_offers(db, task_id) -> list[TaskOffer]:
    return (
        db.query(TaskOffer)
        .filter(TaskOffer.task_id == task_id, TaskOffer.status == "PENDING")
        .all()
    )


def _make_workers(db, n: int):
    return [
        make_user(db, "WORKER", full_name=f"Runner {i}", skills=("document_submission",))
        for i in range(n)
    ]


def test_ring_down_offers_exactly_one_worker_at_a_time(client, db):
    customer = make_user(db, "CUSTOMER")
    workers = _make_workers(db, 3)
    task_id = _confirmed_task(client, customer)

    pending = _pending_offers(db, task_id)
    assert len(pending) == 1
    assert pending[0].worker_id == workers[0].id
    remaining = (as_aware(pending[0].expires_at) - utcnow()).total_seconds()
    assert 0 < remaining <= OFFER_SECONDS + 1

    dispatch_engine.clear(task_id)


def test_reject_rings_the_next_candidate_and_counts_a_miss(client, db):
    customer = make_user(db, "CUSTOMER")
    workers = _make_workers(db, 3)
    task_id = _confirmed_task(client, customer)

    rejected = client.post(f"/api/v1/tasks/{task_id}/reject", headers=auth_headers(workers[0]))
    assert rejected.status_code == 200, rejected.text

    db.expire_all()
    pending = _pending_offers(db, task_id)
    assert len(pending) == 1
    assert pending[0].worker_id == workers[1].id
    profile = db.query(WorkerProfile).filter(WorkerProfile.user_id == workers[0].id).one()
    assert profile.missed_offers == 1

    dispatch_engine.clear(task_id)


def test_timeout_rings_the_next_candidate(client, db):
    customer = make_user(db, "CUSTOMER")
    workers = _make_workers(db, 2)
    task_id = _confirmed_task(client, customer)

    offer = _pending_offers(db, task_id)[0]
    db.rollback()  # release the read transaction before the handler writes
    dispatch_engine._handle_timeout(task_id, offer.id)

    db.expire_all()
    assert offer.status == "TIMEOUT"
    pending = _pending_offers(db, task_id)
    assert len(pending) == 1
    assert pending[0].worker_id == workers[1].id
    profile = db.query(WorkerProfile).filter(WorkerProfile.user_id == workers[0].id).one()
    assert profile.missed_offers == 1

    dispatch_engine.clear(task_id)


def test_three_failures_escalate_to_surge_broadcast(client, db):
    customer = make_user(db, "CUSTOMER")
    workers = _make_workers(db, 3)
    task_id = _confirmed_task(client, customer)

    for worker in workers:  # every worker declines in ring order
        resp = client.post(f"/api/v1/tasks/{task_id}/reject", headers=auth_headers(worker))
        assert resp.status_code == 200, resp.text

    db.expire_all()
    pending = _pending_offers(db, task_id)
    offered_to = {o.worker_id for o in pending}
    # Surge: every verified worker in radius gets the offer at once.
    assert offered_to == {w.id for w in workers}

    dispatch_engine.clear(task_id)


def test_first_accept_wins_after_surge(client, db):
    customer = make_user(db, "CUSTOMER")
    workers = _make_workers(db, 3)
    task_id = _confirmed_task(client, customer)

    for worker in workers:
        client.post(f"/api/v1/tasks/{task_id}/reject", headers=auth_headers(worker))

    accepted = client.post(f"/api/v1/tasks/{task_id}/accept", headers=auth_headers(workers[1]))
    assert accepted.status_code == 200, accepted.text
    task = accepted.json()["data"]["task"]
    assert task["status"] == "ACCEPTED"
    assert task["assigned_worker_id"] == workers[1].id

    # A slower worker cannot take the same task.
    late = client.post(f"/api/v1/tasks/{task_id}/accept", headers=auth_headers(workers[2]))
    assert late.status_code == 409

    dispatch_engine.clear(task_id)


def test_accept_without_any_offer_is_rejected(client, db):
    customer = make_user(db, "CUSTOMER")
    # Offline workers are never ring candidates, so they hold no offer.
    bystander = make_user(db, "WORKER", is_online=False, skills=("document_submission",))
    task_id = _confirmed_task(client, customer)

    resp = client.post(f"/api/v1/tasks/{task_id}/accept", headers=auth_headers(bystander))
    assert resp.status_code == 409
    assert "no pending offer" in resp.json()["error"]["message"].lower()

    dispatch_engine.clear(task_id)


def test_worker_cannot_accept_someone_elses_offer(client, db):
    customer = make_user(db, "CUSTOMER")
    _make_workers(db, 2)
    outsider = make_user(db, "WORKER", skills=("document_submission",))
    task_id = _confirmed_task(client, customer)

    resp = client.post(f"/api/v1/tasks/{task_id}/accept", headers=auth_headers(outsider))
    assert resp.status_code == 409  # never had an offer

    dispatch_engine.clear(task_id)


def test_confirm_without_workers_keeps_task_open_without_offers(client, db):
    customer = make_user(db, "CUSTOMER")
    task_id = _confirmed_task(client, customer)

    assert _pending_offers(db, task_id) == []


def test_recovery_rings_task_once_a_worker_is_available(client, db):
    customer = make_user(db, "CUSTOMER")
    task_id = _confirmed_task(client, customer)
    assert _pending_offers(db, task_id) == []

    runner = make_user(db, "WORKER", skills=("document_submission",))
    dispatched = dispatch_engine.recover_open_tasks(db)
    db.commit()

    assert dispatched == 1
    db.expire_all()
    pending = _pending_offers(db, task_id)
    assert len(pending) == 1
    assert pending[0].worker_id == runner.id

    dispatch_engine.clear(task_id)


def test_recovery_skips_live_offers_and_respects_cooldown(client, db):
    customer = make_user(db, "CUSTOMER")
    make_user(db, "WORKER", skills=("document_submission",))
    task_id = _confirmed_task(client, customer)

    assert dispatch_engine.recover_open_tasks(db) == 0  # countdown still running

    offer = _pending_offers(db, task_id)[0]
    offer.status = "TIMEOUT"
    db.commit()
    assert dispatch_engine.recover_open_tasks(db) == 0  # inside cooldown window

    offer.created_at = utcnow_naive() - timedelta(seconds=REDISPATCH_COOLDOWN_SECONDS + 1)
    db.commit()
    assert dispatch_engine.recover_open_tasks(db) == 1

    db.expire_all()
    assert len(_pending_offers(db, task_id)) == 1

    dispatch_engine.clear(task_id)
