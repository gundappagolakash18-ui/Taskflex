"""Admin analytics: DAU/MAU series, task completion, revenue and platform health.

Every aggregate is a small grouped SELECT — appropriate for the scale of the
demo dataset and honest about its limits (swap in a warehouse for real scale).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    Dispute,
    Payment,
    Rating,
    RatingDirection,
    Task,
    TaskStatus,
    User,
    VerificationDocument,
    VerificationStatus,
    WorkerProfile,
)
from app.repositories import TaskRepository
from app.schemas.admin import AnalyticsResponse, DashboardMetrics, TimeSeriesPoint


def _day_start(day: datetime) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


class AnalyticsService:
    def __init__(self, db: Session):
        self.db = db
        self.tasks = TaskRepository(db)

    # ---------- dashboard ----------

    def dashboard_metrics(self) -> DashboardMetrics:
        now = datetime.now(timezone.utc)

        total_users = int(self.db.scalar(select(func.count()).select_from(User)) or 0)
        total_customers = int(
            self.db.scalar(select(func.count()).select_from(User).where(User.role == "CUSTOMER")) or 0
        )
        total_workers = int(
            self.db.scalar(select(func.count()).select_from(User).where(User.role == "WORKER")) or 0
        )
        active_workers = int(
            self.db.scalar(
                select(func.count()).select_from(WorkerProfile).where(WorkerProfile.is_online.is_(True))
            )
            or 0
        )
        verified_workers = int(
            self.db.scalar(
                select(func.count()).select_from(WorkerProfile).where(WorkerProfile.is_verified.is_(True))
            )
            or 0
        )
        pending_verifications = int(
            self.db.scalar(
                select(func.count())
                .select_from(VerificationDocument)
                .where(VerificationDocument.status == VerificationStatus.PENDING)
            )
            or 0
        )

        status_counts = self.tasks.count_by_status()
        total_tasks = sum(status_counts.values())
        completed = status_counts.get(TaskStatus.COMPLETED.value, 0)
        cancelled = status_counts.get(TaskStatus.CANCELLED.value, 0)
        disputed = status_counts.get(TaskStatus.DISPUTED.value, 0)
        active = (
            status_counts.get(TaskStatus.SEARCHING_WORKER.value, 0)
            + status_counts.get(TaskStatus.OFFERED.value, 0)
            + status_counts.get(TaskStatus.ACCEPTED.value, 0)
            + status_counts.get(TaskStatus.WORKER_ON_THE_WAY.value, 0)
            + status_counts.get(TaskStatus.IN_PROGRESS.value, 0)
        )
        settled = completed + cancelled
        completion_rate = (completed / settled) if settled else 0.0
        cancellation_rate = (cancelled / settled) if settled else 0.0

        captured = self.db.execute(
            select(
                func.coalesce(func.sum(Payment.amount), 0.0),
                func.coalesce(func.sum(Payment.commission_amount), 0.0),
                func.coalesce(func.sum(Payment.worker_payout_amount), 0.0),
                func.count(),
            ).where(Payment.status == "CAPTURED")
        ).one()
        gmv, commission, payouts, captured_count = (float(captured[0]), float(captured[1]), float(captured[2]), int(captured[3]))
        average_task_value = (gmv / captured_count) if captured_count else 0.0

        average_rating = self.db.scalar(
            select(func.coalesce(func.avg(Rating.score), 0.0)).where(
                Rating.direction == RatingDirection.CUSTOMER_TO_WORKER
            )
        )
        open_disputes = int(
            self.db.scalar(
                select(func.count()).select_from(Dispute).where(Dispute.status.in_(["OPEN", "UNDER_REVIEW"]))
            )
            or 0
        )

        return DashboardMetrics(
            total_users=total_users,
            total_customers=total_customers,
            total_workers=total_workers,
            active_workers=active_workers,
            verified_workers=verified_workers,
            total_tasks=total_tasks,
            active_tasks=active,
            completed_tasks=completed,
            cancelled_tasks=cancelled,
            disputed_tasks=disputed,
            completion_rate=round(completion_rate, 4),
            cancellation_rate=round(cancellation_rate, 4),
            total_revenue=round(gmv, 2),
            platform_commission=round(commission, 2),
            worker_payouts=round(payouts, 2),
            average_task_value=round(average_task_value, 2),
            average_rating=round(float(average_rating or 0.0), 2),
            open_disputes=open_disputes,
            pending_verifications=pending_verifications,
        )

    # ---------- series ----------

    def analytics(self, days: int = 30) -> AnalyticsResponse:
        end = _day_start(datetime.now(timezone.utc))
        start = end - timedelta(days=days - 1)

        return AnalyticsResponse(
            dau=self._dau_series(start, end),
            mau=self._mau_series(start, end),
            tasks_created=self._series(
                func.date(Task.created_at),
                Task.created_at >= start,
                Task.created_at < end + timedelta(days=1),
                start=start,
                end=end,
            ),
            tasks_completed=self._series(
                func.date(Task.completed_at),
                Task.status == TaskStatus.COMPLETED.value,
                Task.completed_at.is_not(None),
                Task.completed_at >= start,
                Task.completed_at < end + timedelta(days=1),
                start=start,
                end=end,
            ),
            task_type_distribution=self._task_type_distribution(),
            status_distribution=[
                {"status": status, "count": count}
                for status, count in sorted(self.tasks.count_by_status().items())
            ],
            metrics=self.dashboard_metrics(),
        )

    # ---------- internals ----------

    def _buckets(self, start: datetime, end: datetime) -> list[datetime]:
        day = start
        out = []
        while day <= end:
            out.append(day)
            day += timedelta(days=1)
        return out

    def _series(self, date_expr, *filters, start: datetime, end: datetime) -> list[TimeSeriesPoint]:
        stmt = (
            select(date_expr, func.count())
            .where(*filters)
            .group_by(date_expr)
        )
        counts = {str(day): int(n) for day, n in self.db.execute(stmt).all()}
        return [
            TimeSeriesPoint(date=day.date().isoformat(), value=counts.get(day.date().isoformat(), 0))
            for day in self._buckets(start, end)
        ]

    def _dau_series(self, start: datetime, end: datetime) -> list[TimeSeriesPoint]:
        stmt = (
            select(func.date(AuditLog.created_at), func.count(func.distinct(AuditLog.user_id)))
            .where(
                AuditLog.created_at >= start,
                AuditLog.created_at < end + timedelta(days=1),
                AuditLog.user_id.is_not(None),
            )
            .group_by(func.date(AuditLog.created_at))
        )
        counts = {str(day): int(n) for day, n in self.db.execute(stmt).all()}
        return [
            TimeSeriesPoint(date=day.date().isoformat(), value=counts.get(day.date().isoformat(), 0))
            for day in self._buckets(start, end)
        ]

    def _mau_series(self, start: datetime, end: datetime) -> list[TimeSeriesPoint]:
        """Distinct users seen in the trailing 30 days, sampled daily."""
        points: list[TimeSeriesPoint] = []
        window_start = start - timedelta(days=30)
        for day in self._buckets(start, end):
            count = int(
                self.db.scalar(
                    select(func.count(func.distinct(AuditLog.user_id))).where(
                        AuditLog.created_at >= window_start,
                        AuditLog.created_at < day + timedelta(days=1),
                        AuditLog.user_id.is_not(None),
                    )
                )
                or 0
            )
            points.append(TimeSeriesPoint(date=day.date().isoformat(), value=count))
        return points

    def _task_type_distribution(self, limit: int = 8) -> list[dict]:
        rows = self.db.execute(
            select(Task.task_type, func.count())
            .group_by(Task.task_type)
            .order_by(func.count().desc())
            .limit(limit)
        ).all()
        return [{"task_type": t, "count": int(n)} for t, n in rows]
