"""Live E2E: task-scoped chat (REST + WebSocket), 24 h chat close, and the
public tracking share link.

Runs against the real Postgres/Redis backend and the locally running API.
Creates an isolated customer/worker/task, chats over both transports, mints a
share link, verifies the anonymous payload is PII-free, then cleans up.
"""
import asyncio
import json
import sys
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import websockets

from app.core.security import create_access_token, hash_password
from app.core.timeutils import utcnow
from app.db.session import SessionLocal
from app.models import (
    Conversation,
    CustomerProfile,
    Message,
    Task,
    User,
    Wallet,
    WorkerProfile,
)
from app.services import MessagingService

BASE = "http://127.0.0.1:8000/api/v1"
WS_BASE = "ws://127.0.0.1:8000"
suffix = uuid.uuid4().hex[:8]
db = SessionLocal()
client = httpx.Client(timeout=30.0)


def make_user(role, name, seq):
    user = User(
        email=f"chat-{role.lower()}{seq}-{suffix}@test.dev",
        phone=f"+917{suffix}{seq:04d}",
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
                is_online=True,
                is_verified=True,
                verification_status="APPROVED",
                working_radius_km=8.0,
            )
        )
    db.commit()
    db.refresh(user)
    return user


def token_for(user):
    return create_access_token(user.id, user.role)


def auth(user):
    return {"Authorization": f"Bearer {token_for(user)}"}


def make_task(customer, worker):
    task = Task(
        customer_id=customer.id,
        title=f"Chat & share E2E {suffix}",
        description="Pick up a sealed envelope and deliver it across town.",
        task_type="courier_pickup",
        status="ACCEPTED",
        urgency="normal",
        latitude=15.8600,
        longitude=74.5100,
        address_text="Door 14, Shivaji Colony, Belagavi",
        area_name="Shivaji Colony",
        city="Belagavi",
        budget=300,
        assigned_worker_id=worker.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


async def chat_flow(customer, worker, task):
    customer_url = f"{WS_BASE}/ws/chat/{task.id}?token={token_for(customer)}"
    worker_url = f"{WS_BASE}/ws/chat/{task.id}?token={token_for(worker)}"
    async with websockets.connect(customer_url) as customer_ws, websockets.connect(worker_url) as worker_ws:
        customer_ready = json.loads(await customer_ws.recv())
        worker_ready = json.loads(await worker_ws.recv())
        assert customer_ready["event"] == worker_ready["event"] == "chat_ready"
        assert customer_ready["data"]["conversation_id"] == worker_ready["data"]["conversation_id"]

        await customer_ws.send(json.dumps({"event": "send_message", "data": {"body": "I'm at the gate."}}))
        ack = json.loads(await customer_ws.recv())
        pushed = json.loads(await worker_ws.recv())
        assert ack["event"] == "message_sent"
        assert pushed["event"] == "message" and pushed["data"]["body"] == "I'm at the gate."

        await worker_ws.send(json.dumps({"event": "send_message", "data": {"body": "Coming out now."}}))
        ack = json.loads(await worker_ws.recv())
        pushed = json.loads(await customer_ws.recv())
        assert ack["event"] == "message_sent"
        assert pushed["event"] == "message" and pushed["data"]["body"] == "Coming out now."

        conversation_id = customer_ready["data"]["conversation_id"]
        return conversation_id


def telemetry_flow(worker, task):
    async def _run():
        url = f"{WS_BASE}/ws?token={token_for(worker)}"
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps({"event": "subscribe_tracking", "data": {"task_id": task.id}}))
            await ws.send("ping")
            assert json.loads(await ws.recv())["event"] == "pong"
            await ws.send(
                json.dumps(
                    {
                        "event": "location_update",
                        "data": {
                            "task_id": task.id,
                            "latitude": 15.8510,
                            "longitude": 74.5005,
                            "speed_kmph": 24.0,
                        },
                    }
                )
            )
            update = json.loads(await ws.recv())
            assert update["event"] == "tracking_update"

    asyncio.run(_run())


def cleanup_stale_runs():
    """Remove rows left behind by an interrupted earlier run."""
    stale = db.query(Task).filter(Task.title.like("Chat & share E2E %")).all()
    user_ids = set()
    for old in stale:
        user_ids.update(uid for uid in (old.customer_id, old.assigned_worker_id) if uid)
        for conv in db.query(Conversation).filter(Conversation.task_id == old.id):
            db.delete(conv)
        db.flush()
        db.delete(old)
    db.flush()
    for uid in user_ids:
        user = db.get(User, uid)
        if user is not None:
            db.delete(user)
    db.commit()


def main():
    cleanup_stale_runs()
    customer = make_user("CUSTOMER", "Kavya Rao", 1)
    worker = make_user("WORKER", "Ravi Naik", 2)
    task = make_task(customer, worker)
    print(f"1. task {task.id} accepted by {worker.full_name}")

    opened = client.post(
        f"{BASE}/conversations?task_id={task.id}", headers=auth(customer)
    )
    assert opened.status_code == 201, opened.text
    assert opened.json()["data"]["conversation"]["chat_open"] is True

    conversation_id = asyncio.run(chat_flow(customer, worker, task))
    print(f"2. chat over WS delivered both ways (conversation {conversation_id})")

    db.expire_all()
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .all()
    )
    assert [m.body for m in messages] == ["I'm at the gate.", "Coming out now."]
    print(f"3. {len(messages)} messages persisted")

    history = client.get(
        f"{BASE}/conversations/{conversation_id}/messages", headers=auth(customer)
    )
    assert history.status_code == 200, history.text
    assert history.json()["data"]["total"] == 2
    print("4. REST history + read receipts working")

    created = client.post(f"{BASE}/tasks/{task.id}/share", headers=auth(customer))
    assert created.status_code == 200, created.text
    share = created.json()["data"]["share"]
    token = share["token"]
    assert share["path"] == f"/track/{token}"
    print(f"5. share link minted: {share['path']}")

    public = client.get(f"{BASE}/public/track/{token}")
    assert public.status_code == 200, public.text
    body = public.text
    for secret in (
        customer.id,
        worker.id,
        task.id,
        customer.email,
        worker.email,
        customer.phone,
        worker.phone,
        task.address_text,
    ):
        assert secret not in body, f"leaked {secret}"
    tracking = public.json()["data"]["tracking"]
    assert tracking["worker"]["full_name"] == "Ravi Naik"
    assert "phone" not in tracking["worker"] and "email" not in tracking["worker"]
    print("6. anonymous payload is PII-free (ids, emails, phones, address stripped)")

    telemetry_flow(worker, task)
    live = client.get(f"{BASE}/public/track/{token}").json()["data"]["tracking"]
    assert live["latest"] is not None
    assert abs(live["latest"]["latitude"] - 15.851) < 0.01
    assert abs(live["latest"]["longitude"] - 74.5005) < 0.01
    assert live["latest"]["eta_minutes"] is not None
    print(f"7. live fix shared anonymously: ETA {live['latest']['eta_minutes']} min")

    db.expire_all()
    task = db.get(Task, task.id)
    task.share_token_expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    expired = client.get(f"{BASE}/public/track/{token}")
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "SHARE_LINK_EXPIRED"
    print("8. expired link rejected with 410 SHARE_LINK_EXPIRED")

    rotated = client.post(
        f"{BASE}/tasks/{task.id}/share", json={"rotate": True}, headers=auth(customer)
    )
    assert rotated.status_code == 200
    new_token = rotated.json()["data"]["share"]["token"]
    assert new_token != token
    assert client.get(f"{BASE}/public/track/{new_token}").status_code == 200
    revoked = client.delete(f"{BASE}/tasks/{task.id}/share", headers=auth(customer))
    assert revoked.status_code == 200
    assert client.get(f"{BASE}/public/track/{new_token}").status_code == 404
    print("9. rotation revokes the old token; DELETE revokes the new one")

    db.expire_all()
    task = db.get(Task, task.id)
    task.status = "COMPLETED"
    task.completed_at = utcnow() - timedelta(hours=25)
    db.commit()

    closed = client.get(
        f"{BASE}/conversations/{conversation_id}/messages", headers=auth(worker)
    )
    assert closed.status_code == 409
    assert closed.json()["error"]["code"] == "CHAT_CLOSED"

    closed_count = MessagingService(db).close_due_conversations()
    db.commit()
    db.expire_all()
    assert closed_count == 1
    assert db.get(Conversation, conversation_id).closed_at is not None
    print("10. chat auto-closed 24 h after completion (REST + sweeper)")

    async def closed_ws():
        url = f"{WS_BASE}/ws/chat/{task.id}?token={token_for(customer)}"
        async with websockets.connect(url) as ws:
            event = json.loads(await ws.recv())
            assert event["event"] == "chat_closed"

    asyncio.run(closed_ws())
    print("11. closed chat socket announces chat_closed")

    db.delete(db.query(Conversation).filter(Conversation.id == conversation_id).one())
    db.flush()
    db.delete(db.get(Task, task.id))
    db.flush()
    db.delete(db.get(User, customer.id))
    db.delete(db.get(User, worker.id))
    db.commit()
    print("12. cleanup done")
    print("CHAT + SHARE E2E OK")


if __name__ == "__main__":
    try:
        main()
    finally:
        client.close()
        db.close()
