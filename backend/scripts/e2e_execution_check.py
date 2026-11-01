"""Live E2E: PoE photo validation + expense approval + payout settlement.

Runs against the real Postgres/Redis backend and the running API server.
Creates an isolated customer/worker/task, drives the full handshake, uploads
GPS-tagged photos, logs and approves an expense, completes the task, asserts
the wallet ledger, then cleans everything up.
"""
import io
import shutil
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.models import (
    CustomerProfile,
    Task,
    TaskExpense,
    TaskExecutionProof,
    Transaction,
    User,
    Wallet,
    WorkerProfile,
)

BASE = "http://localhost:8000/api/v1"
suffix = uuid.uuid4().hex[:8]
db = SessionLocal()


def wait_for_row(loader, label, attempts=60):
    """The API commits when the request's DB dependency tears down, which can
    trail the HTTP response by a moment — poll instead of racing it."""
    for _ in range(attempts):
        db.expire_all()
        row = loader()
        if row is not None:
            return row
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {label}")


def make_user(role, name, seq):
    user = User(
        email=f"exec-{role}{seq}-{suffix}@test.dev",
        phone=f"+918{suffix}{seq:04d}",
        full_name=name,
        password_hash=hash_password("E2e@1234"),
        role=role,
        city="Belagavi",
        is_active=True,
        is_email_verified=True,
    )
    db.add(user)
    db.flush()
    db.add(Wallet(user_id=user.id, balance=0, total_earned=0, total_spent=0))
    if role == "CUSTOMER":
        db.add(
            CustomerProfile(
                user_id=user.id,
                area="Hanji Nagar",
                default_latitude=15.8497,
                default_longitude=74.4977,
            )
        )
    else:
        db.add(
            WorkerProfile(
                user_id=user.id,
                city="Belagavi",
                area="Hanji Nagar",
                latitude=15.8497,
                longitude=74.4977,
                experience_years=2,
                languages="English",
                is_online=True,
                is_verified=True,
                verification_status="APPROVED",
                working_radius_km=8.0,
            )
        )
    db.commit()
    return user


def dms(value):
    degrees = int(value)
    minutes_float = (value - degrees) * 60
    minutes = int(minutes_float)
    return degrees, minutes, round((minutes_float - minutes) * 60, 4)


def jpeg(latitude=None, longitude=None):
    image = Image.new("RGB", (480, 360), (35, 120, 205))
    exif = Image.Exif()
    exif[0x0112] = 1
    if latitude is not None and longitude is not None:
        gps = exif.get_ifd(0x8825)
        gps[1], gps[2] = ("N" if latitude >= 0 else "S"), dms(abs(latitude))
        gps[3], gps[4] = ("E" if longitude >= 0 else "W"), dms(abs(longitude))
        exif[0x8825] = gps
    exif[0x8769] = {36867: "2026:10:23 11:30:00"}
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif, quality=90)
    return buffer.getvalue()


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (160, 100), (235, 235, 235)).save(buffer, "PNG")
    return buffer.getvalue()


customer = make_user("CUSTOMER", "Execution Customer", 1)
worker = make_user("WORKER", "Execution Runner", 2)
t_customer = create_access_token(customer.id, customer.role)
t_worker = create_access_token(worker.id, worker.role)
h_customer = {"Authorization": f"Bearer {t_customer}"}
h_worker = {"Authorization": f"Bearer {t_worker}"}

PAYLOAD = {
    "title": "Proof + expense E2E verification task",
    "description": "Submit the sealed affidavit at the sub-registrar office and collect the receipt.",
    "task_type": "document_submission",
    "urgency": "normal",
    "scheduled_date": "2026-10-24",
    "scheduled_time": "11:00",
    "estimated_duration_minutes": 60,
    "latitude": 15.8497,
    "longitude": 74.4977,
    "address_text": "12 MG Road, Hanji Nagar, Belagavi",
    "area_name": "Hanji Nagar",
    "city": "Belagavi",
    "budget": 350,
    "required_skills": ["document_submission"],
}


def main():
    created = httpx.post(f"{BASE}/tasks", json=PAYLOAD, headers=h_customer, timeout=30)
    assert created.status_code == 201, created.text
    tid = created.json()["data"]["task"]["id"]
    confirmed = httpx.post(f"{BASE}/tasks/{tid}/confirm", headers=h_customer, timeout=60)
    assert confirmed.status_code == 200, confirmed.text
    accepted = httpx.post(f"{BASE}/tasks/{tid}/accept", headers=h_worker, timeout=30)
    assert accepted.status_code == 200, accepted.text
    print(f"1. task {tid} confirmed and accepted")

    for status in ("WORKER_ON_THE_WAY", "ARRIVED_AT_LOCATION"):
        step = httpx.post(
            f"{BASE}/tasks/{tid}/status",
            json={"status": status},
            headers=h_worker,
            timeout=30,
        )
        assert step.status_code == 200, step.text
    start_code = httpx.get(f"{BASE}/tasks/{tid}", headers=h_customer, timeout=30).json()[
        "data"
    ]["task"]["start_otp_display"]
    started = httpx.post(
        f"{BASE}/tasks/{tid}/verify-start-otp",
        json={"otp": start_code},
        headers=h_worker,
        timeout=30,
    )
    assert started.status_code == 200, started.text
    print("2. start OTP verified -> IN_PROGRESS")

    no_proof = httpx.post(f"{BASE}/tasks/{tid}/request-completion", headers=h_worker, timeout=30)
    assert no_proof.status_code == 422, no_proof.text
    assert no_proof.json()["error"]["code"] == "PROOF_REQUIRED"

    no_gps = httpx.post(
        f"{BASE}/tasks/{tid}/proof-of-execution",
        files={"file": ("site.jpg", jpeg(), "image/jpeg")},
        headers=h_worker,
        timeout=60,
    )
    assert no_gps.status_code == 422, no_gps.text
    assert no_gps.json()["error"]["code"] == "PROOF_LOCATION_MISSING"

    far = httpx.post(
        f"{BASE}/tasks/{tid}/proof-of-execution",
        files={"file": ("site.jpg", jpeg(15.95, 74.60), "image/jpeg")},
        headers=h_worker,
        timeout=60,
    )
    assert far.status_code == 422, far.text
    error = far.json()["error"]
    assert error["code"] == "PROOF_OUT_OF_RANGE", error
    print(
        f"3. geofence enforced: photo {error['details']['distance_m']}m away "
        f"(limit {error['details']['max_distance_m']}m)"
    )

    uploaded = httpx.post(
        f"{BASE}/tasks/{tid}/proof-of-execution",
        files={"file": ("site.jpg", jpeg(15.8497, 74.4977), "image/jpeg")},
        headers=h_worker,
        timeout=60,
    )
    assert uploaded.status_code == 201, uploaded.text
    proof = uploaded.json()["data"]["proof"]
    proof_row = wait_for_row(
        lambda: db.scalar(select(TaskExecutionProof).where(TaskExecutionProof.task_id == tid)),
        "proof row",
    )
    stored = Path(settings.upload_dir) / proof_row.file_key
    assert stored.is_file() and stored.read_bytes()[8:12] == b"WEBP", "proof not stored as WebP"
    with Image.open(stored) as image:
        assert dict(image.getexif()) == {}, "EXIF was not stripped"
    proof_file = httpx.get(
        f"{BASE}/tasks/{tid}/proofs/{proof['id']}/file", headers=h_customer, timeout=30
    )
    assert proof_file.status_code == 200 and proof_file.content[:4] == b"RIFF", proof_file.text
    print(f"4. proof stored privately at {proof_row.file_key} (WebP, EXIF stripped)")

    expense = httpx.post(
        f"{BASE}/tasks/{tid}/expenses",
        data={
            "amount": "180.50",
            "category": "PRINTING",
            "description": "Printed and notarised the affidavit at the copy shop.",
        },
        files={"receipt": ("receipt.png", png(), "image/png")},
        headers=h_worker,
        timeout=30,
    )
    assert expense.status_code == 201, expense.text
    expense_id = expense.json()["data"]["expense"]["id"]

    notices = httpx.get(
        f"{BASE}/notifications?unread_only=true&page_size=100", headers=h_customer, timeout=30
    ).json()["data"]["items"]
    request_notice = next(
        n for n in notices if n["type"] == "EXPENSE_REQUESTED" and n["data"].get("expense_id") == expense_id
    )
    print(f"5. expense Rs {request_notice['data']['amount']} pushed to customer notifications")

    approved = httpx.post(
        f"{BASE}/tasks/{tid}/expenses/{expense_id}/approve",
        json={"note": "Receipt verified."},
        headers=h_customer,
        timeout=30,
    )
    assert approved.status_code == 200, approved.text
    totals = approved.json()["data"]["totals"]
    assert totals["approved_total"] == 180.5, totals
    print(f"6. expense approved; approved_total={totals['approved_total']}")

    requested = httpx.post(f"{BASE}/tasks/{tid}/request-completion", headers=h_worker, timeout=30)
    assert requested.status_code == 200, requested.text
    completion_code = httpx.get(f"{BASE}/tasks/{tid}", headers=h_customer, timeout=30).json()[
        "data"
    ]["task"]["completion_otp_display"]
    done = httpx.post(
        f"{BASE}/tasks/{tid}/complete",
        json={"otp": completion_code},
        headers=h_worker,
        timeout=60,
    )
    assert done.status_code == 200, done.text
    assert done.json()["data"]["task"]["status"] == "COMPLETED"
    print("7. completion OTP verified -> COMPLETED")

    base_payout = round(350 * 0.90, 2)
    expected_balance = round(base_payout + 180.5, 2)
    for _ in range(60):
        db.expire_all()
        wallet = db.scalar(select(Wallet).where(Wallet.user_id == worker.id))
        expense_row = db.get(TaskExpense, expense_id)
        if wallet.balance == expected_balance and expense_row.status == "REIMBURSED":
            break
        time.sleep(0.1)
    assert wallet.balance == expected_balance, wallet.balance
    customer_wallet = db.scalar(select(Wallet).where(Wallet.user_id == customer.id))
    assert customer_wallet.total_spent == round(350 + 180.5, 2), customer_wallet.total_spent
    assert expense_row.status == "REIMBURSED", expense_row.status
    worker_tx = list(
        db.scalars(select(Transaction).where(Transaction.user_id == worker.id))
    )
    assert len(worker_tx) == 2, [t.amount for t in worker_tx]
    assert {t.reference_type for t in worker_tx} == {"task", "task_expense"}
    print(
        f"8. payout settled: base Rs {base_payout} + expenses Rs 180.50 "
        f"= Rs {wallet.balance} (expense {expense_row.status})"
    )

    detail = httpx.get(f"{BASE}/tasks/{tid}", headers=h_customer, timeout=30).json()["data"]["task"]
    assert detail["expense_totals"]["reimbursed_total"] == 180.5
    late = httpx.post(
        f"{BASE}/tasks/{tid}/expenses/{expense_id}/reject", headers=h_customer, timeout=30
    )
    assert late.status_code == 409, late.text
    print("9. post-completion expense decision correctly refused (409)")

    for folder in ("proofs", "expenses"):
        shutil.rmtree(Path(settings.upload_dir) / folder / tid, ignore_errors=True)
    task = db.get(Task, tid)
    db.delete(task)
    db.flush()
    for user in (worker, customer):
        row = db.get(User, user.id)
        db.delete(row)
    db.commit()
    left = db.scalar(select(TaskExecutionProof).where(TaskExecutionProof.task_id == tid))
    assert left is None
    print("10. cleanup done")
    print("EXECUTION E2E OK")


if __name__ == "__main__":
    try:
        main()
    finally:
        db.close()
