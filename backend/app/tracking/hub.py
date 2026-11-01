"""Live-tracking hub: who is watching which task, and where workers are.

Fan-out is Redis pub/sub when REDIS_URL is configured (multi-instance safe)
and degrades to an in-process registry for single-instance deployments.
Latest telemetry per task is cached (Redis when available) so customers who
open the tracking screen late still get the current position instantly."""

import asyncio
import json
from collections import defaultdict

from app.core.config import settings
from app.core.logging import get_logger
from app.websocket.manager import manager

logger = get_logger("tracking.hub")

CHANNEL_PREFIX = "channel:tracking:task:"
LATEST_KEY_PREFIX = "tracking:latest:task:"
LATEST_TTL_SECONDS = 3600
HISTORY_KEY_PREFIX = "tracking:history:task:"
HISTORY_TTL_SECONDS = 6 * 3600


class TrackingHub:
    def __init__(self) -> None:
        self._subs: dict[str, set[str]] = defaultdict(set)
        self._latest_local: dict[str, dict] = {}
        self._history_local: dict[str, list[dict]] = {}
        self._redis = None
        self._listener: asyncio.Task | None = None

    # ---------- lifecycle ----------

    async def start(self) -> None:
        if not settings.redis_url:
            logger.info("tracking_hub in-process mode (no REDIS_URL)")
            return
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            await self._redis.ping()
            self._listener = asyncio.create_task(self._listen())
            logger.info("tracking_hub redis mode url=%s", settings.redis_url)
        except Exception:
            logger.exception("redis_unavailable; tracking hub falling back to in-process")
            self._redis = None

    async def close(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            self._listener = None
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None

    # ---------- subscriptions ----------

    def subscribe(self, task_id: str, user_id: str) -> None:
        self._subs[task_id].add(user_id)

    def unsubscribe(self, task_id: str, user_id: str) -> None:
        self._subs[task_id].discard(user_id)
        if not self._subs[task_id]:
            self._subs.pop(task_id, None)

    def unsubscribe_user(self, user_id: str) -> None:
        for task_id in list(self._subs):
            self.unsubscribe(task_id, user_id)

    # ---------- publish / latest / history ----------

    async def publish(self, task_id: str, payload: dict) -> None:
        body = json.dumps(payload)
        if self._redis is not None:
            history_key = f"{HISTORY_KEY_PREFIX}{task_id}"
            pipe = self._redis.pipeline()
            pipe.publish(f"{CHANNEL_PREFIX}{task_id}", body)
            pipe.set(f"{LATEST_KEY_PREFIX}{task_id}", body, ex=LATEST_TTL_SECONDS)
            pipe.rpush(history_key, body)
            pipe.ltrim(history_key, -settings.tracking_history_points, -1)
            pipe.expire(history_key, HISTORY_TTL_SECONDS)
            await pipe.execute()
        else:
            self._latest_local[task_id] = payload
            ring = self._history_local.setdefault(task_id, [])
            ring.append(payload)
            del ring[: -settings.tracking_history_points]
            await self._deliver(task_id, payload)

    async def latest(self, task_id: str) -> dict | None:
        if self._redis is not None:
            raw = await self._redis.get(f"{LATEST_KEY_PREFIX}{task_id}")
            return json.loads(raw) if raw else None
        return self._latest_local.get(task_id)

    async def history(self, task_id: str, limit: int | None = None) -> list[dict]:
        """The newest N positions, oldest first (the frozen evidence trail
        used by SOS)."""
        count = limit or settings.tracking_history_points
        if self._redis is not None:
            raw = await self._redis.lrange(f"{HISTORY_KEY_PREFIX}{task_id}", -count, -1)
            return [json.loads(item) for item in raw]
        return list(self._history_local.get(task_id, []))[-count:]

    async def clear_history(self, task_id: str) -> None:
        if self._redis is not None:
            await self._redis.delete(f"{HISTORY_KEY_PREFIX}{task_id}")
        else:
            self._history_local.pop(task_id, None)

    # ---------- internals ----------

    async def _listen(self) -> None:
        assert self._redis is not None
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(f"{CHANNEL_PREFIX}*")
        try:
            async for message in pubsub.listen():
                if message.get("type") != "pmessage":
                    continue
                channel: str = message["channel"]
                task_id = channel[len(CHANNEL_PREFIX):]
                await self._deliver(task_id, json.loads(message["data"]))
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await pubsub.aclose()
            except Exception:
                pass

    async def _deliver(self, task_id: str, payload: dict) -> None:
        user_ids = list(self._subs.get(task_id, ()))
        if user_ids:
            await manager.send_to_users(user_ids, "tracking_update", payload)


hub = TrackingHub()
