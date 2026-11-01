"""Central notification dispatcher: every domain event funnels through here so
in-app persistence, WebSocket push, and (future) email/SMS stay consistent."""

import asyncio

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.notifications.channels import (
    InAppChannel,
    OutgoingNotification,
    get_email_channel,
    get_sms_channel,
)
from app.websocket.manager import fire_and_forget, manager

logger = get_logger("notify")

_in_app = InAppChannel()


async def _push_ws(user_ids: list[str], *, notification_type: str, title: str, body: str,
                   data: dict | None, link: str | None) -> None:
    try:
        await manager.send_to_users(
            user_ids,
            "notification",
            {"type": notification_type, "title": title, "body": body, "data": data or {}, "link": link},
        )
    except Exception:
        logger.warning("ws_notification_push_failed type=%s", notification_type)


async def notify_users(
    user_ids: list[str],
    *,
    notification_type: str,
    title: str,
    body: str,
    data: dict | None = None,
    link: str | None = None,
    push_ws: bool = True,
    deliver_email: bool = False,
    deliver_sms: bool = True,
    db: Session | None = None,
) -> None:
    if not user_ids:
        return
    type = notification_type
    for user_id in user_ids:
        outgoing = OutgoingNotification(
            user_id=user_id, type=type, title=title, body=body, data=data, link=link
        )
        try:
            _in_app.send(outgoing, db=db)
        except Exception:
            logger.exception("in_app_notification_failed user=%s type=%s", user_id, type)
            continue

    if push_ws:
        await _push_ws(
            user_ids,
            notification_type=type,
            title=title,
            body=body,
            data=data,
            link=link,
        )

    if not (deliver_email or deliver_sms):
        return
    email = get_email_channel()
    sms = get_sms_channel()
    for user_id in user_ids:
        outgoing = OutgoingNotification(user_id=user_id, type=type, title=title, body=body, data=data)
        if deliver_email:
            try:
                email.send(outgoing)
            except Exception:
                logger.warning("email_notification_failed user=%s", user_id)
        if deliver_sms:
            try:
                sms.send(outgoing)
            except Exception:
                logger.warning("sms_notification_failed user=%s", user_id)


def notify_users_sync(user_ids: list[str], **kwargs) -> None:
    """Bridge for synchronous contexts (services, seed scripts).

    Persistence + email/SMS run in the calling thread; the WebSocket push is
    scheduled onto the app's main loop so it reaches live sockets (a fresh
    asyncio.run loop cannot send to sockets owned by the server loop)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        push_ws = bool(kwargs.pop("push_ws", True))
        asyncio.run(notify_users(user_ids, push_ws=False, **kwargs))
        if push_ws and user_ids:
            fire_and_forget(
                _push_ws(
                    user_ids,
                    notification_type=kwargs.get("notification_type", "SYSTEM"),
                    title=kwargs.get("title", ""),
                    body=kwargs.get("body", ""),
                    data=kwargs.get("data"),
                    link=kwargs.get("link"),
                )
            )
        return
    asyncio.create_task(notify_users(user_ids, **kwargs))
