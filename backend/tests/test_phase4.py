"""Phase 4 marketplace parity: bidding, chaining, RideCheck, tiers/quests,
tips + UPI cashout, scheduled reserves, worker affinities and round trips."""

from datetime import datetime, timedelta, timezone

from app.matching.engine import MatchingEngine
from app.matching.config import get_matching_config
from app.models import (
    CustomerWorkerAffinity,
    Payment,
    PayoutRequest,
    RideCheckEvent,
    Task,
    TaskAssignment,
    TaskBid,
    TaskExecutionProof,
    Transaction,
    User,
    WorkerProfile,
    WorkerQuestProgress,
    Wallet,
)
from app.services.gamification_service import GamificationService
from app.services.reserve_watchdog import ReserveWatchdog
from app.services.ridecheck_monitor import RideCheckMonitor
from app.services.task_service import TaskService
from tests.conftest import auth_headers, make_user, task_payload

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def confirm_task(client, customer, **overrides) -> dict:
    created = client.post(
        "/api/v1/tasks", json=task_payload(**overrides), headers=auth_headers(customer)
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["task"]["id"]
    confirmed = client.post(f"/api/v1/tasks/{task_id}/confirm", headers=auth_headers(customer))
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["data"]["task"]


def accept_offer(client, worker, task_id: str) -> None:
    offers = client.get(
        "/api/v1/workers/me/offers", headers=auth_headers(worker)
    ).json()["data"]["items"]
    offer_id = next(o["offer"]["id"] for o in offers if o["task"]["id"] == task_id)
    accepted = client.post(
        f"/api/v1/workers/offers/{offer_id}/accept", headers=auth_headers(worker)
    )
    assert accepted.status_code == 200, accepted.text


def drive_to_completion_request(client, db, worker, customer, task_id: str) -> None:
    for next_status in ("WORKER_ON_THE_WAY", "ARRIVED_AT_LOCATION"):
        step = client.post(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": next_status},
            headers=auth_headers(worker),
        )
        assert step.status_code == 200, step.text

    start_code = client.get(
        f"/api/v1/tasks/{task_id}", headers=auth_headers(customer)
    ).json()["data"]["task"]["start_otp_display"]
    started = client.post(
        f"/api/v1/tasks/{task_id}/verify-start-otp",
        json={"otp": start_code},
        headers=auth_headers(worker),
    )
    assert started.status_code == 200, started.text

    db.add(TaskExecutionProof(task_id=task_id, worker_id=worker.id, file_key=f"proofs/{task_id}.webp"))
    db.commit()
    requested = client.post(
        f"/api/v1/tasks/{task_id}/request-completion", headers=auth_headers(worker)
    )
    assert requested.status_code == 200, requested.text


def complete(client, worker, customer, task_id: str) -> dict:
    completion_code = client.get(
        f"/api/v1/tasks/{task_id}", headers=auth_headers(customer)
    ).json()["data"]["task"]["completion_otp_display"]
    response = client.post(
        f"/api/v1/tasks/{task_id}/complete",
        json={"otp": completion_code},
        headers=auth_headers(worker),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["task"]


# ---------------------------------------------------------------------------
# 1. Counter-offer bidding
# ---------------------------------------------------------------------------


def test_counter_offer_bidding_flow(client, db):
    customer = make_user(db, "CUSTOMER")
    first = make_user(db, "WORKER")
    second = make_user(db, "WORKER")
    task = confirm_task(client, customer)

    below = client.post(
        f"/api/v1/tasks/{task['id']}/bids",
        json={"proposed_amount": 355, "note": "Below the allowed minimum"},
        headers=auth_headers(first),
    )
    assert below.status_code == 409, below.text
    above = client.post(
        f"/api/v1/tasks/{task['id']}/bids",
        json={"proposed_amount": 900},
        headers=auth_headers(first),
    )
    assert above.status_code == 409, above.text

    bid_one = client.post(
        f"/api/v1/tasks/{task['id']}/bids",
        json={"proposed_amount": 400, "note": "Rush hour pricing", "estimated_arrival_minutes": 12},
        headers=auth_headers(first),
    )
    assert bid_one.status_code == 201, bid_one.text
    bid_id = bid_one.json()["data"]["bid"]["id"]
    assert bid_one.json()["data"]["bid"]["worker_name"] == first.full_name

    bid_two = client.post(
        f"/api/v1/tasks/{task['id']}/bids",
        json={"proposed_amount": 450},
        headers=auth_headers(second),
    )
    assert bid_two.status_code == 201, bid_two.text

    listed = client.get(f"/api/v1/tasks/{task['id']}/bids", headers=auth_headers(customer))
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 2
    assert listed.json()["data"]["items"][0]["proposed_amount"] == 400.0

    stranger = make_user(db, "CUSTOMER")
    assert (
        client.get(f"/api/v1/tasks/{task['id']}/bids", headers=auth_headers(stranger)).status_code
        == 403
    )

    accepted = client.post(f"/api/v1/bids/{bid_id}/accept", headers=auth_headers(customer))
    assert accepted.status_code == 200, accepted.text
    accepted_task = accepted.json()["data"]["task"]
    assert accepted_task["status"] == "ACCEPTED"
    assert accepted_task["budget"] == 400.0
    assert accepted_task["assigned_worker_id"] == first.id

    db.expire_all()
    stored = db.get(Task, task["id"])
    assert float(stored.budget) == 400.0
    assert stored.assigned_worker_id == first.id
    winner = db.get(TaskBid, bid_id)
    loser = db.get(TaskBid, bid_two.json()["data"]["bid"]["id"])
    assert winner.status == "ACCEPTED"
    assert loser.status == "EXPIRED"

    payments = {
        p.purpose: p for p in db.query(Payment).filter(Payment.task_id == task["id"]).all()
    }
    assert set(payments) == {"TASK", "BID_DELTA"}
    assert float(payments["TASK"].amount) == 350.0
    assert float(payments["BID_DELTA"].amount) == 50.0
    assert payments["BID_DELTA"].status == "AUTHORIZED"

    duplicate = client.post(f"/api/v1/bids/{bid_id}/accept", headers=auth_headers(customer))
    assert duplicate.status_code == 409


# ---------------------------------------------------------------------------
# 2. Tips, UPI cashout and statements
# ---------------------------------------------------------------------------


def test_tip_then_upi_withdrawal_and_statement(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = confirm_task(client, customer)
    accept_offer(client, worker, task["id"])
    drive_to_completion_request(client, db, worker, customer, task["id"])
    completed = complete(client, worker, customer, task["id"])
    assert completed["status"] == "COMPLETED"

    db.expire_all()
    wallet = db.query(Wallet).filter(Wallet.user_id == worker.id).one()
    balance_before_tip = float(wallet.balance)
    assert balance_before_tip > 0

    tipped = client.post(
        f"/api/v1/tasks/{task['id']}/tip",
        json={"amount": 50},
        headers=auth_headers(customer),
    )
    assert tipped.status_code == 200, tipped.text
    assert tipped.json()["data"]["tip"]["settled"] is True
    db.expire_all()
    task_row = db.get(Task, task["id"])
    assert float(task_row.tip_amount) == 50.0
    wallet = db.query(Wallet).filter(Wallet.user_id == worker.id).one()
    assert float(wallet.balance) == round(balance_before_tip + 50.0, 2)
    assert (
        db.query(Transaction)
        .filter(Transaction.user_id == worker.id, Transaction.type == "TIP")
        .count()
        == 1
    )

    bad_upi = client.put(
        "/api/v1/wallet/upi", json={"upi_id": "not-a-upi"}, headers=auth_headers(worker)
    )
    assert bad_upi.status_code == 422
    good_upi = client.put(
        "/api/v1/wallet/upi", json={"upi_id": "worker@okhdfcbank"}, headers=auth_headers(worker)
    )
    assert good_upi.status_code == 200

    too_much = client.post(
        "/api/v1/wallet/withdraw",
        json={"amount": 100000},
        headers=auth_headers(worker),
    )
    assert too_much.status_code == 422

    wallet.balance = 200.0
    db.commit()
    withdrawn = client.post(
        "/api/v1/wallet/withdraw",
        json={"amount": 150},
        headers=auth_headers(worker),
    )
    assert withdrawn.status_code == 200, withdrawn.text
    payout = withdrawn.json()["data"]["payout"]
    assert payout["status"] == "COMPLETED"
    assert payout["reference_utr"].startswith("TFX")
    assert payout["upi_id"] == "worker@okhdfcbank"
    db.expire_all()
    wallet = db.query(Wallet).filter(Wallet.user_id == worker.id).one()
    assert float(wallet.balance) == 50.0
    stored_payout = db.query(PayoutRequest).filter(PayoutRequest.worker_id == worker.id).one()
    assert float(stored_payout.amount) == 150.0

    statement = client.get("/api/v1/wallet/statement", headers=auth_headers(worker))
    assert statement.status_code == 200
    data = statement.json()["data"]["statement"]
    assert data["categories"]["tips"] == 50.0
    assert data["categories"]["withdrawals"] == 150.0
    assert data["wallet_balance"] == 50.0
    assert data["net_earnings"] == round(
        data["categories"]["base_earnings"] + 50.0, 2
    )
    assert data["platform_fees"] > 0
    assert data["transaction_count"] >= 3

    csv_response = client.get(
        "/api/v1/wallet/statement?format=csv", headers=auth_headers(worker)
    )
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "Tips" in csv_response.text
    assert "UPI withdrawal" in csv_response.text


# ---------------------------------------------------------------------------
# 3. Scheduled reservations + watchdog
# ---------------------------------------------------------------------------


def test_scheduled_reservation_and_watchdog(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    tomorrow = (datetime.now(timezone.utc).astimezone(IST) + timedelta(days=1)).date().isoformat()
    task = confirm_task(
        client, customer, scheduled_date=tomorrow, scheduled_time="10:00"
    )
    assert task["status"] == "SCHEDULED_OPEN"
    assert task["is_scheduled"] is True

    board = client.get("/api/v1/workers/scheduled-board", headers=auth_headers(worker))
    assert board.status_code == 200
    assert any(item["task_id"] == task["id"] for item in board.json()["data"]["items"])

    claimed = client.post(
        f"/api/v1/tasks/{task['id']}/claim-reservation", headers=auth_headers(worker)
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["data"]["task"]["status"] == "SCHEDULED_ASSIGNED"
    assert claimed.json()["data"]["task"]["assigned_worker_id"] == worker.id

    readiness = client.post(
        f"/api/v1/tasks/{task['id']}/confirm-readiness", headers=auth_headers(worker)
    )
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["data"]["task"]["worker_confirmed_readiness"] is True

    # Once the start time arrives the watchdog promotes the reservation.
    db.expire_all()
    task_row = db.get(Task, task["id"])
    task_row.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    counts = ReserveWatchdog(db).tick()
    assert counts["activated"] == 1
    db.commit()
    db.expire_all()
    assert db.get(Task, task["id"]).status == "ACCEPTED"

    # A second reservation that never confirms readiness is revoked at T-30.
    other_worker = make_user(db, "WORKER")
    task_two = confirm_task(
        client, customer, scheduled_date=tomorrow, scheduled_time="12:00"
    )
    claimed_two = client.post(
        f"/api/v1/tasks/{task_two['id']}/claim-reservation", headers=auth_headers(other_worker)
    )
    assert claimed_two.status_code == 200, claimed_two.text
    db.expire_all()
    task_two_row = db.get(Task, task_two["id"])
    task_two_row.scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=20)
    db.commit()
    counts = ReserveWatchdog(db).tick()
    assert counts["revoked"] == 1
    db.commit()
    db.expire_all()
    revoked = db.get(Task, task_two["id"])
    assert revoked.status == "SEARCHING_WORKER"
    assert revoked.assigned_worker_id is None
    assignments = (
        db.query(TaskAssignment)
        .filter(TaskAssignment.task_id == task_two["id"], TaskAssignment.status == "CANCELLED")
        .all()
    )
    assert len(assignments) == 1


# ---------------------------------------------------------------------------
# 4. Round trips + return OTP
# ---------------------------------------------------------------------------


def test_round_trip_requires_return_handback_otp(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = confirm_task(
        client,
        customer,
        is_round_trip=True,
        pickup_latitude=15.8497,
        pickup_longitude=74.4977,
        pickup_address="12 MG Road, Hanji Nagar",
    )
    assert task["is_round_trip"] is True
    assert task["return_otp_required"] is True
    assert task["return_otp_display"]

    db.expire_all()
    stored = db.get(Task, task["id"])
    labels = [loc.label for loc in sorted(stored.locations, key=lambda loc: loc.sequence)]
    assert labels == ["pickup", "dropoff", "return"]

    accept_offer(client, worker, task["id"])
    drive_to_completion_request(client, db, worker, customer, task["id"])

    completion_code = client.get(
        f"/api/v1/tasks/{task['id']}", headers=auth_headers(customer)
    ).json()["data"]["task"]["completion_otp_display"]
    blocked = client.post(
        f"/api/v1/tasks/{task['id']}/complete",
        json={"otp": completion_code},
        headers=auth_headers(worker),
    )
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["error"]["details"]["purpose"] == "return"

    return_code = client.get(
        f"/api/v1/tasks/{task['id']}", headers=auth_headers(customer)
    ).json()["data"]["task"]["return_otp_display"]
    verified = client.post(
        f"/api/v1/tasks/{task['id']}/verify-return-otp",
        json={"otp": return_code},
        headers=auth_headers(worker),
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["data"]["task"]["return_otp_verified_at"] is not None

    finished = complete(client, worker, customer, task["id"])
    assert finished["status"] == "COMPLETED"
    db.expire_all()
    stored = db.get(Task, task["id"])
    assert stored.return_otp_verified_at is not None
    worker_wallet = db.query(Wallet).filter(Wallet.user_id == worker.id).one()
    assert float(worker_wallet.total_earned) > 0


# ---------------------------------------------------------------------------
# 5. Preferred / blacklisted workers
# ---------------------------------------------------------------------------


def test_preferred_and_blacklisted_affinities(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")

    preferred = client.post(
        f"/api/v1/users/workers/{worker.id}/prefer", headers=auth_headers(customer)
    )
    assert preferred.status_code == 200
    affinities = client.get(
        "/api/v1/users/me/worker-affinities", headers=auth_headers(customer)
    ).json()["data"]
    assert [w["worker_id"] for w in affinities["preferred"]] == [worker.id]

    blocked = client.post(
        f"/api/v1/users/workers/{worker.id}/blacklist", headers=auth_headers(customer)
    )
    assert blocked.status_code == 200
    affinities = client.get(
        "/api/v1/users/me/worker-affinities", headers=auth_headers(customer)
    ).json()["data"]
    assert [w["worker_id"] for w in affinities["blacklisted"]] == [worker.id]
    assert affinities["preferred"] == []

    task = confirm_task(client, customer)
    bid = client.post(
        f"/api/v1/tasks/{task['id']}/bids",
        json={"proposed_amount": 400},
        headers=auth_headers(worker),
    )
    assert bid.status_code == 403, bid.text

    offers = client.get(
        "/api/v1/workers/me/offers", headers=auth_headers(worker)
    ).json()["data"]["items"]
    assert not any(o["task"]["id"] == task["id"] for o in offers)

    unblocked = client.delete(
        f"/api/v1/users/workers/{worker.id}/blacklist", headers=auth_headers(customer)
    )
    assert unblocked.status_code == 200
    again = client.post(
        f"/api/v1/users/workers/{worker.id}/prefer", headers=auth_headers(customer)
    )
    assert again.status_code == 200
    db.expire_all()
    assert (
        db.query(CustomerWorkerAffinity)
        .filter(
            CustomerWorkerAffinity.customer_id == customer.id,
            CustomerWorkerAffinity.worker_id == worker.id,
            CustomerWorkerAffinity.affinity_type == "PREFERRED",
        )
        .count()
        == 1
    )


# ---------------------------------------------------------------------------
# 6. Tiers + quests
# ---------------------------------------------------------------------------


def test_daily_quest_bonus_and_tier_rules(client, db):
    worker = make_user(db, "WORKER")
    service = GamificationService(db)
    quests = service.today_quests(worker.id)
    assert [q["target_tasks_count"] for q in quests] == [3, 5, 12]

    for _ in range(3):
        completed = service._advance_quests(worker.id)
    db.commit()
    assert len(completed) == 1
    assert completed[0]["title"] == "First Three"

    db.expire_all()
    wallet = db.query(Wallet).filter(Wallet.user_id == worker.id).one()
    assert float(wallet.balance) == 50.0
    bonus = db.query(Transaction).filter(
        Transaction.user_id == worker.id, Transaction.type == "QUEST_BONUS"
    ).one()
    assert float(bonus.amount) == 50.0
    quest_progress = db.query(WorkerQuestProgress).filter(
        WorkerQuestProgress.worker_id == worker.id,
        WorkerQuestProgress.is_claimed.is_(True),
    ).all()
    assert len(quest_progress) == 1
    overview = client.get("/api/v1/workers/me/tier", headers=auth_headers(worker))
    assert overview.status_code == 200
    data = overview.json()["data"]
    assert data["tier"] == "SILVER"
    assert data["commission_rate"] == 0.1
    claimed = next(q for q in data["quests"] if q["title"] == "First Three")
    assert claimed["is_claimed"] is True

    assert service.tier_for(
        {"completed_30d": 25, "rating": 4.9, "cancellation_rate": 0.01}
    ) == "PLATINUM"
    assert service.tier_for(
        {"completed_30d": 10, "rating": 4.6, "cancellation_rate": 0.06}
    ) == "GOLD"
    assert service.tier_for(
        {"completed_30d": 9, "rating": 4.9, "cancellation_rate": 0.0}
    ) == "SILVER"
    assert service.tier_for(
        {"completed_30d": 30, "rating": 4.9, "cancellation_rate": 0.12}
    ) == "SILVER"


# ---------------------------------------------------------------------------
# 7. RideCheck detection, acknowledgement and admin escalation
# ---------------------------------------------------------------------------


def test_ridecheck_detection_and_admin_flag(client, db, monkeypatch):
    async def _offline_route(*args, **kwargs):
        return None

    monkeypatch.setattr("app.api.routes.tasks.route_for_task", _offline_route)

    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    admin = make_user(db, "ADMIN")
    task = confirm_task(client, customer)
    accept_offer(client, worker, task["id"])
    step = client.post(
        f"/api/v1/tasks/{task['id']}/status",
        json={"status": "WORKER_ON_THE_WAY"},
        headers=auth_headers(worker),
    )
    assert step.status_code == 200, step.text

    db.expire_all()
    task_row = db.get(Task, task["id"])
    worker_row = db.get(User, worker.id)
    monitor = RideCheckMonitor(db)
    raised = []
    for _ in range(3):
        raised = monitor.evaluate(
            task_row,
            worker_row,
            latitude=15.90,
            longitude=74.60,
            deviation_m=550.0,
            remaining_km=3.0,
            speed_kmph=30.0,
        )
    assert len(raised) == 1
    assert raised[0].type == "ROUTE_DEVIATION"
    db.commit()

    view = client.get(f"/api/v1/tasks/{task['id']}/ridecheck", headers=auth_headers(customer))
    assert view.status_code == 200
    assert view.json()["data"]["active"]["id"] == raised[0].id
    assert view.json()["data"]["active"]["non_dismissible"] is True

    acked = client.post(
        f"/api/v1/tasks/ridecheck/{raised[0].id}/acknowledge",
        json={"action": "SAFE", "reason": "TRAFFIC"},
        headers=auth_headers(worker),
    )
    assert acked.status_code == 200, acked.text
    assert acked.json()["data"]["event"]["status"] == "ACKNOWLEDGED"

    # Second incident left unanswered → flagged after the 120 s grace period.
    raised_again = []
    for _ in range(3):
        raised_again = monitor.evaluate(
            task_row,
            worker_row,
            latitude=15.90,
            longitude=74.60,
            deviation_m=700.0,
            remaining_km=2.0,
            speed_kmph=20.0,
        )
    assert len(raised_again) == 1
    db.commit()
    db.expire_all()
    event = db.get(RideCheckEvent, raised_again[0].id)
    event.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=200)
    db.commit()

    flagged = monitor.flag_overdue()
    assert flagged >= 1
    db.commit()

    listed = client.get("/api/v1/admin/ridecheck", headers=auth_headers(admin))
    assert listed.status_code == 200
    assert any(e["id"] == event.id for e in listed.json()["data"]["items"])

    resolved = client.post(
        f"/api/v1/admin/ridecheck/{event.id}/resolve",
        params={"note": "Checked in with the worker by phone."},
        headers=auth_headers(admin),
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["data"]["event"]["status"] == "RESOLVED"


# ---------------------------------------------------------------------------
# 8. Back-to-back chaining
# ---------------------------------------------------------------------------


def test_chained_candidate_and_queued_promotion(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")

    active = confirm_task(client, customer)
    queued = confirm_task(client, customer)

    db.expire_all()
    profile = db.query(WorkerProfile).filter(WorkerProfile.user_id == worker.id).one()
    active_row = db.get(Task, active["id"])
    queued_row = db.get(Task, queued["id"])

    active_row.status = "IN_PROGRESS"
    active_row.assigned_worker_id = worker.id
    assignment = TaskAssignment(
        task_id=active_row.id,
        worker_id=worker.id,
        status="ACTIVE",
        accepted_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc) - timedelta(minutes=80),
        earnings_amount=350,
    )
    db.add(assignment)
    db.commit()

    engine = MatchingEngine(config=get_matching_config())
    chain_task, origin = engine.chaining_state(db, profile)
    assert chain_task is not None and chain_task.id == active_row.id
    assert origin == (15.8497, 74.4977)

    profile.queued_task_id = queued_row.id
    db.commit()
    assert engine.chaining_state(db, profile) == (None, None)

    queued_row.status = "QUEUED_NEXT"
    queued_row.assigned_worker_id = worker.id
    db.commit()
    promoted = TaskService(db)._promote_queued_task(
        db.get(User, worker.id), completed_task=active_row
    )
    assert promoted is not None
    db.expire_all()
    assert db.get(Task, queued_row.id).status == "ACCEPTED"
    worker_row = db.get(User, worker.id)
    assert db.query(WorkerProfile).filter(
        WorkerProfile.user_id == worker_row.id
    ).one().queued_task_id is None
