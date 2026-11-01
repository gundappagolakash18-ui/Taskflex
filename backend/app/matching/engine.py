"""Multi-factor worker matching engine.

Every component score is normalised to [0, 1]; the final score is the weighted
sum using MatchingWeights. Business rules that decide *eligibility* (radius,
online status, capacity) live here so controllers stay thin.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.matching.config import MatchingConfig, get_matching_config
from app.matching.geo import haversine_km
from app.models import (
    AffinityType,
    CustomerWorkerAffinity,
    Task,
    TaskAssignment,
    TaskStatus,
    User,
    WorkerProfile,
    WorkerSkill,
    WorkerTier,
)

PREFERRED_BOOST = 0.35
CHAINING_DISTANCE_DISCOUNT = 0.92
CHAIN_ELAPSED_RATIO = 0.80
TIER_BOOSTS = {
    WorkerTier.SILVER.value: 0.0,
    WorkerTier.GOLD.value: 0.05,
    WorkerTier.PLATINUM.value: 0.10,
}


@dataclass
class MatchResult:
    worker: WorkerProfile
    scores: dict = field(default_factory=dict)

    @property
    def final_score(self) -> float:
        return self.scores.get("final_score", 0.0)


class MatchingEngine:
    def __init__(self, config: MatchingConfig | None = None):
        self.config = config or get_matching_config()

    # ---------- eligibility ----------

    def find_eligible_workers(
        self, db: Session, task: Task, *, radius_multiplier: float = 1.0
    ) -> list[WorkerProfile]:
        """Workers who may receive an offer: active account, verified, online,
        inside their declared working radius (optionally widened by
        `radius_multiplier`, used by surge dispatch), below capacity, and not
        blacklisted by this customer. Workers wrapping up a current job are
        eligible for one back-to-back queued task."""
        stmt = (
            select(WorkerProfile)
            .join(User, User.id == WorkerProfile.user_id)
            .where(
                User.is_active.is_(True),
                WorkerProfile.is_online.is_(True),
                WorkerProfile.is_verified.is_(True),
                WorkerProfile.user_id != task.customer_id,
            )
            .options(
                selectinload(WorkerProfile.user),
                selectinload(WorkerProfile.skills).selectinload(WorkerSkill.skill),
                selectinload(WorkerProfile.availability),
            )
        )
        candidates = list(db.execute(stmt).scalars().unique().all())
        affinities = self.affinity_map(db, task.customer_id)
        eligible = []
        for worker in candidates:
            if affinities.get(worker.user_id) == AffinityType.BLACKLISTED.value:
                continue
            if worker.queued_task_id is not None:
                continue
            chain_task, chain_origin = self.chaining_state(db, worker)
            if chain_origin is not None:
                if not self._within_radius_from(task, chain_origin, worker, radius_multiplier):
                    continue
                if not self._has_capacity(db, worker, allow_full=chain_task is not None):
                    continue
            else:
                if not self._within_radius(task, worker, radius_multiplier):
                    continue
                if not self._has_capacity(db, worker):
                    continue
            eligible.append(worker)
        return eligible

    def affinity_map(self, db: Session, customer_id: str) -> dict[str, str]:
        rows = db.execute(
            select(CustomerWorkerAffinity.worker_id, CustomerWorkerAffinity.affinity_type).where(
                CustomerWorkerAffinity.customer_id == customer_id
            )
        ).all()
        return {worker_id: affinity for worker_id, affinity in rows}

    def chaining_state(
        self, db: Session, worker: WorkerProfile
    ) -> tuple[Task | None, tuple[float, float] | None]:
        """Return the worker's in-progress task and its final waypoint when the
        worker is close enough to finishing to be queued another job."""
        if worker.queued_task_id is not None:
            return None, None
        row = db.execute(
            select(TaskAssignment, Task)
            .join(Task, Task.id == TaskAssignment.task_id)
            .where(
                TaskAssignment.worker_id == worker.user_id,
                TaskAssignment.status == "ACTIVE",
                Task.status == TaskStatus.IN_PROGRESS.value,
            )
            .options(selectinload(Task.locations))
            .order_by(TaskAssignment.accepted_at.desc())
            .limit(1)
        ).first()
        if row is None:
            return None, None
        assignment, active = row

        elapsed_ok = False
        if assignment.started_at is not None:
            started = assignment.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            elapsed_min = (datetime.now(timezone.utc) - started).total_seconds() / 60.0
            elapsed_ok = elapsed_min >= CHAIN_ELAPSED_RATIO * max(active.estimated_duration_minutes or 0, 1)
        if not (elapsed_ok or worker.wrapping_up_soon):
            return None, None

        final = None
        if active.locations:
            final = max(active.locations, key=lambda loc: loc.sequence)
        if final is not None:
            origin = (float(final.latitude), float(final.longitude))
        elif active.latitude is not None and active.longitude is not None:
            origin = (float(active.latitude), float(active.longitude))
        else:
            origin = None
        return active, origin

    def _within_radius(self, task: Task, worker: WorkerProfile, radius_multiplier: float = 1.0) -> bool:
        if task.latitude is None or task.longitude is None:
            return True
        if worker.latitude is None or worker.longitude is None:
            return True
        return self._within_radius_from(
            task, (float(worker.latitude), float(worker.longitude)), worker, radius_multiplier
        )

    def _within_radius_from(
        self,
        task: Task,
        origin: tuple[float, float] | None,
        worker: WorkerProfile,
        radius_multiplier: float = 1.0,
    ) -> bool:
        if task.latitude is None or task.longitude is None:
            return True
        if origin is None:
            return True
        distance = haversine_km(task.latitude, task.longitude, origin[0], origin[1])
        radius = max(worker.working_radius_km * radius_multiplier, 0.1)
        return distance <= radius

    def _has_capacity(self, db: Session, worker: WorkerProfile, *, allow_full: bool = False) -> bool:
        from app.models import Task, TaskAssignment
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(TaskAssignment)
            .join(Task, Task.id == TaskAssignment.task_id)
            .where(
                TaskAssignment.worker_id == worker.user_id,
                TaskAssignment.status == "ACTIVE",
                Task.status.notin_(
                    [
                        "COMPLETED",
                        "CANCELLED",
                        "DISPUTED",
                        TaskStatus.QUEUED_NEXT.value,
                        TaskStatus.SCHEDULED_ASSIGNED.value,
                    ]
                ),
            )
        )
        active = db.execute(stmt).scalar_one()
        if allow_full:
            return True
        return active < worker.max_concurrent_tasks

    # ---------- component scores ----------

    def calculate_distance_score(
        self,
        task: Task,
        worker: WorkerProfile,
        *,
        origin: tuple[float, float] | None = None,
        chained: bool = False,
    ) -> tuple[float, float]:
        lat, lng = origin if origin is not None else (worker.latitude, worker.longitude)
        if task.latitude is None or task.longitude is None or lat is None or lng is None:
            return self.config.unknown_location_score, 0.0
        distance = haversine_km(task.latitude, task.longitude, float(lat), float(lng))
        radius = max(worker.working_radius_km, 0.1)
        if chained:
            # Measure from where the worker will finish their current job, with
            # an 8% distance credit for the seamless back-to-back handover.
            distance = distance * CHAINING_DISTANCE_DISCOUNT
        score = max(0.0, min(1.0, 1.0 - (distance / radius)))
        return score, round(distance, 2)

    def calculate_skill_score(self, task: Task, worker: WorkerProfile) -> float:
        required = {r.skill_name.lower() for r in task.requirements}
        if not required:
            return self.config.no_skill_requirement_score
        worker_skills = {ws.skill.slug.lower() for ws in worker.skills} | {
            ws.skill.name.lower() for ws in worker.skills
        }
        if not worker_skills:
            return 0.0
        overlap = len(required & worker_skills)
        return min(1.0, overlap / len(required))

    def calculate_availability_score(self, task: Task, worker: WorkerProfile) -> float:
        if not worker.availability:
            return self.config.no_availability_info_score
        target_day = self._target_weekday(task)
        day_entries = [a for a in worker.availability if a.day_of_week == target_day]
        if not day_entries:
            return 0.1  # schedule defined, but not working that day
        entry = day_entries[0]
        if not entry.is_available:
            return 0.0
        if task.scheduled_time is None:
            return 1.0
        start = self._minutes(entry.start_time)
        end = self._minutes(entry.end_time)
        task_start = task.scheduled_time.hour * 60 + task.scheduled_time.minute
        task_end = task_start + max(task.estimated_duration_minutes, 15)
        if task_start >= start and task_end <= end:
            return 1.0
        if task_start >= start and task_start <= end:
            return 0.6  # partially overlapping
        return 0.2

    def calculate_rating_score(self, worker: WorkerProfile) -> float:
        count = worker.rating_count
        avg = worker.rating_average
        blended = (
            (avg * count + self.config.rating_prior_mean * self.config.rating_prior_weight)
            / (count + self.config.rating_prior_weight)
            if count >= 0
            else self.config.rating_prior_mean
        )
        return max(0.0, min(1.0, blended / 5.0))

    def calculate_reliability_score(self, worker: WorkerProfile) -> float:
        completed = worker.completed_tasks_count
        cancelled = worker.cancelled_tasks_count
        rate = completed / (completed + cancelled) if (completed + cancelled) > 0 else 0.0
        blended = (
            (rate * (completed + cancelled) + self.config.reliability_prior_rate * self.config.reliability_prior_weight)
            / (completed + cancelled + self.config.reliability_prior_weight)
        )
        return max(0.0, min(1.0, blended))

    def calculate_workload_score(self, db: Session, worker: WorkerProfile) -> float:
        from app.models import Task, TaskAssignment
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(TaskAssignment)
            .join(Task, Task.id == TaskAssignment.task_id)
            .where(
                TaskAssignment.worker_id == worker.user_id,
                TaskAssignment.status == "ACTIVE",
                Task.status.notin_(["COMPLETED", "CANCELLED", "DISPUTED"]),
            )
        )
        active = db.execute(stmt).scalar_one()
        capacity = max(worker.max_concurrent_tasks, 1)
        return max(0.0, min(1.0, 1.0 - (active / capacity)))

    # ---------- final ----------

    def calculate_final_score(self, components: dict[str, float]) -> float:
        weights = self.config.weights.as_dict()
        total = sum(weights[name] * components[name] for name in weights)
        return round(total, 4)

    def rank_workers(self, db: Session, task: Task, workers: list[WorkerProfile]) -> list[MatchResult]:
        affinities = self.affinity_map(db, task.customer_id)
        results: list[MatchResult] = []
        for worker in workers:
            affinity = affinities.get(worker.user_id)
            if affinity == AffinityType.BLACKLISTED.value:
                continue
            preferred = affinity == AffinityType.PREFERRED.value
            chain_task, chain_origin = self.chaining_state(db, worker)
            chained = chain_task is not None
            distance_score, distance_km = self.calculate_distance_score(
                task, worker, origin=chain_origin, chained=chained
            )
            components = {
                "distance": round(distance_score, 4),
                "skill_match": round(self.calculate_skill_score(task, worker), 4),
                "availability": round(self.calculate_availability_score(task, worker), 4),
                "rating": round(self.calculate_rating_score(worker), 4),
                "reliability": round(self.calculate_reliability_score(worker), 4),
                "workload": round(self.calculate_workload_score(db, worker), 4),
            }
            tier_boost = TIER_BOOSTS.get(worker.tier or WorkerTier.SILVER.value, 0.0)
            preferred_boost = PREFERRED_BOOST if preferred else 0.0
            base_score = self.calculate_final_score(components)
            components["base_score"] = base_score
            components["tier_boost"] = round(tier_boost, 4)
            components["preferred_boost"] = round(preferred_boost, 4)
            components["final_score"] = round(min(1.0, base_score + tier_boost + preferred_boost), 4)
            result = MatchResult(worker=worker, scores=dict(components))
            result.scores["distance_km"] = distance_km
            result.scores["preferred"] = preferred
            result.scores["chained"] = chained
            result.scores["chain_task_id"] = chain_task.id if chain_task is not None else None
            results.append(result)
        results.sort(key=lambda r: (r.scores.get("preferred", False), r.final_score), reverse=True)
        return results

    def _target_weekday(self, task: Task) -> int:
        target: date | None = task.scheduled_date
        if target is None:
            target = date.today()
        return target.weekday()

    @staticmethod
    def _minutes(t: time) -> int:
        return t.hour * 60 + t.minute
