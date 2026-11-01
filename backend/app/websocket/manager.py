"""In-memory WebSocket connection registry.

Tracks authenticated user connections and pushes real-time events:
task status changes, notifications, chat messages, and worker availability.
For multi-instance deployments swap this for a Redis pub/sub-backed manager.
"""

import asyncio
from collections import defaultdict

from fastapi import WebSocket

from app.core.logging import get_logger

logger = get_logger("ws")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[user_id].add(websocket)
        logger.info("ws_connected user=%s total_users=%d", user_id, len(self._connections))

    async def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        async with self._lock:
            self._connections[user_id].discard(websocket)
            if not self._connections[user_id]:
                del self._connections[user_id]

    def is_online(self, user_id: str) -> bool:
        return bool(self._connections.get(user_id))

    def online_user_ids(self) -> list[str]:
        return list(self._connections.keys())

    async def send_to_user(self, user_id: str, event: str, data: dict) -> bool:
        payload = {"event": event, "data": data}
        sockets = list(self._connections.get(user_id, ()))
        delivered = False
        for socket in sockets:
            try:
                await socket.send_json(payload)
                delivered = True
            except Exception:
                await self.disconnect(socket, user_id)
        if delivered:
            logger.info("ws_event user=%s event=%s", user_id, event)
        return delivered

    async def send_to_users(self, user_ids: list[str], event: str, data: dict) -> int:
        delivered = 0
        for user_id in user_ids:
            if await self.send_to_user(user_id, event, data):
                delivered += 1
        return delivered

    async def broadcast_admins(self, admin_ids: list[str], event: str, data: dict) -> int:
        return await self.send_to_users(admin_ids, event, data)


# ---------------------------------------------------------------------------
# Main-loop bridge: sync request handlers run in a threadpool, so WebSocket
# pushes from them must be scheduled onto the event loop that owns the
# sockets — never a fresh asyncio.run() loop, where sends would fail.
# ---------------------------------------------------------------------------

_main_loop: asyncio.AbstractEventLoop | None = None


def capture_main_loop() -> None:
    global _main_loop
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    logger.info("ws_main_loop_captured")


def fire_and_forget(coro) -> None:
    """Schedule `coro` on the app's main loop from any thread."""
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is not None:
        running.create_task(coro)
        return
    if _main_loop is not None and not _main_loop.is_closed():
        try:
            asyncio.run_coroutine_threadsafe(coro, _main_loop)
            return
        except RuntimeError:
            pass
    try:
        asyncio.run(coro)
    except Exception:
        logger.warning("fire_and_forget_failed (no loop available)")


manager = ConnectionManager()
