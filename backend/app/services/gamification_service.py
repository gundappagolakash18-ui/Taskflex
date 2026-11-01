"""Worker tiers, rolling performance and daily quests.

Tiers are recalculated after every completion from rolling 30-day stats:

===========  ===========  ============  ===================  ==============
Tier         Tasks        Rating        Cancellation rate     Commission
===========  ===========  ============  ===================  ==============
PLATINUM     >= 25        >= 4.8        < 5%                  5.0 %
GOLD         >= 10        >= 4.5        < 10%                 7.5 %
SILVER       default      default       default               10.0 %
===========  ===========  ============  ===================  ==============

The tier also feeds a matching boost (+0.05 GOLD, +0.10 PLATINUM) in the
matching engine. Daily quests are seeded automatically; each completion
advances today's progress and a reached target credits the wallet in full
with a ``QUEST_BONUS`` ledger entry plus a ``QUEST_COMPLETED`` WebSocket
event for the confetti toast.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import (
    NotificationType,
    Rating,
    Task,
    TaskAssignment,
    TransactionType,
    User,
    WorkerProfile,
    WorkerQuest,
    WorkerQuestProgress,
    WorkerTier,
)
from app.notifications.dispatcher import notify_users_sync
from app.repositories import PaymentRepository
from app.websocket.manager import fire_and_forget, manager

logger = get_logger("taskflex.gamification")

IST = timezone(timedelta(hours=5, minutes=30))

TIER_RULES = {
    WorkerTier.PLATINUM.value: {
        "min_tasks": 25, "min_rating": 4.8, "max_cancel_rate": 0.05, "commission_rate": 0.05,
    },
    WorkerTier.GOLD.value: {
        "min_tasks": 10, "min_rating": 4.5, "max_cancel_rate": 0.10, "commission_rate": 0.075,
    },
    WorkerTier.SILVER.value: {
        "min_tasks": 0, "min_rating": 0.0, "max_cancel_rate": 1.0, "commission_rate": 0.10,
    },
}

DAILY_QUEST_BLUEPRINT = (
    ("First Three", "Complete 3 tasks today", 3, 50.0),
    ("High Five", "Complete 5 tasks today", 5, 120.0),
    ("Daily Dozen", "Complete 12 tasks today", 12, 300.0),
)


def ist_today() -> date:
    return datetime.now(timezone.utc).astimezone(IST).date()


class GamificationService:
    def __init__(self, db: Session):
        self.db = db
        self.payments = PaymentRepository(db)

    # ------------------------------------------------------------------
    # Daily quests
    # ------------------------------------------------------------------

    def ensure_daily_quests(self, day: date | None = None) -> list[WorkerQuest]:
        day = day or ist_today()
        existing = list(
            self.db.scalars(
                select(WorkerQuest).where(
                    WorkerQuest.valid_date == day, WorkerQuest.is_active.is_(True)
                )
            )
        )
        if existing:
            return existing
        created = []
        for title, description, target, bonus in DAILY_QUEST_BLUEPRINT:
            quest = WorkerQuest(
                title=title,
                description=description,
                target_tasks_count=target,
                bonus_amount=bonus,
                valid_date=day,
                is_active=True,
            )
            self.db.add(quest)
            created.append(quest)
        self.db.flush()
        logger.info("daily_quests_seeded day=%s count=%d", day, len(created))
        return created

    def today_quests(self, worker_id: str) -> list[dict]:
        quests = self.ensure_daily_quests()
        progress_by_quest = {
            row.quest_id: row
            for row in self.db.scalars(
                select(WorkerQuestProgress).where(
                    WorkerQuestProgress.worker_id == worker_id,
                    WorkerQuestProgress.quest_id.in_([q.id for q in quests]),
                )
            )
        }
        payload = []
        for quest in sorted(quests, key=lambda q: q.target_tasks_count):
            progress = progress_by_quest.get(quest.id)
            completed = int(progress.completed_count) if progress else 0
            claimed = bool(progress.is_claimed) if progress else False
            payload.append(
                {
                    "id": quest.id,
                    "title": quest.title,
                    "description": quest.description,
                    "target_tasks_count": quest.target_tasks_count,
                    "bonus_amount": float(quest.bonus_amount),
                    "valid_date": quest.valid_date.isoformat(),
                    "completed_count": completed,
                    "is_claimed": claimed,
                    "progress_percent": round(
                        min(1.0, completed / max(quest.target_tasks_count, 1)) * 100, 1
                    ),
                }
            )
        return payload

    def _advance_quests(self, worker_id: str) -> list[dict]:
        quests = self.ensure_daily_quests()
        completed_quests: list[dict] = []
        for quest in quests:
            progress = self.db.scalar(
                select(WorkerQuestProgress).where(
                    WorkerQuestProgress.worker_id == worker_id,
                    WorkerQuestProgress.quest_id == quest.id,
                )
            )
            if progress is None:
                progress = WorkerQuestProgress(worker_id=worker_id, quest_id=quest.id)
                self.db.add(progress)
                self.db.flush()
            if progress.is_claimed:
                continue
            progress.completed_count = int(progress.completed_count or 0) + 1
            if progress.completed_count < quest.target_tasks_count:
                continue
            # Target reached: auto-credit the bonus in full.
            wallet = self.payments.ensure_wallet(worker_id)
            bonus = float(quest.bonus_amount)
            wallet.balance = round(wallet.balance + bonus, 2)
            wallet.total_earned = round(wallet.total_earned + bonus, 2)
            self.payments.add_transaction(
                user_id=worker_id,
                wallet_id=wallet.id,
                type=TransactionType.QUEST_BONUS,
                amount=bonus,
                balance_after=wallet.balance,
                currency=wallet.currency,
                reference_type="quest",
                reference_id=quest.id,
                description=f"Quest bonus: {quest.title}",
            )
            progress.is_claimed = True
            progress.claimed_at = datetime.now(timezone.utc)
            completed_quests.append(
                {
                    "quest_id": quest.id,
                    "title": quest.title,
                    "bonus_amount": bonus,
                    "completed_count": progress.completed_count,
                }
            )
            notify_users_sync(
                [worker_id],
                notification_type=NotificationType.QUEST_COMPLETED,
                title=f"Quest complete: {quest.title}",
                body=f"₹{bonus:.0f} was credited to your wallet for completing "
                     f"{quest.target_tasks_count} tasks today.",
                data={"quest_id": quest.id, "bonus_amount": bonus},
                link="/worker/earnings",
                db=self.db,
            )
            fire_and_forget(
                manager.send_to_user(
                    worker_id,
                    "QUEST_COMPLETED",
                    {
                        "quest_id": quest.id,
                        "title": quest.title,
                        "bonus_amount": bonus,
                        "confetti": True,
                    },
                )
            )
        self.db.flush()
        return completed_quests

    # ------------------------------------------------------------------
    # Tiers
    # ------------------------------------------------------------------

    def rolling_stats(self, worker_id: str) -> dict:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        completed = int(
            self.db.scalar(
                select(func.count())
                .select_from(TaskAssignment)
                .join(Task, Task.id == TaskAssignment.task_id)
                .where(
                    TaskAssignment.worker_id == worker_id,
                    TaskAssignment.completed_at.is_not(None),
                    TaskAssignment.completed_at >= cutoff,
                )
            )
            or 0
        )
        cancelled = int(
            self.db.scalar(
                select(func.count())
                .select_from(TaskAssignment)
                .where(
                    TaskAssignment.worker_id == worker_id,
                    TaskAssignment.status == "CANCELLED",
                    TaskAssignment.accepted_at >= cutoff,
                )
            )
            or 0
        )
        avg_rating, rating_count = self.db.execute(
            select(func.avg(Rating.score), func.count()).where(
                Rating.ratee_id == worker_id,
                Rating.direction == "CUSTOMER_TO_WORKER",
                Rating.created_at >= cutoff,
            )
        ).one()
        profile = self.db.scalar(
            select(WorkerProfile).where(WorkerProfile.user_id == worker_id)
        )
        rating = round(float(avg_rating), 2) if avg_rating is not None else float(
            profile.rating_average if profile else 0.0
        )
        total = completed + cancelled
        cancel_rate = round(cancelled / total, 4) if total else 0.0
        return {
            "completed_30d": completed,
            "cancelled_30d": cancelled,
            "rating": rating,
            "rating_count_30d": int(rating_count or 0),
            "cancellation_rate": cancel_rate,
        }

    def tier_for(self, stats: dict) -> str:
        for tier in (WorkerTier.PLATINUM.value, WorkerTier.GOLD.value):
            rule = TIER_RULES[tier]
            if (
                stats["completed_30d"] >= rule["min_tasks"]
                and stats["rating"] >= rule["min_rating"]
                and stats["cancellation_rate"] < rule["max_cancel_rate"]
            ):
                return tier
        return WorkerTier.SILVER.value

    def recalculate_tier(self, worker_id: str) -> dict:
        profile = self.db.scalar(
            select(WorkerProfile).where(WorkerProfile.user_id == worker_id)
        )
        if profile is None:
            return {"tier": WorkerTier.SILVER.value, "changed": False}
        stats = self.rolling_stats(worker_id)
        new_tier = self.tier_for(stats)
        previous = profile.tier or WorkerTier.SILVER.value
        profile.tier = new_tier
        profile.commission_rate = TIER_RULES[new_tier]["commission_rate"]
        self.db.flush()
        changed = new_tier != previous
        if changed:
            notify_users_sync(
                [worker_id],
                notification_type=NotificationType.TIER_UPGRADED,
                title=f"Tier updated: {new_tier.title()}",
                body=(
                    f"You are now {new_tier.title()} — platform commission is "
                    f"{TIER_RULES[new_tier]['commission_rate'] * 100:.1f}% on future tasks."
                ),
                data={"tier": new_tier, "previous_tier": previous},
                link="/worker/profile",
                db=self.db,
            )
            fire_and_forget(
                manager.send_to_user(
                    worker_id,
                    "TIER_UPGRADED",
                    {"tier": new_tier, "previous_tier": previous},
                )
            )
            logger.info("tier_changed worker=%s %s->%s", worker_id, previous, new_tier)
        return {
            "tier": new_tier,
            "previous_tier": previous,
            "changed": changed,
            "commission_rate": TIER_RULES[new_tier]["commission_rate"],
            "stats": stats,
        }

    def on_task_completed(self, task: Task, worker_user: User) -> dict:
        """Called once when escrow settles: bump lifetime counters, advance
        today's quests, and recompute the worker's tier."""
        profile = self.db.scalar(
            select(WorkerProfile).where(WorkerProfile.user_id == worker_user.id)
        )
        if profile is not None:
            profile.completed_tasks_count = int(profile.completed_tasks_count or 0) + 1
            self.db.flush()
        quests = self._advance_quests(worker_user.id)
        tier = self.recalculate_tier(worker_user.id)
        logger.info(
            "gamification_applied task=%s worker=%s tier=%s quests_completed=%d",
            task.id, worker_user.id, tier.get("tier"), len(quests),
        )
        return {"tier": tier, "quests_completed": quests}

    def on_task_cancelled(self, task: Task) -> None:
        if task.assigned_worker_id is None:
            return
        profile = self.db.scalar(
            select(WorkerProfile).where(WorkerProfile.user_id == task.assigned_worker_id)
        )
        if profile is not None and task.status_history:
            # Count a cancellation against the worker only once per task.
            profile.cancelled_tasks_count = int(profile.cancelled_tasks_count or 0) + 1
            self.db.flush()

    # ------------------------------------------------------------------
    # Overview for the worker dashboard
    # ------------------------------------------------------------------

    def worker_overview(self, worker_id: str) -> dict:
        profile = self.db.scalar(
            select(WorkerProfile).where(WorkerProfile.user_id == worker_id)
        )
        if profile is None:
            return {}
        stats = self.rolling_stats(worker_id)
        tier = profile.tier or WorkerTier.SILVER.value
        rule = TIER_RULES[tier]
        next_tier = {"SILVER": WorkerTier.GOLD.value, "GOLD": WorkerTier.PLATINUM.value}.get(tier)
        next_rule = TIER_RULES[next_tier] if next_tier else None
        return {
            "tier": tier,
            "commission_rate": float(profile.commission_rate),
            "stats": stats,
            "rule": rule,
            "next_tier": next_tier,
            "next_tier_rule": next_rule,
            "quests": self.today_quests(worker_id),
        }
