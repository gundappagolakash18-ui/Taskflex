"""Live E2E: sequential ring-down dispatch over Redis + WS (one-shot script)."""
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import redis as redis_sync
import websockets

from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.models import CustomerProfile, Task, TaskOffer, User, WorkerProfile, Wallet

BASE = "http://localhost:8000/api/v1"
suffix = uuid.uuid4().hex[:8]
db = SessionLocal()
r = redis_sync.Redis.from_url("redis://localhost:6379/0", decode_responses=True)


def make_user(role, name, seq):
    u = User(
        email=f"e2e-{role}{seq}-{suffix}@test.dev",
        phone=f"+919{suffix}{seq:04d}",
        full_name=name,
        password_hash=hash_password("E2e@1234"),
        role=role,
        city="Belagavi",
        is_active=True,
        is_email_verified=True,
    )
    db.add(u)
    db.flush()
    db.add(Wallet(user_id=u.id, balance=0, total_earned=0, total_spent=0))
    if role == "CUSTOMER":
        db.add(CustomerProfile(user_id=u.id, area="Hanji Nagar",
                               default_latitude=15.8497, default_longitude=74.4977))
    else:
        db.add(WorkerProfile(user_id=u.id, city="Belagavi", area="Hanji Nagar",
                             latitude=15.8497, longitude=74.4977, experience_years=2,
                             languages="English", is_online=True, is_verified=True,
                             verification_status="APPROVED", working_radius_km=8.0))
    db.commit()
    return u


customer = make_user("CUSTOMER", "E2E Customer", 0)
workers = [make_user("WORKER", f"E2E Runner {i}", i + 1) for i in range(3)]
cust_token = create_access_token(customer.id, customer.role)
w_tokens = [create_access_token(w.id, w.role) for w in workers]

PAYLOAD = {
    "title": "Ring-down E2E verification task",
    "description": "Collect a sealed envelope near Hanji Nagar and deliver it to the sub-registrar office before 5 PM.",
    "task_type": "document_submission",
    "urgency": "normal",
    "scheduled_date": "2026-10-14",
    "scheduled_time": "14:00",
    "estimated_duration_minutes": 90,
    "latitude": 15.8497,
    "longitude": 74.4977,
    "address_text": "12 MG Road, Hanji Nagar, Belagavi",
    "area_name": "Hanji Nagar",
    "city": "Belagavi",
    "budget": 350,
    "required_skills": ["document_submission"],
}


def create_and_confirm():
    headers = {"Authorization": f"Bearer {cust_token}"}
    t = httpx.post(f"{BASE}/tasks", json=PAYLOAD, headers=headers, timeout=30)
    assert t.status_code == 201, t.text
    tid = t.json()["data"]["task"]["id"]
    c = httpx.post(f"{BASE}/tasks/{tid}/confirm", headers=headers, timeout=60)
    assert c.status_code == 200, c.text
    return tid, c.json()["data"]["task"]["status"]


async def main():
    uri = f"ws://localhost:8000/ws?token={w_tokens[0]}"
    async with websockets.connect(uri) as ws:
        tid, status = await asyncio.to_thread(create_and_confirm)
        print(f"1. confirmed task {tid} -> {status}")

        raw = await asyncio.wait_for(ws.recv(), timeout=15)
        msg = json.loads(raw)
        d = msg["data"]
        assert msg["event"] == "TASK_OFFER", msg
        assert d["task_id"] == tid and d["expires_in"] == 30
        print(f"2. WS TASK_OFFER -> worker0 (expires_in={d['expires_in']}s, "
              f"earnings={d['estimated_earnings']}, km={d['distance_km']})")
        assert d["estimated_earnings"] == 315.0

        queued = r.zcard(f"dispatch:task:{tid}:candidates")
        print(f"3. redis candidates queued after first offer: {queued}")
        assert queued == 2

    for i in range(3):
        resp = await asyncio.to_thread(
            lambda i=i: httpx.post(f"{BASE}/tasks/{tid}/reject",
                                   headers={"Authorization": f"Bearer {w_tokens[i]}"}, timeout=30)
        )
        assert resp.status_code == 200, resp.text
    print("4. all three workers rejected")

    db.expire_all()
    pend = db.query(TaskOffer).filter(TaskOffer.task_id == tid, TaskOffer.status == "PENDING").all()
    print(f"5. surge: pending offers to {len(pend)} worker(s)")
    assert len(pend) == 3
    db.expire_all()
    for w in workers:
        prof = db.query(WorkerProfile).filter(WorkerProfile.user_id == w.id).one()
        assert prof.missed_offers == 1, (w.full_name, prof.missed_offers)
    print("6. every worker has missed_offers == 1")

    acc = await asyncio.to_thread(
        lambda: httpx.post(f"{BASE}/tasks/{tid}/accept",
                           headers={"Authorization": f"Bearer {w_tokens[1]}"}, timeout=30)
    )
    assert acc.status_code == 200, acc.text
    task = acc.json()["data"]["task"]
    print(f"7. worker1 accepted -> status={task['status']}, assigned={task['assigned_worker_id'] == workers[1].id}")
    assert task["status"] == "ACCEPTED"

    lock = r.get(f"lock:task:{tid}")
    print(f"8. redis lock:task = {lock == workers[1].id}")
    assert lock == workers[1].id
    assert r.zcard(f"dispatch:task:{tid}:candidates") == 0
    print("9. candidate queue drained")

    late = await asyncio.to_thread(
        lambda: httpx.post(f"{BASE}/tasks/{tid}/accept",
                           headers={"Authorization": f"Bearer {w_tokens[2]}"}, timeout=30)
    )
    print(f"10. late accept blocked -> {late.status_code}")
    assert late.status_code == 409

    # cleanup
    r.delete(f"lock:task:{tid}", f"dispatch:task:{tid}:candidates")
    for u in [customer, *workers]:
        obj = db.get(User, u.id)
        db.delete(obj)
    db.commit()
    left = db.query(Task).filter(Task.id == tid).count()
    print(f"11. cleanup done (task cascaded away: {left == 0})")
    print("E2E OK")


asyncio.run(main())
db.close()
