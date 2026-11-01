"""Live E2E: SOS freeze + admin paging over real Postgres/Redis/WebSocket."""
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
from app.models import CustomerProfile, Task, TaskSosAlert, User, Wallet, WorkerProfile

BASE = "http://localhost:8000/api/v1"
suffix = uuid.uuid4().hex[:8]
db = SessionLocal()
r = redis_sync.Redis.from_url("redis://localhost:6379/0", decode_responses=True)


def make_user(role, name, seq):
    u = User(
        email=f"sos-{role}{seq}-{suffix}@test.dev",
        phone=f"+918{suffix}{seq:04d}",
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
    elif role == "WORKER":
        db.add(WorkerProfile(user_id=u.id, city="Belagavi", area="Hanji Nagar",
                             latitude=15.8497, longitude=74.4977, experience_years=2,
                             languages="English", is_online=True, is_verified=True,
                             verification_status="APPROVED", working_radius_km=8.0))
    db.commit()
    return u


admin = make_user("ADMIN", "Akash E2E Admin", 0)
customer = make_user("CUSTOMER", "SOS Customer", 1)
worker = make_user("WORKER", "SOS Runner", 2)
t_admin = create_access_token(admin.id, admin.role)
t_customer = create_access_token(customer.id, customer.role)
t_worker = create_access_token(worker.id, worker.role)

PAYLOAD = {
    "title": "SOS E2E verification task",
    "description": "Collect a sealed envelope near Hanji Nagar and deliver it to the sub-registrar office.",
    "task_type": "document_submission",
    "urgency": "normal",
    "scheduled_date": "2026-10-15",
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


def create_confirm_accept():
    h = {"Authorization": f"Bearer {t_customer}"}
    t = httpx.post(f"{BASE}/tasks", json=PAYLOAD, headers=h, timeout=30)
    assert t.status_code == 201, t.text
    tid = t.json()["data"]["task"]["id"]
    c = httpx.post(f"{BASE}/tasks/{tid}/confirm", headers=h, timeout=60)
    assert c.status_code == 200, c.text
    a = httpx.post(f"{BASE}/tasks/{tid}/accept",
                   headers={"Authorization": f"Bearer {t_worker}"}, timeout=30)
    assert a.status_code == 200, a.text
    return tid, a.json()["data"]["task"]["status"]


async def main():
    admin_ws_uri = f"ws://localhost:8000/ws?token={t_admin}"
    worker_ws_uri = f"ws://localhost:8000/ws?token={t_worker}"
    async with websockets.connect(admin_ws_uri) as admin_ws, \
               websockets.connect(worker_ws_uri) as worker_ws:
        tid, status = await asyncio.to_thread(create_confirm_accept)
        print(f"1. assigned task {tid} -> {status}")

        for i in range(3):
            await worker_ws.send(json.dumps({
                "event": "location_update",
                "data": {"task_id": tid, "latitude": 15.8497 + i * 0.0002,
                         "longitude": 74.4977 + i * 0.0002, "speed_kmph": 21.0},
            }))
            await asyncio.sleep(3.3)  # telemetry throttle is 3s

        # Ingestion is async and serialized behind OSRM calls — poll the ring
        # until every accepted fix has landed.
        hist_len = 0
        for _ in range(30):
            hist_len = r.llen(f"tracking:history:task:{tid}")
            if hist_len >= 3:
                break
            await asyncio.sleep(1.0)
        latest_raw = r.get(f"tracking:latest:task:{tid}")
        latest = json.loads(latest_raw) if latest_raw else {}
        print(f"2. redis history={hist_len} latest=({latest.get('latitude')},{latest.get('longitude')}) "
              f"snapped={latest.get('snapped')} remaining={latest.get('remaining_km')}km")
        assert hist_len == 3, hist_len

        sos = await asyncio.to_thread(
            lambda: httpx.post(f"{BASE}/tasks/{tid}/sos",
                               json={"message": "Unsafe area, please check on me."},
                               headers={"Authorization": f"Bearer {t_customer}"}, timeout=30)
        )
        assert sos.status_code == 201, sos.text
        alert = sos.json()["data"]["alert"]
        print(f"3. SOS -> alert {alert['status']} previous={alert['previous_status']} "
              f"frozen={len(alert['location_history'])} task={sos.json()['data']['task']['status']}")
        assert len(alert["location_history"]) == 3
        assert sos.json()["data"]["task"]["status"] == "EMERGENCY_ALERT"

        event = None
        seen = []
        for _ in range(6):
            msg = json.loads(await asyncio.wait_for(admin_ws.recv(), timeout=10))
            seen.append(msg["event"])
            if msg["event"] == "EMERGENCY_ALERT":
                event = msg
                break
        print(f"4. admin WS events={seen} task={event and event['data']['task_id'] == tid}")
        assert event is not None and event["data"]["task_id"] == tid

        listed = await asyncio.to_thread(
            lambda: httpx.get(f"{BASE}/admin/sos-alerts?status=OPEN",
                              headers={"Authorization": f"Bearer {t_admin}"}, timeout=30)
        )
        assert listed.status_code == 200, listed.text
        ids = [item["id"] for item in listed.json()["data"]["items"]]
        print(f"5. admin sees open alerts={len(ids)} includes_ours={alert['id'] in ids}")
        assert alert["id"] in ids

        resolved = await asyncio.to_thread(
            lambda: httpx.post(f"{BASE}/admin/sos-alerts/{alert['id']}/resolve",
                               json={"note": "Called the customer; all safe."},
                               headers={"Authorization": f"Bearer {t_admin}"}, timeout=30)
        )
        assert resolved.status_code == 200, resolved.text
        print(f"6. resolved -> {resolved.json()['data']['alert']['status']}")

        db.expire_all()
        task = db.get(Task, tid)
        assert task.status == "ACCEPTED", task.status
        print(f"7. task restored -> {task.status}")

        # duplicate SOS must be refused only while open; after resolve a new one is allowed
        again = await asyncio.to_thread(
            lambda: httpx.post(f"{BASE}/tasks/{tid}/sos", json={},
                               headers={"Authorization": f"Bearer {t_worker}"}, timeout=30)
        )
        assert again.status_code == 201, again.text
        print("8. fresh SOS after resolution -> 201")

    # cleanup
    r.delete(f"tracking:history:task:{tid}", f"tracking:latest:task:{tid}",
             f"channel:tracking:task:{tid}")
    for u in (admin, customer, worker):
        obj = db.get(User, u.id)
        if obj:
            db.delete(obj)
    db.commit()
    left_task = db.query(Task).filter(Task.id == tid).count()
    left_alerts = db.query(TaskSosAlert).filter(TaskSosAlert.task_id == tid).count()
    print(f"9. cleanup: task={left_task} alerts={left_alerts}")
    assert left_task == 0 and left_alerts == 0
    print("SOS E2E OK")


asyncio.run(main())
db.close()
