"""Proof-of-execution photos and the incidental expense ledger.

Photos are generated in-memory with real EXIF GPS tags so the validator,
the WebP re-encode (which must strip EXIF) and the 500 m geofence are all
exercised without mocks.
"""

import io
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.models import (
    CustomerProfile,
    ExpenseStatus,
    Notification,
    TaskExpense,
    TaskExecutionProof,
    Transaction,
    Wallet,
    WorkerProfile,
)

from tests.conftest import auth_headers, make_user, task_payload


def _dms(value: float) -> tuple[int, int, float]:
    degrees = int(value)
    minutes_float = (value - degrees) * 60
    minutes = int(minutes_float)
    seconds = round((minutes_float - minutes) * 60, 4)
    return degrees, minutes, seconds


def _jpeg(
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    captured: str = "2026:10:23 09:15:00",
    size: tuple[int, int] = (320, 240),
) -> bytes:
    image = Image.new("RGB", size, (30, 110, 200))
    exif = Image.Exif()
    exif[0x0112] = 1
    if latitude is not None and longitude is not None:
        gps = exif.get_ifd(0x8825)
        gps[1] = "N" if latitude >= 0 else "S"
        gps[2] = _dms(abs(latitude))
        gps[3] = "E" if longitude >= 0 else "W"
        gps[4] = _dms(abs(longitude))
        exif[0x8825] = gps
    exif[0x8769] = {36867: captured}
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif, quality=90)
    return buffer.getvalue()


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (120, 80), (220, 220, 220)).save(buffer, "PNG")
    return buffer.getvalue()


def _start_task(client, db, *, advance_to_in_progress: bool = True):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER", skills=("document_submission",))
    other_worker = make_user(db, "WORKER", skills=("document_submission",))

    created = client.post("/api/v1/tasks", json=task_payload(), headers=auth_headers(customer))
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["task"]["id"]

    confirmed = client.post(f"/api/v1/tasks/{task_id}/confirm", headers=auth_headers(customer))
    assert confirmed.status_code == 200, confirmed.text
    accepted = client.post(f"/api/v1/tasks/{task_id}/accept", headers=auth_headers(worker))
    assert accepted.status_code == 200, accepted.text

    if not advance_to_in_progress:
        return customer, worker, other_worker, task_id

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
    return customer, worker, other_worker, task_id


def _complete_task(client, customer, worker, task_id) -> str:
    proof = client.post(
        f"/api/v1/tasks/{task_id}/proof-of-execution",
        files={"file": ("site.jpg", _jpeg(latitude=15.8497, longitude=74.4977), "image/jpeg")},
        headers=auth_headers(worker),
    )
    assert proof.status_code == 201, proof.text
    requested = client.post(
        f"/api/v1/tasks/{task_id}/request-completion", headers=auth_headers(worker)
    )
    assert requested.status_code == 200, requested.text
    code = client.get(
        f"/api/v1/tasks/{task_id}", headers=auth_headers(customer)
    ).json()["data"]["task"]["completion_otp_display"]
    done = client.post(
        f"/api/v1/tasks/{task_id}/complete",
        json={"otp": code},
        headers=auth_headers(worker),
    )
    assert done.status_code == 200, done.text
    return code


# ---------------------------------------------------------------- proofs --


def test_proof_is_geofenced_reencoded_and_private(client, db):
    customer, worker, other_worker, task_id = _start_task(client, db)
    photo = _jpeg(latitude=15.8497, longitude=74.4977)

    uploaded = client.post(
        f"/api/v1/tasks/{task_id}/proof-of-execution",
        files={"file": ("site.jpg", photo, "image/jpeg")},
        headers=auth_headers(worker),
    )
    assert uploaded.status_code == 201, uploaded.text
    proof = uploaded.json()["data"]["proof"]
    assert proof["location_source"] == "EXIF"
    assert proof["latitude"] == 15.8497
    assert proof["longitude"] == 74.4977
    assert proof["captured_at"].startswith("2026-10-23")
    assert proof["file_url"].endswith(f"/tasks/{task_id}/proofs/{proof['id']}/file")

    db.expire_all()
    row = db.scalar(select(TaskExecutionProof).where(TaskExecutionProof.task_id == task_id))
    assert row is not None
    assert row.file_key.startswith(f"proofs/{task_id}/")
    stored_path = Path(settings.upload_dir) / row.file_key
    stored = stored_path.read_bytes()
    assert stored[:4] == b"RIFF" and stored[8:12] == b"WEBP"
    with Image.open(io.BytesIO(stored)) as normalized:
        assert normalized.format == "WEBP"
        assert normalized.width <= 1920 and normalized.height <= 1080
        # Re-encoding must strip the original EXIF block (privacy).
        assert dict(normalized.getexif()) == {}

    customer_file = client.get(
        f"/api/v1/tasks/{task_id}/proofs/{proof['id']}/file", headers=auth_headers(customer)
    )
    assert customer_file.status_code == 200
    assert customer_file.headers["content-type"] == "image/webp"
    assert customer_file.content.startswith(b"RIFF")

    denied = client.get(
        f"/api/v1/tasks/{task_id}/proofs/{proof['id']}/file",
        headers=auth_headers(other_worker),
    )
    assert denied.status_code == 403

    detail = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers(customer)).json()["data"]["task"]
    assert len(detail["execution_proofs"]) == 1
    assert detail["expense_totals"]["count"] == 0


def test_proof_rejects_missing_or_distant_gps(client, db):
    customer, worker, _, task_id = _start_task(client, db)
    url = f"/api/v1/tasks/{task_id}/proof-of-execution"

    missing = client.post(
        url,
        files={"file": ("site.jpg", _jpeg(), "image/jpeg")},
        headers=auth_headers(worker),
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "PROOF_LOCATION_MISSING"

    far = client.post(
        url,
        files={"file": ("site.jpg", _jpeg(latitude=15.95, longitude=74.60), "image/jpeg")},
        headers=auth_headers(worker),
    )
    assert far.status_code == 422
    body = far.json()["error"]
    assert body["code"] == "PROOF_OUT_OF_RANGE"
    assert body["details"]["max_distance_m"] == settings.proof_max_distance_m
    assert body["details"]["distance_m"] > settings.proof_max_distance_m

    spoofed = client.post(
        url,
        files={"file": ("site.jpg", b"this is not an image", "image/jpeg")},
        headers=auth_headers(worker),
    )
    assert spoofed.status_code == 415
    assert spoofed.json()["error"]["code"] == "FILE_TYPE_NOT_ALLOWED"

    mismatched = client.post(
        url,
        files={"file": ("site.png", _png(), "image/jpeg")},
        headers=auth_headers(worker),
    )
    assert mismatched.status_code == 422
    assert mismatched.json()["error"]["code"] == "VALIDATION_ERROR"

    db.expire_all()
    assert db.scalar(select(TaskExecutionProof).where(TaskExecutionProof.task_id == task_id)) is None


def test_proof_requires_assignment_and_active_status(client, db, monkeypatch):
    customer, worker, other_worker, task_id = _start_task(client, db, advance_to_in_progress=False)
    url = f"/api/v1/tasks/{task_id}/proof-of-execution"

    early = client.post(
        url,
        files={"file": ("site.jpg", _jpeg(latitude=15.8497, longitude=74.4977), "image/jpeg")},
        headers=auth_headers(worker),
    )
    assert early.status_code == 422
    assert early.json()["error"]["code"] == "INVALID_TRANSITION"

    for next_status in ("WORKER_ON_THE_WAY", "ARRIVED_AT_LOCATION"):
        client.post(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": next_status},
            headers=auth_headers(worker),
        )
    start_code = client.get(
        f"/api/v1/tasks/{task_id}", headers=auth_headers(customer)
    ).json()["data"]["task"]["start_otp_display"]
    client.post(
        f"/api/v1/tasks/{task_id}/verify-start-otp",
        json={"otp": start_code},
        headers=auth_headers(worker),
    )

    denied = client.post(
        url,
        files={"file": ("site.jpg", _jpeg(latitude=15.8497, longitude=74.4977), "image/jpeg")},
        headers=auth_headers(other_worker),
    )
    assert denied.status_code == 403

    monkeypatch.setattr(settings, "proof_max_per_task", 1)
    first = client.post(
        url,
        files={"file": ("site.jpg", _jpeg(latitude=15.8497, longitude=74.4977), "image/jpeg")},
        headers=auth_headers(worker),
    )
    assert first.status_code == 201, first.text
    capped = client.post(
        url,
        files={"file": ("site2.jpg", _jpeg(latitude=15.8497, longitude=74.4977), "image/jpeg")},
        headers=auth_headers(worker),
    )
    assert capped.status_code == 409


# -------------------------------------------------------------- expenses --


def test_expense_approval_is_reimbursed_at_completion(client, db):
    customer, worker, other_worker, task_id = _start_task(client, db)
    created = client.post(
        f"/api/v1/tasks/{task_id}/expenses",
        data={
            "amount": "120.50",
            "category": "PARKING",
            "description": "Paid the parking attendant at the office gate.",
        },
        files={"receipt": ("receipt.png", _png(), "image/png")},
        headers=auth_headers(worker),
    )
    assert created.status_code == 201, created.text
    expense = created.json()["data"]["expense"]
    assert expense["status"] == "PENDING_APPROVAL"
    assert expense["receipt_available"] is True
    assert expense["amount"] == 120.5

    db.expire_all()
    notice = db.scalars(
        select(Notification).where(
            Notification.user_id == customer.id,
            Notification.type == "EXPENSE_REQUESTED",
        )
    ).one()
    assert notice.data["expense_id"] == expense["id"]
    assert notice.data["amount"] == 120.5

    receipt_file = client.get(
        f"/api/v1/tasks/{task_id}/expenses/{expense['id']}/receipt",
        headers=auth_headers(customer),
    )
    assert receipt_file.status_code == 200
    assert receipt_file.headers["content-type"] == "image/png"
    denied = client.get(
        f"/api/v1/tasks/{task_id}/expenses/{expense['id']}/receipt",
        headers=auth_headers(other_worker),
    )
    assert denied.status_code == 403

    worker_decision = client.post(
        f"/api/v1/tasks/{task_id}/expenses/{expense['id']}/approve",
        headers=auth_headers(worker),
    )
    assert worker_decision.status_code == 403

    approved = client.post(
        f"/api/v1/tasks/{task_id}/expenses/{expense['id']}/approve",
        json={"note": "Parking receipt looks correct."},
        headers=auth_headers(customer),
    )
    assert approved.status_code == 200, approved.text
    decided = approved.json()["data"]["expense"]
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_id"] == customer.id
    assert decided["decision_note"] == "Parking receipt looks correct."
    assert approved.json()["data"]["totals"]["approved_total"] == 120.5

    db.expire_all()
    worker_notice = db.scalars(
        select(Notification).where(
            Notification.user_id == worker.id,
            Notification.type == "EXPENSE_APPROVED",
        )
    ).one()
    assert worker_notice.data["expense_id"] == expense["id"]

    again = client.post(
        f"/api/v1/tasks/{task_id}/expenses/{expense['id']}/approve",
        headers=auth_headers(customer),
    )
    assert again.status_code == 409

    _complete_task(client, customer, worker, task_id)

    db.expire_all()
    base_payout = round(350 * 0.90, 2)
    worker_wallet = db.scalar(select(Wallet).where(Wallet.user_id == worker.id))
    assert worker_wallet.balance == round(base_payout + 120.5, 2)
    assert worker_wallet.total_earned == round(base_payout + 120.5, 2)

    customer_wallet = db.scalar(select(Wallet).where(Wallet.user_id == customer.id))
    assert customer_wallet.total_spent == round(350 + 120.5, 2)
    customer_profile = db.scalar(
        select(CustomerProfile).where(CustomerProfile.user_id == customer.id)
    )
    assert customer_profile.total_spent == round(350 + 120.5, 2)
    worker_profile = db.scalar(select(WorkerProfile).where(WorkerProfile.user_id == worker.id))
    assert worker_profile.total_earnings == base_payout

    ledger = {
        (tx.reference_type, tx.reference_id): tx
        for tx in db.scalars(select(Transaction).where(Transaction.user_id == worker.id))
    }
    assert ledger[("task", task_id)].amount == base_payout
    assert ledger[("task_expense", expense["id"])].amount == 120.5
    assert sum(tx.amount for tx in ledger.values()) == round(base_payout + 120.5, 2)

    db.expire_all()
    row = db.get(TaskExpense, expense["id"])
    assert row.status == ExpenseStatus.REIMBURSED.value

    detail = client.get(
        f"/api/v1/tasks/{task_id}", headers=auth_headers(customer)
    ).json()["data"]["task"]
    assert detail["expense_totals"]["reimbursed_total"] == 120.5
    assert detail["expense_totals"]["approved_total"] == 0
    assert detail["expense_totals"]["worker_reimbursement_total"] == 120.5

    late = client.post(
        f"/api/v1/tasks/{task_id}/expenses/{expense['id']}/reject", headers=auth_headers(customer)
    )
    assert late.status_code == 409


def test_rejected_expense_never_reaches_payout(client, db):
    customer, worker, _, task_id = _start_task(client, db)
    created = client.post(
        f"/api/v1/tasks/{task_id}/expenses",
        data={
            "amount": "50",
            "category": "PRINTING",
            "description": "Printed the affidavit at the copy shop.",
        },
        headers=auth_headers(worker),
    )
    assert created.status_code == 201, created.text
    expense_id = created.json()["data"]["expense"]["id"]

    rejected = client.post(
        f"/api/v1/tasks/{task_id}/expenses/{expense_id}/reject",
        json={"note": "Printing was already covered."},
        headers=auth_headers(customer),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["expense"]["status"] == "REJECTED"
    assert rejected.json()["data"]["totals"]["rejected_total"] == 50

    db.expire_all()
    notice = db.scalars(
        select(Notification).where(
            Notification.user_id == worker.id,
            Notification.type == "EXPENSE_REJECTED",
        )
    ).one()
    assert notice.data["expense_id"] == expense_id

    _complete_task(client, customer, worker, task_id)
    db.expire_all()
    wallet = db.scalar(select(Wallet).where(Wallet.user_id == worker.id))
    assert wallet.balance == round(350 * 0.90, 2)
    assert db.get(TaskExpense, expense_id).status == "REJECTED"


def test_unreviewed_expense_is_closed_at_completion(client, db):
    customer, worker, _, task_id = _start_task(client, db)
    created = client.post(
        f"/api/v1/tasks/{task_id}/expenses",
        data={
            "amount": "75",
            "category": "PARKING",
            "description": "Parking fee while waiting at the registry office.",
        },
        headers=auth_headers(worker),
    )
    assert created.status_code == 201, created.text
    expense_id = created.json()["data"]["expense"]["id"]

    _complete_task(client, customer, worker, task_id)

    db.expire_all()
    row = db.get(TaskExpense, expense_id)
    assert row.status == "REJECTED"
    assert row.decided_by_id is None
    assert "completed before review" in row.decision_note
    wallet = db.scalar(select(Wallet).where(Wallet.user_id == worker.id))
    assert wallet.balance == round(350 * 0.90, 2)
    notice = db.scalars(
        select(Notification).where(
            Notification.user_id == worker.id,
            Notification.type == "EXPENSE_REJECTED",
        )
    ).one()
    assert expense_id in notice.data["expense_ids"]


def test_expense_validation_and_ownership(client, db, monkeypatch):
    customer, worker, other_worker, task_id = _start_task(client, db)
    url = f"/api/v1/tasks/{task_id}/expenses"
    base = {"category": "OTHER", "description": "A valid expense description."}

    zero = client.post(url, data={**base, "amount": "0"}, headers=auth_headers(worker))
    assert zero.status_code == 422
    assert zero.json()["error"]["code"] == "VALIDATION_ERROR"

    monkeypatch.setattr(settings, "expense_max_amount", 100.0)
    over = client.post(url, data={**base, "amount": "101"}, headers=auth_headers(worker))
    assert over.status_code == 422
    assert over.json()["error"]["code"] == "EXPENSE_LIMIT_EXCEEDED"

    bad_category = client.post(
        url, data={**base, "amount": "10", "category": "BRIBERY"}, headers=auth_headers(worker)
    )
    assert bad_category.status_code == 422

    short = client.post(
        url, data={"amount": "10", "category": "OTHER", "description": "x"}, headers=auth_headers(worker)
    )
    assert short.status_code == 422

    bad_receipt = client.post(
        url,
        data={**base, "amount": "10"},
        files={"receipt": ("receipt.pdf", b"not a real pdf", "application/pdf")},
        headers=auth_headers(worker),
    )
    assert bad_receipt.status_code == 415

    outsider = client.post(url, data={**base, "amount": "10"}, headers=auth_headers(other_worker))
    assert outsider.status_code == 403
    owner = client.post(url, data={**base, "amount": "10"}, headers=auth_headers(customer))
    assert owner.status_code == 403

    monkeypatch.setattr(settings, "expense_max_per_task", 1)
    monkeypatch.setattr(settings, "expense_max_amount", 20_000.0)
    first = client.post(url, data={**base, "amount": "10"}, headers=auth_headers(worker))
    assert first.status_code == 201, first.text
    second = client.post(url, data={**base, "amount": "12"}, headers=auth_headers(worker))
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "EXPENSE_LIMIT_EXCEEDED"


def test_expense_and_proof_blocked_before_start(client, db):
    customer, worker, _, task_id = _start_task(client, db, advance_to_in_progress=False)

    expense = client.post(
        f"/api/v1/tasks/{task_id}/expenses",
        data={"amount": "25", "category": "OTHER", "description": "Auto fare to the office."},
        headers=auth_headers(worker),
    )
    assert expense.status_code == 422
    assert expense.json()["error"]["code"] == "INVALID_TRANSITION"

    proof = client.post(
        f"/api/v1/tasks/{task_id}/proof-of-execution",
        files={"file": ("site.jpg", _jpeg(latitude=15.8497, longitude=74.4977), "image/jpeg")},
        headers=auth_headers(worker),
    )
    assert proof.status_code == 422
    assert proof.json()["error"]["code"] == "INVALID_TRANSITION"
