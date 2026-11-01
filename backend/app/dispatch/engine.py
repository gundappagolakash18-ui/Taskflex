"""Sequential ring-down dispatch engine (Uber/Rapido-style).

On confirmation the ranked candidate list goes into a Redis sorted set
(`dispatch:task:{task_id}:candidates`, score = ring order; in-process list
when Redis is absent). The engine offers the task to ONE worker at a time
over the worker's private WS channel (TASK_OFFER with a 30-second
countdown). A rejection or timeout pops the next candidate and counts a
missed offer against the worker. After 3 consecutive misses the engine
escalates to a surge broadcast: every verified worker within 1.5x radius
gets the offer simultaneously and the first accept wins (guarded by a
SETNX lock on `lock:task:{task_id}`)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis_sync import get_redis_sync
from app.core.timeutils import utcnow, utcnow_naive
from app.db.session import SessionLocal
from app.matching.config import get_matching_config
from app.matching.engine import MatchingEngine
from app.models import NotificationType, Task, TaskOffer, TaskStatus, WorkerProfile
from app.notifications.dispatcher import notify_users_sync
from app.websocket.manager import fire_and_forget, manager

logger = get_logger("dispatch.engine")

OFFER_SECONDS = 30
SURGE_AFTER_FAILURES = 3
SURGE_RADIUS_MULTIPLIER = 1.5
LOCK_TTL_SECONDS = 600
REDISPATCH_COOLDOWN_SECONDS = 120
RECOVERY_BATCH_SIZE = 20

_CANDIDATES_KEY = "dispatch:task:{task_id}:candidates"
_LOCK_KEY = "lock:task:{task_id}"


class SequentialDispatchEngine:
    def __init__(self) -> None:
        self._queues: dict[str, list[dict]] = {}       # in-proc fallback candidate queues
        self._timers: dict[str, threading.Timer] = {}  # one countdown per task
        self._locks: set[str] = set()                  # in-proc SETNX fallback

    # ------------------------------------------------------------------
    # Candidate queue (Redis sorted set with in-process fallback)
    # ------------------------------------------------------------------

    def _push_candidates(self, task_id: str, candidates: list[dict]) -> None:
        client = get_redis_sync()
        if client is not None:
            key = _CANDIDATES_KEY.format(task_id=task_id)
            pipe = client.pipeline()
            pipe.delete(key)
            for rank, cand in enumerate(candidates):
                pipe.zadd(key, {json.dumps(cand): rank})
            pipe.expire(key, 86400)
            pipe.execute()
        else:
            self._queues[task_id] = list(candidates)

    def _pop_next(self, task_id: str) -> dict | None:
        client = get_redis_sync()
        if client is not None:
            popped = client.zpopmin(_CANDIDATES_KEY.format(task_id=task_id), 1)
            if not popped:
                return None
            return json.loads(popped[0][0])
        queue = self._queues.get(task_id)
        if not queue:
            return None
        return queue.pop(0)

    def _drop_queue(self, task_id: str) -> None:
        client = get_redis_sync()
        if client is not None:
            try:
                client.delete(_CANDIDATES_KEY.format(task_id=task_id))
            except Exception:
                logger.warning("dispatch_queue_drop_failed task=%s", task_id)
        self._queues.pop(task_id, None)

    # ------------------------------------------------------------------
    # Ring dispatch
    # ------------------------------------------------------------------

    def start(self, db: Session, task: Task) -> int:
        """Queue the ranked candidates and offer to the first one.
        Returns the number of candidates queued."""
        engine = MatchingEngine(config=get_matching_config())
        eligible = engine.find_eligible_workers(db, task)
        ranked = engine.rank_workers(db, task, eligible)

        # On retries, skip workers who already hold a pending offer.
        already_pending = set(
            db.scalars(
                select(TaskOffer.worker_id).where(
                    TaskOffer.task_id == task.id, TaskOffer.status == "PENDING"
                )
            )
        )

        candidates = []
        for m in ranked:
            if m.worker.user_id in already_pending:
                continue
            rate = float(
                m.worker.commission_rate
                if m.worker.commission_rate is not None
                else settings.platform_commission_percent / 100.0
            )
            candidates.append(
                {
                    "worker_id": m.worker.user_id,
                    "distance_km": float(m.scores.get("distance_km", 0.0) or 0.0),
                    "match_score": float(m.final_score),
                    "estimated_earnings": round(float(task.budget or 0) * (1.0 - rate), 2),
                    "preferred": bool(m.scores.get("preferred", False)),
                    "chained": bool(m.scores.get("chained", False)),
                    "chain_task_id": m.scores.get("chain_task_id"),
                }
            )
        self._push_candidates(task.id, candidates)
        if candidates:
            self.offer_next(db, task)
        return len(candidates)

    def recover_open_tasks(self, db: Session, *, limit: int = RECOVERY_BATCH_SIZE) -> int:
        """Re-ring open tasks that have no live countdown.

        Covers the real cases where dispatch would otherwise go silent: the
        customer confirmed while no eligible worker was online, the backend
        restarted and lost its timer threads, or the previous ring ran out of
        candidates. The cooldown stops the watchdog from restarting a ring
        that a live countdown is still handling.
        """
        now = utcnow_naive()
        cutoff = now - timedelta(seconds=REDISPATCH_COOLDOWN_SECONDS)
        last_offer_at = (
            select(func.max(TaskOffer.created_at))
            .where(TaskOffer.task_id == Task.id)
            .correlate(Task)
            .scalar_subquery()
        )
        live_offer = (
            select(TaskOffer.id)
            .where(
                TaskOffer.task_id == Task.id,
                TaskOffer.status == "PENDING",
                or_(TaskOffer.expires_at.is_(None), TaskOffer.expires_at > now),
            )
            .correlate(Task)
            .exists()
        )
        tasks = list(
            db.scalars(
                select(Task)
                .where(
                    Task.status.in_(
                        [TaskStatus.SEARCHING_WORKER.value, TaskStatus.OFFERED.value]
                    ),
                    Task.assigned_worker_id.is_(None),
                    ~live_offer,
                    or_(last_offer_at.is_(None), last_offer_at <= cutoff),
                )
                .order_by(Task.created_at.asc())
                .limit(limit)
            )
        )
        dispatched = 0
        for task in tasks:
            try:
                if self.start(db, task) > 0:
                    dispatched += 1
            except Exception:
                logger.exception("dispatch_recovery_failed task=%s", task.id)
        if dispatched:
            logger.info("dispatch_recovered tasks=%d", dispatched)
        return dispatched

    def offer_next(self, db: Session, task: Task) -> TaskOffer | None:
        """Offer the task to the next queued candidate (30s countdown)."""
        cand = self._pop_next(task.id)
        if cand is None:
            return None
        worker_id = cand["worker_id"]

        offer = TaskOffer(
            task_id=task.id,
            worker_id=worker_id,
            status="PENDING",
            match_score=round(cand.get("match_score", 0.0), 4),
            expires_at=utcnow() + timedelta(seconds=OFFER_SECONDS),
        )
        preferred = bool(cand.get("preferred", False))
        chained = bool(cand.get("chained", False))
        offer.match_breakdown = json.dumps(
            {
                "distance_km": cand.get("distance_km"),
                "estimated_earnings": cand.get("estimated_earnings"),
                "preferred": preferred,
                "chained": chained,
                "chain_task_id": cand.get("chain_task_id"),
            }
        )
        db.add(offer)
        db.flush()

        badge = (
            "⭐ Repeat Customer Request!" if preferred
            else ("Wrapping up a nearby job" if chained else None)
        )
        payload = {
            "event": "TASK_OFFER",
            "task_id": task.id,
            "offer_id": offer.id,
            "title": task.title,
            "task_type": task.task_type,
            "budget": float(task.budget or 0),
            "expires_in": OFFER_SECONDS,
            "distance_km": cand.get("distance_km"),
            "estimated_earnings": cand.get("estimated_earnings"),
            "preferred": preferred,
            "chained": chained,
            "chain_task_id": cand.get("chain_task_id"),
            "badge": badge,
        }
        fire_and_forget(manager.send_to_user(worker_id, "TASK_OFFER", payload))
        notify_users_sync(
            [worker_id],
            notification_type=NotificationType.TASK_OFFER,
            title=f"New task offer: {task.title}",
            body=f"You have {OFFER_SECONDS} seconds to accept before it goes to the next worker.",
            data={
                "task_id": task.id,
                "offer_id": offer.id,
                "expires_in": OFFER_SECONDS,
                "distance_km": cand.get("distance_km"),
                "estimated_earnings": cand.get("estimated_earnings"),
                "preferred": preferred,
                "chained": chained,
                "badge": badge,
            },
            link="/worker/offers",
            db=db,
        )
        self._start_countdown(task.id, offer.id)
        logger.info(
            "dispatch_offer task=%s worker=%s expires_in=%ss",
            task.id, worker_id, OFFER_SECONDS,
        )
        return offer

    # ------------------------------------------------------------------
    # Countdown
    # ------------------------------------------------------------------

    def _start_countdown(self, task_id: str, offer_id: str) -> None:
        self._cancel_countdown(task_id)
        timer = threading.Timer(OFFER_SECONDS, self._on_timeout, args=(task_id, offer_id))
        timer.daemon = True
        timer.start()
        self._timers[task_id] = timer

    def _cancel_countdown(self, task_id: str) -> None:
        timer = self._timers.pop(task_id, None)
        if timer is not None:
            timer.cancel()

    def _on_timeout(self, task_id: str, offer_id: str) -> None:
        """Timer thread entry — own DB session, all failures swallowed."""
        try:
            self._handle_timeout(task_id, offer_id)
        except Exception:
            logger.exception("dispatch_timeout_failed task=%s", task_id)

    def _handle_timeout(self, task_id: str, offer_id: str) -> None:
        db = SessionLocal()
        try:
            offer = db.get(TaskOffer, offer_id)
            if offer is None or offer.status != "PENDING":
                return  # accepted/declined meanwhile, or state was wiped
            task = db.get(Task, task_id)
            if task is None or task.assigned_worker_id is not None:
                return
            if task.status not in ("SEARCHING_WORKER", "OFFERED"):
                return

            offer.status = "TIMEOUT"
            offer.responded_at = utcnow()
            self.note_miss(db, offer)
            db.commit()

            self._advance_after_failure(db, task)
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Failure accounting / escalation
    # ------------------------------------------------------------------

    def note_miss(self, db: Session, offer: TaskOffer) -> None:
        """worker_metrics.missed_offers += 1 for the worker who let it lapse."""
        profile = db.scalar(
            select(WorkerProfile).where(WorkerProfile.user_id == offer.worker_id)
        )
        if profile is not None:
            profile.missed_offers = (profile.missed_offers or 0) + 1
            db.flush()
        notify_users_sync(
            [offer.worker_id],
            notification_type=NotificationType.OFFER_TIMEOUT,
            title="Offer expired",
            body="You did not respond in time — the offer moved to another worker.",
            data={"task_id": offer.task_id},
            link="/worker/offers",
            db=db,
        )

    def failure_count(self, db: Session, task_id: str) -> int:
        return int(
            db.scalar(
                select(func.count())
                .select_from(TaskOffer)
                .where(
                    TaskOffer.task_id == task_id,
                    TaskOffer.status.in_(["TIMEOUT", "DECLINED"]),
                )
            )
            or 0
        )

    def on_declined(self, db: Session, task: Task, offer: TaskOffer) -> None:
        """A worker actively rejected: count the miss and escalate/ring on."""
        self.note_miss(db, offer)
        self._advance_after_failure(db, task)

    def _advance_after_failure(self, db: Session, task: Task) -> None:
        if task.assigned_worker_id is not None or task.status not in ("SEARCHING_WORKER", "OFFERED"):
            return
        # Someone is still considering the task (surge window): first accept wins.
        pending = db.scalar(
            select(TaskOffer.id)
            .where(TaskOffer.task_id == task.id, TaskOffer.status == "PENDING")
            .limit(1)
        )
        if pending is not None:
            return
        if self.failure_count(db, task.id) >= SURGE_AFTER_FAILURES:
            self.surge(db, task)
            return
        self.offer_next(db, task)
        db.commit()

    # ------------------------------------------------------------------
    # Surge broadcast
    # ------------------------------------------------------------------

    def surge(self, db: Session, task: Task) -> int:
        """Last resort: offer to EVERY verified worker within 1.5x radius at
        once — first accept wins."""
        engine = MatchingEngine(config=get_matching_config())
        eligible = engine.find_eligible_workers(
            db, task, radius_multiplier=SURGE_RADIUS_MULTIPLIER
        )
        ranked = engine.rank_workers(db, task, eligible)

        expires_at = utcnow() + timedelta(minutes=settings.offer_ttl_minutes)
        payloads = []
        for m in ranked:
            worker_id = m.worker.user_id
            already = db.scalar(
                select(TaskOffer.id).where(
                    TaskOffer.task_id == task.id,
                    TaskOffer.worker_id == worker_id,
                    TaskOffer.status == "PENDING",
                )
            )
            if already:
                continue
            rate = float(
                m.worker.commission_rate
                if m.worker.commission_rate is not None
                else settings.platform_commission_percent / 100.0
            )
            offer = TaskOffer(
                task_id=task.id,
                worker_id=worker_id,
                status="PENDING",
                match_score=round(m.final_score, 4),
                expires_at=expires_at,
                match_breakdown=json.dumps(
                    {
                        "distance_km": float(m.scores.get("distance_km", 0.0) or 0.0),
                        "estimated_earnings": round(float(task.budget or 0) * (1.0 - rate), 2),
                        "preferred": bool(m.scores.get("preferred", False)),
                        "chained": bool(m.scores.get("chained", False)),
                        "chain_task_id": m.scores.get("chain_task_id"),
                    }
                ),
            )
            db.add(offer)
            db.flush()
            payloads.append(
                {
                    "worker_id": worker_id,
                    "offer_id": offer.id,
                    "distance_km": float(m.scores.get("distance_km", 0.0) or 0.0),
                    "estimated_earnings": round(float(task.budget or 0) * (1.0 - rate), 2),
                    "preferred": bool(m.scores.get("preferred", False)),
                    "chained": bool(m.scores.get("chained", False)),
                    "chain_task_id": m.scores.get("chain_task_id"),
                }
            )

        for p in payloads:
            fire_and_forget(
                manager.send_to_user(
                    p["worker_id"],
                    "TASK_OFFER",
                    {
                        "event": "TASK_OFFER",
                        "task_id": task.id,
                        "offer_id": p["offer_id"],
                        "title": task.title,
                        "task_type": task.task_type,
                        "budget": float(task.budget or 0),
                        "expires_in": settings.offer_ttl_minutes * 60,
                        "distance_km": p["distance_km"],
                        "estimated_earnings": p["estimated_earnings"],
                        "preferred": p["preferred"],
                        "chained": p["chained"],
                        "chain_task_id": p["chain_task_id"],
                        "badge": (
                            "⭐ Repeat Customer Request!" if p["preferred"]
                            else ("Wrapping up a nearby job" if p["chained"] else None)
                        ),
                        "surge": True,
                    },
                )
            )

        notify_users_sync(
            [task.customer_id],
            notification_type=NotificationType.SYSTEM,
            title=f"Widening the search: {task.title}",
            body=(
                "Nearby workers haven't responded yet — we're now offering your task "
                "to every verified worker in the wider area. First to accept gets it."
            ),
            data={"task_id": task.id},
            link=f"/customer/tasks/{task.id}",
            db=db,
        )
        db.commit()
        logger.info("dispatch_surge task=%s workers=%d", task.id, len(payloads))
        return len(payloads)

    # ------------------------------------------------------------------
    # Accept lock + cleanup
    # ------------------------------------------------------------------

    def try_acquire_lock(self, task_id: str, worker_id: str) -> bool:
        """SETNX lock:task:{task_id} — only one worker can accept."""
        client = get_redis_sync()
        if client is not None:
            try:
                got = client.set(_LOCK_KEY.format(task_id=task_id), worker_id, nx=True, ex=LOCK_TTL_SECONDS)
                return bool(got)
            except Exception:
                logger.warning("dispatch_lock_redis_failed task=%s", task_id)
                return True  # never let a Redis hiccup block an acceptance
        if task_id in self._locks:
            return False
        self._locks.add(task_id)
        return True

    def release_lock(self, task_id: str) -> None:
        client = get_redis_sync()
        if client is not None:
            try:
                client.delete(_LOCK_KEY.format(task_id=task_id))
            except Exception:
                pass
        self._locks.discard(task_id)

    def finalize_accept(self, task_id: str) -> None:
        """Winner found: kill the countdown and clear the candidate queue."""
        self._cancel_countdown(task_id)
        self._drop_queue(task_id)

    def clear(self, task_id: str) -> None:
        """Task closed (cancelled/completed): stop dispatching entirely."""
        self._cancel_countdown(task_id)
        self._drop_queue(task_id)
        self.release_lock(task_id)


dispatch_engine = SequentialDispatchEngine()
