"""WebSocket endpoint: /ws?token=<access JWT>

Pushes real-time events: notifications, chat messages, task status changes,
live worker tracking. Authentication happens via query param (browsers cannot
set headers on WS).

Client -> server messages (JSON):
  {"event": "subscribe_tracking",   "data": {"task_id": "..."}}
  {"event": "unsubscribe_tracking", "data": {"task_id": "..."}}
  {"event": "location_update",      "data": {"task_id": "...", "latitude": ..,
                                              "longitude": .., "heading": ..,
                                              "speed_kmph": ..}}
"""

import json

import jwt as pyjwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.core.security import decode_token
from app.db.session import SessionLocal
from app.repositories import UserRepository
from app.websocket.manager import manager

logger = get_logger("ws")

ws_router = APIRouter()
chat_ws_router = APIRouter()


async def _authenticate(websocket: WebSocket, token: str) -> str | None:
    try:
        payload = decode_token(token, expected_type="access")
        user_id = payload["sub"]
    except pyjwt.InvalidTokenError:
        await websocket.close(code=4401)
        return None

    db = SessionLocal()
    try:
        user = UserRepository(db).get_by_id(user_id)
        if user is None or not user.is_active:
            await websocket.close(code=4403)
            return None
    finally:
        db.close()
    return user_id


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(default="")):
    user_id: str | None = None
    try:
        payload = decode_token(token, expected_type="access")
        user_id = payload["sub"]
    except pyjwt.InvalidTokenError:
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    try:
        user = UserRepository(db).get_by_id(user_id)
        if user is None or not user.is_active:
            await websocket.close(code=4403)
            return
    finally:
        db.close()

    await manager.connect(websocket, user_id)
    try:
        while True:
            raw = await websocket.receive_text()
            if raw in ("ping", '"ping"'):
                await websocket.send_json({"event": "pong", "data": {}})
                continue
            await _handle_message(user_id, raw)
    except WebSocketDisconnect:
        await manager.disconnect(websocket, user_id)
        _after_disconnect(user_id)
    except Exception:
        logger.exception("ws_error user=%s", user_id)
        await manager.disconnect(websocket, user_id)
        _after_disconnect(user_id)


def _after_disconnect(user_id: str) -> None:
    from app.tracking.hub import hub

    hub.unsubscribe_user(user_id)


async def _handle_message(user_id: str, raw: str) -> None:
    from app.tracking.hub import hub
    from app.tracking.service import ingest_worker_position

    try:
        message = json.loads(raw)
        event = message.get("event")
        data = message.get("data") or {}
        task_id = str(data.get("task_id") or "")
    except Exception:
        return
    if not task_id:
        return

    if event in ("subscribe_tracking", "unsubscribe_tracking"):
        if event == "subscribe_tracking" and await _can_watch(user_id, task_id):
            hub.subscribe(task_id, user_id)
        else:
            hub.unsubscribe(task_id, user_id)
        return

    if event == "location_update":
        db = SessionLocal()
        try:
            worker = UserRepository(db).get_by_id(user_id)
            if worker is None or worker.role != "WORKER":
                return
            latitude = data.get("latitude")
            longitude = data.get("longitude")
            if latitude is None or longitude is None:
                return
            await ingest_worker_position(
                db,
                worker,
                task_id,
                latitude=float(latitude),
                longitude=float(longitude),
                heading=data.get("heading"),
                speed_kmph=data.get("speed_kmph"),
            )
        finally:
            db.close()


async def _can_watch(user_id: str, task_id: str) -> bool:
    from app.models import Task
    from app.models.enums import UserRole

    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if task is None:
            return False
        user = UserRepository(db).get_by_id(user_id)
        if user is None:
            return False
        if user.role == UserRole.ADMIN.value:
            return True
        return user_id in (task.customer_id, task.assigned_worker_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Task-scoped chat socket: /ws/chat/{task_id}?token=<access JWT>
#
# Client -> server:
#   {"event": "send_message", "data": {"body": "..."}}
#   {"event": "read",         "data": {}}
#   {"event": "ping"}
# Server -> sender:
#   {"event": "chat_ready", "data": {...}}
#   {"event": "message_sent", "data": {...}}
#   {"event": "chat_error", "data": {"code": "...", "message": "..."}}
# Server -> the other participant (via the shared connection manager):
#   {"event": "message", "data": {...}} / {"event": "read_receipt", "data": {...}}
# ---------------------------------------------------------------------------


def _chat_error(exc: AppException) -> dict:
    code = exc.code.value if hasattr(exc.code, "value") else str(exc.code)
    return {"event": "chat_error", "data": {"code": code, "message": exc.message}}


def _chat_context(user_id: str, task_id: str) -> dict | None:
    """Open (or lazily create) the conversation for one socket connection.
    Returns None when the caller is not a participant or no worker is assigned."""
    from app.models import Task
    from app.services import MessagingService

    db = SessionLocal()
    try:
        user = UserRepository(db).get_by_id(user_id)
        task = db.get(Task, task_id)
        if user is None or task is None:
            return None
        if user_id not in (task.customer_id, task.assigned_worker_id):
            return None
        service = MessagingService(db)
        if task.assigned_worker_id is None:
            return None
        conversation = service.get_or_create_for_task(task, user)
        closed = service.is_closed(conversation, task)
        closes_at = service.chat_closes_at(task)
        db.commit()
        return {
            "conversation_id": conversation.id,
            "closed": closed,
            "closes_at": closes_at.isoformat() if closes_at else None,
        }
    finally:
        db.close()


@chat_ws_router.websocket("/ws/chat/{task_id}")
async def chat_websocket_endpoint(
    websocket: WebSocket, task_id: str, token: str = Query(default="")
):
    user_id = await _authenticate(websocket, token)
    if user_id is None:
        return

    context = _chat_context(user_id, task_id)
    if context is None:
        await websocket.close(code=4403)
        return

    if context["closed"]:
        await websocket.accept()
        await websocket.send_json(
            {
                "event": "chat_closed",
                "data": {
                    "conversation_id": context["conversation_id"],
                    "message": "This conversation is closed.",
                },
            }
        )
        await websocket.close(code=4409)
        return

    await manager.connect(websocket, user_id)
    try:
        await websocket.send_json(
            {
                "event": "chat_ready",
                "data": {
                    "conversation_id": context["conversation_id"],
                    "task_id": task_id,
                    "closes_at": context["closes_at"],
                },
            }
        )
        while True:
            raw = await websocket.receive_text()
            if raw in ("ping", '"ping"'):
                await websocket.send_json({"event": "pong", "data": {}})
                continue
            await _handle_chat_message(
                websocket, user_id, task_id, context["conversation_id"], raw
            )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("chat_ws_error user=%s task=%s", user_id, task_id)
    finally:
        await manager.disconnect(websocket, user_id)


async def _handle_chat_message(
    websocket: WebSocket, user_id: str, task_id: str, conversation_id: str, raw: str
) -> None:
    from app.services import MessagingService

    try:
        message = json.loads(raw)
        event = message.get("event")
        data = message.get("data") or {}
    except Exception:
        await websocket.send_json(
            {"event": "chat_error", "data": {"code": "VALIDATION_ERROR", "message": "Malformed message."}}
        )
        return

    if event == "ping":
        await websocket.send_json({"event": "pong", "data": {}})
        return

    db = SessionLocal()
    try:
        service = MessagingService(db)
        conversation = service.get_conversation_or_404(conversation_id)
        user = UserRepository(db).get_by_id(user_id)
        if user is None:
            return

        if event == "send_message":
            body = data.get("body")
            sent = await service.send_message(conversation, user, str(body or ""))
            db.commit()
            await websocket.send_json(
                {"event": "message_sent", "data": service.message_payload(sent, user, conversation)}
            )
            return

        if event == "read":
            count = service.mark_read(conversation, user)
            db.commit()
            for participant_id in conversation.participant_ids():
                if participant_id != user_id:
                    await manager.send_to_user(
                        participant_id,
                        "read_receipt",
                        {
                            "conversation_id": conversation.id,
                            "reader_id": user_id,
                            "read_count": count,
                        },
                    )
            await websocket.send_json(
                {"event": "read", "data": {"conversation_id": conversation.id, "read_count": count}}
            )
            return

        await websocket.send_json(
            {"event": "chat_error", "data": {"code": "VALIDATION_ERROR", "message": f"Unknown event '{event}'."}}
        )
    except AppException as exc:
        db.rollback()
        await websocket.send_json(_chat_error(exc))
    except Exception:
        db.rollback()
        logger.exception("chat_ws_message_failed user=%s task=%s", user_id, task_id)
        await websocket.send_json(
            {"event": "chat_error", "data": {"code": "INTERNAL_ERROR", "message": "Message could not be sent."}}
        )
    finally:
        db.close()
