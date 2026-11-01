"""The full TaskFlex acceptance flow over the real API:

parse (AI only) → create (PENDING_CONFIRMATION) → confirm (pay + dispatch)
→ worker accepts → status chain → start OTP → proof + completion OTP
→ payment captured + wallet credited → mutual ratings → admin sees it all.
"""

from app.models import Notification, Payment, TaskExecutionProof, Wallet, WorkerProfile

from tests.conftest import auth_headers, make_user, task_payload

PARSE_TEXT = (
    "I need someone to collect my passport from the courier office this afternoon. "
    "My budget is 350 rupees."
)


def test_full_task_lifecycle_end_to_end(client, db):
    customer = make_user(db, "CUSTOMER", full_name="Kavya Rao")
    worker = make_user(db, "WORKER", full_name="Ravi Naik", skills=("document_submission",))
    second_worker = make_user(db, "WORKER", full_name="Sunil Joshi", skills=("document_submission",))
    admin = make_user(db, "ADMIN")

    # 1 — AI interpretation only: nothing saved.
    parsed = client.post("/api/v1/tasks/parse", json={"text": PARSE_TEXT}, headers=auth_headers(customer))
    assert parsed.status_code == 200
    assert parsed.json()["data"]["draft"]["provider"] == "mock"

    # 2 — customer reviews the draft and creates the task.
    created = client.post("/api/v1/tasks", json=task_payload(), headers=auth_headers(customer))
    assert created.status_code == 201
    task = created.json()["data"]["task"]
    task_id = task["id"]
    assert task["status"] == "PENDING_CONFIRMATION"

    # 3 — matching preview for the owner.
    matches = client.get(f"/api/v1/tasks/{task_id}/matches", headers=auth_headers(customer))
    assert matches.status_code == 200
    match_data = matches.json()["data"]
    assert match_data["eligible_count"] == 2
    assert len(match_data["matches"]) == 2

    # 4 — the explicit confirmation gate: payment authorized + offers dispatched.
    confirmed = client.post(f"/api/v1/tasks/{task_id}/confirm", headers=auth_headers(customer))
    assert confirmed.status_code == 200
    task = confirmed.json()["data"]["task"]
    assert task["status"] == "SEARCHING_WORKER"
    assert task["payment_status"] == "AUTHORIZED"

    # 5 — workers see the offer in their queue.
    offers = client.get("/api/v1/workers/me/offers", headers=auth_headers(worker))
    assert offers.status_code == 200
    offer_items = offers.json()["data"]["items"]
    assert offers.json()["data"]["total"] >= 1
    mine = next(item for item in offer_items if item["task"]["id"] == task_id)
    offer_id = mine["offer"]["id"]
    assert mine["offer"]["status"] == "PENDING"

    # 6 — worker accepts; sibling offer expires.
    accepted = client.post(f"/api/v1/workers/offers/{offer_id}/accept", headers=auth_headers(worker))
    assert accepted.status_code == 200
    task = accepted.json()["data"]["task"]
    assert task["status"] == "ACCEPTED"
    assert task["assigned_worker_id"] == worker.id

    sibling_status = None
    for item in client.get("/api/v1/workers/me/offers", headers=auth_headers(second_worker)).json()["data"]["items"]:
        if item["task"]["id"] == task_id:
            sibling_status = item["offer"]["status"]
    assert sibling_status in ("EXPIRED", "DECLINED", None) or sibling_status == "EXPIRED"

    # 7 — strict worker status chain; skipping a step is rejected.
    skip = client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "COMPLETED"},
        headers=auth_headers(worker),
    )
    assert skip.status_code == 422

    for next_status in ("WORKER_ON_THE_WAY", "ARRIVED_AT_LOCATION"):
        step = client.post(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": next_status},
            headers=auth_headers(worker),
        )
        assert step.status_code == 200, step.text
        assert step.json()["data"]["task"]["status"] == next_status

    # IN_PROGRESS is OTP-gated: the raw status endpoint refuses it.
    blocked = client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "IN_PROGRESS"},
        headers=auth_headers(worker),
    )
    assert blocked.status_code == 422

    # 8 — the start handshake: the code is visible ONLY to the customer and
    # only the worker may verify it.
    customer_view = client.get(
        f"/api/v1/tasks/{task_id}", headers=auth_headers(customer)
    ).json()["data"]["task"]
    start_code = customer_view["start_otp_display"]
    assert start_code and len(start_code) == 4
    assert customer_view["start_otp_required"] is True

    worker_view = client.get(
        f"/api/v1/tasks/{task_id}", headers=auth_headers(worker)
    ).json()["data"]["task"]
    assert "start_otp_display" not in worker_view
    assert "completion_otp_display" not in worker_view

    wrong_code = "0001" if start_code != "0001" else "0002"
    wrong = client.post(
        f"/api/v1/tasks/{task_id}/verify-start-otp",
        json={"otp": wrong_code},
        headers=auth_headers(worker),
    )
    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "OTP_INVALID"

    started = client.post(
        f"/api/v1/tasks/{task_id}/verify-start-otp",
        json={"otp": start_code},
        headers=auth_headers(worker),
    )
    assert started.status_code == 200, started.text
    assert started.json()["data"]["task"]["status"] == "IN_PROGRESS"

    # 9 — completion: proof of execution is mandatory, then the completion code.
    no_proof = client.post(
        f"/api/v1/tasks/{task_id}/request-completion", headers=auth_headers(worker)
    )
    assert no_proof.status_code == 422
    assert no_proof.json()["error"]["code"] == "PROOF_REQUIRED"

    db.add(TaskExecutionProof(task_id=task_id, worker_id=worker.id, file_key=f"proofs/{task_id}-1.webp"))
    db.commit()

    requested = client.post(
        f"/api/v1/tasks/{task_id}/request-completion", headers=auth_headers(worker)
    )
    assert requested.status_code == 200, requested.text
    assert requested.json()["data"]["task"]["status"] == "COMPLETION_REQUESTED"

    completion_code = client.get(
        f"/api/v1/tasks/{task_id}", headers=auth_headers(customer)
    ).json()["data"]["task"]["completion_otp_display"]
    assert completion_code and len(completion_code) == 4

    payout_expected = round(350 * 0.90, 2)
    commission_expected = round(350 * 0.10, 2)

    wallet_before = db.query(Wallet).filter(Wallet.user_id == worker.id).one()
    assert float(wallet_before.balance) == 0

    done = client.post(
        f"/api/v1/tasks/{task_id}/complete",
        json={"otp": completion_code},
        headers=auth_headers(worker),
    )
    assert done.status_code == 200, done.text
    task = done.json()["data"]["task"]
    assert task["status"] == "COMPLETED"
    assert task["payment_status"] == "CAPTURED"
    assert float(task["worker_payout_amount"]) == payout_expected
    assert float(task["commission_amount"]) == commission_expected

    db.expire_all()
    wallet_after = db.query(Wallet).filter(Wallet.user_id == worker.id).one()
    assert float(wallet_after.balance) == payout_expected
    assert float(wallet_after.total_earned) == payout_expected

    profile = db.query(WorkerProfile).filter(WorkerProfile.user_id == worker.id).one()
    assert float(profile.total_earnings) == payout_expected

    payment = db.query(Payment).filter(Payment.task_id == task_id).one()
    assert payment.status == "CAPTURED"

    # 9 — mutual ratings; duplicate rating in the same direction is rejected.
    customer_rating = client.post(
        "/api/v1/ratings",
        json={"task_id": task_id, "score": 5, "comment": "Quick, polite and reliable."},
        headers=auth_headers(customer),
    )
    assert customer_rating.status_code == 201
    assert customer_rating.json()["data"]["rating"]["direction"] == "CUSTOMER_TO_WORKER"

    duplicate = client.post(
        "/api/v1/ratings",
        json={"task_id": task_id, "score": 4},
        headers=auth_headers(customer),
    )
    assert duplicate.status_code == 409

    worker_rating = client.post(
        "/api/v1/ratings",
        json={"task_id": task_id, "score": 4, "comment": "Clear instructions."},
        headers=auth_headers(worker),
    )
    assert worker_rating.status_code == 201

    db.expire_all()
    profile = db.query(WorkerProfile).filter(WorkerProfile.user_id == worker.id).one()
    assert profile.rating_count == 1
    assert float(profile.rating_average) == 5.0

    ratings = client.get(f"/api/v1/tasks/{task_id}/ratings", headers=auth_headers(customer))
    assert ratings.status_code == 200
    assert len(ratings.json()["data"]["items"]) == 2

    # 10 — the full status trail is queryable.
    detail = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers(customer))
    trail = [h["to_status"] for h in detail.json()["data"]["task"]["status_history"]]
    assert trail == [
        "PENDING_CONFIRMATION",
        "CONFIRMED",
        "SEARCHING_WORKER",
        "ACCEPTED",
        "WORKER_ON_THE_WAY",
        "ARRIVED_AT_LOCATION",
        "IN_PROGRESS",
        "COMPLETION_REQUESTED",
        "COMPLETED",
    ]

    # 11 — the admin dashboard reflects the activity.
    dashboard = client.get("/api/v1/admin/dashboard", headers=auth_headers(admin))
    assert dashboard.status_code == 200
    metrics = dashboard.json()["data"]["metrics"]
    assert metrics["completed_tasks"] >= 1
    assert metrics["total_workers"] >= 2
    assert metrics["total_revenue"] >= 350
    assert metrics["platform_commission"] >= 35


def test_customer_is_notified_on_acceptance_and_arrival(client, db):
    customer = make_user(db, "CUSTOMER", full_name="Nisha Rao")
    worker = make_user(db, "WORKER", full_name="Arun Hegde", skills=("document_submission",))

    created = client.post("/api/v1/tasks", json=task_payload(), headers=auth_headers(customer))
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["task"]["id"]
    confirmed = client.post(f"/api/v1/tasks/{task_id}/confirm", headers=auth_headers(customer))
    assert confirmed.status_code == 200, confirmed.text

    offer = next(
        item
        for item in client.get(
            "/api/v1/workers/me/offers", headers=auth_headers(worker)
        ).json()["data"]["items"]
        if item["task"]["id"] == task_id
    )
    accepted = client.post(
        f"/api/v1/workers/offers/{offer['offer']['id']}/accept", headers=auth_headers(worker)
    )
    assert accepted.status_code == 200, accepted.text

    for next_status in ("WORKER_ON_THE_WAY", "ARRIVED_AT_LOCATION"):
        step = client.post(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": next_status},
            headers=auth_headers(worker),
        )
        assert step.status_code == 200, step.text

    db.expire_all()
    notes = (
        db.query(Notification)
        .filter(Notification.user_id == customer.id)
        .order_by(Notification.created_at.asc())
        .all()
    )
    accepted_notes = [n for n in notes if n.type == "WORKER_ACCEPTED"]
    arriving_notes = [n for n in notes if n.type == "WORKER_ARRIVING"]
    assert len(accepted_notes) == 1
    assert "accepted your task" in accepted_notes[0].body
    assert len(arriving_notes) == 2
    titles = {n.title for n in arriving_notes}
    assert any("on the way" in title.lower() for title in titles)
    assert any("arrived" in title.lower() for title in titles)
    for note in arriving_notes:
        assert note.link == f"/customer/tasks/{task_id}"
    arrived_note = next(n for n in arriving_notes if "arrived" in n.title.lower())
    assert "start code" in arrived_note.body.lower()
