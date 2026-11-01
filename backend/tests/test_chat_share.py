"""Task-scoped chat (REST + WebSocket), 24 h auto-close, and public tracking
share links. Also asserts the anonymous payload never leaks personal data."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.timeutils import utcnow
from app.models import Conversation, Message, Notification, Task
from tests.conftest import auth_headers, make_user, task_payload


@pytest.fixture(autouse=True)
def _clean_tracking_state():
    from app.tracking import hub, service

    def _wipe():
        service._last_ping.clear()
        service._routes.clear()
        hub._latest_local.clear()
        hub._history_local.clear()
        hub._subs.clear()

    _wipe()
    yield
    _wipe()


@pytest.fixture()
def fake_route(monkeypatch):
    from app.tracking.geo import build_route_state

    async def _fake(origin, destination):
        return build_route_state([(15.8497, 74.4977), (15.8497, 74.5100)], 8.0)

    monkeypatch.setattr("app.tracking.service.fetch_route", _fake)


def _make_task(db, customer, worker, *, status="ACCEPTED", completed_at=None):
    payload = task_payload()
    task = Task(
        customer_id=customer.id,
        title=payload["title"],
        description=payload["description"],
        task_type=payload["task_type"],
        status=status,
        urgency=payload["urgency"],
        latitude=payload["latitude"],
        longitude=payload["longitude"],
        address_text=payload["address_text"],
        area_name=payload["area_name"],
        city=payload["city"],
        budget=payload["budget"],
        assigned_worker_id=worker.id if worker else None,
        completed_at=completed_at,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _make_conversation(db, task):
    conv = Conversation(
        task_id=task.id, customer_id=task.customer_id, worker_id=task.assigned_worker_id
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


# ------------------------------------------------------------------ chat REST --


def test_chat_rest_send_list_and_unread(client, db):
    customer = make_user(db, "CUSTOMER", full_name="Kavya Rao")
    worker = make_user(db, "WORKER", full_name="Ravi Naik")
    task = _make_task(db, customer, worker)

    opened = client.post(
        f"/api/v1/conversations?task_id={task.id}", headers=auth_headers(customer)
    )
    assert opened.status_code == 201
    conv = opened.json()["data"]["conversation"]
    assert conv["chat_open"] is True
    conversation_id = conv["id"]

    sent = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"body": "  I'm at the courier office now.  "},
        headers=auth_headers(customer),
    )
    assert sent.status_code == 201
    assert sent.json()["data"]["message"]["body"] == "I'm at the courier office now."

    worker_feed = client.get("/api/v1/conversations", headers=auth_headers(worker)).json()["data"]["items"]
    mine = next(item for item in worker_feed if item["id"] == conversation_id)
    assert mine["unread_count"] == 1
    assert mine["chat_open"] is True
    assert mine["counterpart_name"] == "Kavya Rao"
    assert mine["counterpart_avatar"] is None

    messages = client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=auth_headers(worker)
    )
    assert messages.status_code == 200
    assert messages.json()["data"]["total"] == 1
    # Fetching the thread marks the counterpart's message read.
    worker_feed = client.get("/api/v1/conversations", headers=auth_headers(worker)).json()["data"]["items"]
    assert next(i for i in worker_feed if i["id"] == conversation_id)["unread_count"] == 0

    note = db.query(Notification).filter_by(user_id=worker.id, type="MESSAGE_RECEIVED").one()
    assert "Kavya Rao" in note.title
    assert note.data["conversation_id"] == conversation_id

    outsider = make_user(db, "CUSTOMER")
    denied = client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=auth_headers(outsider)
    )
    assert denied.status_code == 403


def test_chat_masks_phone_numbers_everywhere(client, db):
    customer = make_user(db, "CUSTOMER", full_name="Kavya Rao")
    worker = make_user(db, "WORKER", full_name="Ravi Naik")
    task = _make_task(db, customer, worker)
    conv = _make_conversation(db, task)

    raw = "Call me on 98765 43210 if you need help. Start code 5243, budget 300."
    sent = client.post(
        f"/api/v1/conversations/{conv.id}/messages",
        json={"body": raw},
        headers=auth_headers(customer),
    )
    assert sent.status_code == 201
    body = sent.json()["data"]["message"]["body"]
    assert "98765" not in body and "43210" not in body
    assert "+91 ••••• •3210" in body
    assert "5243" in body and "300" in body

    stored = db.query(Message).filter_by(conversation_id=conv.id).one()
    assert "98765" not in stored.body

    note = db.query(Notification).filter_by(user_id=worker.id, type="MESSAGE_RECEIVED").one()
    assert "98765" not in note.body

    # Rows written before masking shipped are masked when read back.
    db.add(
        Message(
            conversation_id=conv.id,
            sender_id=worker.id,
            body="Reach me at +91-9123456789",
        )
    )
    db.commit()
    feed = client.get(
        f"/api/v1/conversations/{conv.id}/messages", headers=auth_headers(customer)
    )
    bodies = [m["body"] for m in feed.json()["data"]["items"]]
    assert all("9123456789" not in b for b in bodies)
    assert any("•6789" in b for b in bodies)


def test_chat_auto_closes_24h_after_task_completion(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_task(
        db, customer, worker, status="COMPLETED", completed_at=utcnow() - timedelta(hours=25)
    )
    conversation = _make_conversation(db, task)

    read = client.get(
        f"/api/v1/conversations/{conversation.id}/messages", headers=auth_headers(customer)
    )
    assert read.status_code == 409
    assert read.json()["error"]["code"] == "CHAT_CLOSED"

    write = client.post(
        f"/api/v1/conversations/{conversation.id}/messages",
        json={"body": "After the deadline"},
        headers=auth_headers(worker),
    )
    assert write.status_code == 409
    assert write.json()["error"]["code"] == "CHAT_CLOSED"

    feed = client.get("/api/v1/conversations", headers=auth_headers(customer)).json()["data"]["items"]
    item = next(i for i in feed if i["id"] == conversation.id)
    assert item["chat_open"] is False
    assert item["closes_at"] is not None
    assert item["closed_at"] is None  # computed lazily until the sweeper runs

    from app.services import MessagingService

    assert MessagingService(db).close_due_conversations() == 1
    db.commit()
    db.expire_all()
    assert db.get(Conversation, conversation.id).closed_at is not None
    assert MessagingService(db).close_due_conversations() == 0


def test_chat_stays_open_during_grace_period(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_task(
        db, customer, worker, status="COMPLETED", completed_at=utcnow() - timedelta(hours=2)
    )
    conversation = _make_conversation(db, task)

    sent = client.post(
        f"/api/v1/conversations/{conversation.id}/messages",
        json={"body": "Thanks for the help!"},
        headers=auth_headers(customer),
    )
    assert sent.status_code == 201

    feed = client.get("/api/v1/conversations", headers=auth_headers(customer)).json()["data"]["items"]
    item = next(i for i in feed if i["id"] == conversation.id)
    assert item["chat_open"] is True
    assert item["closes_at"] is not None


def test_cancelled_task_chat_closes_after_grace(client, db):
    from app.services import MessagingService

    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_task(db, customer, worker, status="CANCELLED")
    task.cancelled_at = utcnow() - timedelta(hours=24, minutes=5)
    db.commit()
    conversation = _make_conversation(db, task)

    assert MessagingService(db).close_due_conversations() == 1
    db.commit()
    db.expire_all()
    assert db.get(Conversation, conversation.id).closed_at is not None


# -------------------------------------------------------------- chat over WS --


def test_chat_ws_persists_and_pushes_to_counterpart(client, db, monkeypatch):
    delivered: list[tuple[str, str, dict]] = []

    async def _fake_send(user_id, event, data):
        delivered.append((user_id, event, data))
        return True

    monkeypatch.setattr("app.websocket.manager.manager.send_to_user", _fake_send)

    customer = make_user(db, "CUSTOMER", full_name="Kavya Rao")
    worker = make_user(db, "WORKER", full_name="Ravi Naik")
    task = _make_task(db, customer, worker)
    token = auth_headers(customer)["Authorization"].split()[-1]

    with client.websocket_connect(f"/ws/chat/{task.id}?token={token}") as ws:
        ready = ws.receive_json()
        assert ready["event"] == "chat_ready"
        assert ready["data"]["task_id"] == task.id
        conversation_id = ready["data"]["conversation_id"]

        ws.send_json({"event": "send_message", "data": {"body": "On my way"}})
        ack = ws.receive_json()
        assert ack["event"] == "message_sent"
        assert ack["data"]["body"] == "On my way"
        assert ack["data"]["sender_name"] == "Kavya Rao"

        ws.send_json({"event": "read", "data": {}})
        read = ws.receive_json()
        assert read["event"] == "read"

    db.expire_all()
    row = db.query(Message).filter(Message.conversation_id == conversation_id).one()
    assert row.body == "On my way"
    assert any(
        uid == worker.id and event == "message" and data["body"] == "On my way"
        for uid, event, data in delivered
    )
    note = db.query(Notification).filter_by(user_id=worker.id, type="MESSAGE_RECEIVED").one()
    assert note.data["conversation_id"] == conversation_id


def test_chat_ws_alias_route_and_stranger_rejection(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    stranger = make_user(db, "CUSTOMER")
    task = _make_task(db, customer, worker)

    customer_token = auth_headers(customer)["Authorization"].split()[-1]
    with client.websocket_connect(f"/api/v1/ws/chat/{task.id}?token={customer_token}") as ws:
        assert ws.receive_json()["event"] == "chat_ready"

    stranger_token = auth_headers(stranger)["Authorization"].split()[-1]
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/chat/{task.id}?token={stranger_token}") as ws:
            ws.receive_json()


def test_chat_ws_reports_closed_conversation(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_task(
        db, customer, worker, status="COMPLETED", completed_at=utcnow() - timedelta(hours=30)
    )
    _make_conversation(db, task)
    token = auth_headers(customer)["Authorization"].split()[-1]

    with client.websocket_connect(f"/ws/chat/{task.id}?token={token}") as ws:
        event = ws.receive_json()
        assert event["event"] == "chat_closed"


def test_chat_ws_send_after_close_returns_error(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_task(db, customer, worker)
    conversation = _make_conversation(db, task)
    conversation.closed_at = utcnow() - timedelta(minutes=1)
    db.commit()
    token = auth_headers(customer)["Authorization"].split()[-1]

    with client.websocket_connect(f"/ws/chat/{task.id}?token={token}") as ws:
        assert ws.receive_json()["event"] == "chat_closed"


# ------------------------------------------------------------ share links --


def test_share_link_create_resolve_and_privacy(client, db, fake_route):
    customer = make_user(db, "CUSTOMER", full_name="Kavya Rao")
    worker = make_user(db, "WORKER", full_name="Ravi Naik")
    task = _make_task(db, customer, worker)
    task.latitude, task.longitude = 15.8600, 74.5100
    db.commit()
    token = auth_headers(customer)["Authorization"].split()[-1]

    created = client.post(f"/api/v1/tasks/{task.id}/share", headers=auth_headers(customer))
    assert created.status_code == 200, created.text
    share = created.json()["data"]["share"]
    assert share["token"] and len(share["token"]) <= 64
    assert share["path"] == f"/track/{share['token']}"
    assert share["expires_at"] is not None

    # Idempotent while the link is still valid.
    again = client.post(f"/api/v1/tasks/{task.id}/share", headers=auth_headers(customer))
    assert again.json()["data"]["share"]["token"] == share["token"]

    public = client.get(f"/api/v1/public/track/{share['token']}")
    assert public.status_code == 200, public.text
    assert public.headers["cache-control"] == "no-store"
    tracking = public.json()["data"]["tracking"]
    assert tracking["status"] == "ACCEPTED"
    assert tracking["worker"]["full_name"] == "Ravi Naik"
    assert tracking["destination"]["city"] == "Belagavi"
    assert tracking["route"] is not None

    # Nothing personal or internally identifying may leak to an anonymous viewer.
    raw = public.text
    assert worker.phone not in raw
    assert worker.email not in raw
    assert customer.phone not in raw
    assert customer.email not in raw
    assert worker.id not in raw
    assert customer.id not in raw
    assert task.id not in raw
    assert task.address_text not in raw
    assert "phone" not in tracking and "email" not in tracking
    assert "address_text" not in tracking["destination"]

    # The authenticated task payload also strips contact details of both sides.
    task_view = client.get(f"/api/v1/tasks/{task.id}", headers=auth_headers(customer)).json()["data"]["task"]
    assert "phone" not in task_view["customer"]
    assert "phone" not in task_view["worker"]
    assert "email" not in task_view["worker"]

    denied = client.post(f"/api/v1/tasks/{task.id}/share", headers=auth_headers(worker))
    assert denied.status_code == 403


def test_share_link_requires_trackable_task(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_task(db, customer, worker, status="PENDING_CONFIRMATION")

    resp = client.post(f"/api/v1/tasks/{task.id}/share", headers=auth_headers(customer))
    assert resp.status_code == 409
    assert "worker accepts" in resp.json()["error"]["message"]


def test_share_link_rotation_revocation_and_expiry(client, db, fake_route):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_task(db, customer, worker)

    first = client.post(f"/api/v1/tasks/{task.id}/share", headers=auth_headers(customer))
    first_token = first.json()["data"]["share"]["token"]

    rotated = client.post(
        f"/api/v1/tasks/{task.id}/share",
        json={"rotate": True, "expires_in_hours": 999},
        headers=auth_headers(customer),
    )
    rotated_token = rotated.json()["data"]["share"]["token"]
    assert rotated_token != first_token
    assert client.get(f"/api/v1/public/track/{first_token}").status_code == 404

    from app.core.config import settings

    expires = rotated.json()["data"]["share"]["expires_at"]
    assert expires is not None
    # Requested 999 h is clamped to the configured ceiling.
    from app.core.timeutils import as_aware

    task_db = db.get(Task, task.id)
    db.refresh(task_db)
    ttl_hours = (as_aware(task_db.share_token_expires_at) - utcnow()).total_seconds() / 3600
    assert ttl_hours <= settings.tracking_share_max_hours + 0.1

    task_db.share_token_expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    expired = client.get(f"/api/v1/public/track/{rotated_token}")
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "SHARE_LINK_EXPIRED"

    # Revocation after re-issuing kills the link immediately.
    fresh = client.post(f"/api/v1/tasks/{task.id}/share", headers=auth_headers(customer))
    fresh_token = fresh.json()["data"]["share"]["token"]
    revoked = client.delete(f"/api/v1/tasks/{task.id}/share", headers=auth_headers(customer))
    assert revoked.status_code == 200
    assert client.get(f"/api/v1/public/track/{fresh_token}").status_code == 404
    assert client.get("/api/v1/public/track/not-a-real-token").status_code == 404


def test_public_track_includes_latest_telemetry_but_no_task_id(client, db, fake_route):
    import asyncio

    from app.tracking import service

    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_task(db, customer, worker)

    asyncio.run(
        service.ingest_worker_position(db, worker, task.id, 15.8497, 74.5038, speed_kmph=24.0)
    )
    token = (
        client.post(f"/api/v1/tasks/{task.id}/share", headers=auth_headers(customer))
        .json()["data"]["share"]["token"]
    )

    tracking = client.get(f"/api/v1/public/track/{token}").json()["data"]["tracking"]
    assert tracking["latest"]["latitude"] == pytest.approx(15.8497)
    assert tracking["latest"]["eta_minutes"] > 0
    assert "task_id" not in tracking["latest"]
    assert "task_id" not in tracking
    assert tracking["worker"]["rating_average"] >= 0

    # The owner can inspect the current link without rotating it.
    current = client.get(f"/api/v1/tasks/{task.id}/share", headers=auth_headers(customer))
    assert current.json()["data"]["share"]["token"] == token


def test_share_link_cannot_be_created_for_someone_elses_task(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    other_customer = make_user(db, "CUSTOMER")
    task = _make_task(db, customer, worker)

    resp = client.post(f"/api/v1/tasks/{task.id}/share", headers=auth_headers(other_customer))
    assert resp.status_code == 403


def test_chat_ws_requires_valid_token(client, db):
    customer = make_user(db, "CUSTOMER")
    worker = make_user(db, "WORKER")
    task = _make_task(db, customer, worker)

    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/chat/{task.id}?token=bogus") as ws:
            ws.receive_json()
