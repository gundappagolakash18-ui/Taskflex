from datetime import date, datetime, timezone

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.timeutils import utcnow_naive
from app.models import (
    Task,
    TaskAssignment,
    TaskOffer,
    TaskStatusHistory,
    User,
    WorkerProfile,
)


class TaskRepository:
    def __init__(self, db: Session):
        self.db = db

    _LOAD = (
        selectinload(Task.customer),
        selectinload(Task.requirements),
        selectinload(Task.locations),
        selectinload(Task.offers),
        selectinload(Task.assignments).selectinload(TaskAssignment.worker),
        selectinload(Task.status_history),
        selectinload(Task.ratings),
    )

    def get(self, task_id: str) -> Task | None:
        stmt = select(Task).where(Task.id == task_id).options(*self._LOAD)
        return self.db.execute(stmt).scalar_one_or_none()

    def add(self, task: Task) -> Task:
        self.db.add(task)
        self.db.flush()
        return task

    def add_status_history(self, **fields) -> TaskStatusHistory:
        entry = TaskStatusHistory(**fields)
        self.db.add(entry)
        self.db.flush()
        return entry

    def tasks_for_customer(self, customer_id: str, status: str | None = None) -> list[Task]:
        stmt = select(Task).where(Task.customer_id == customer_id).options(*self._LOAD)
        if status:
            stmt = stmt.where(Task.status == status)
        return list(self.db.execute(stmt.order_by(Task.created_at.desc())).scalars().all())

    def tasks_for_worker(self, worker_id: str) -> list[Task]:
        stmt = (
            select(Task)
            .join(TaskAssignment, TaskAssignment.task_id == Task.id)
            .where(TaskAssignment.worker_id == worker_id)
            .options(*self._LOAD)
            .order_by(Task.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().unique().all())

    def pending_offers_for_worker(self, worker_id: str) -> list[tuple[TaskOffer, Task]]:
        stmt = (
            select(TaskOffer, Task)
            .join(Task, Task.id == TaskOffer.task_id)
            .where(
                TaskOffer.worker_id == worker_id,
                TaskOffer.status == "PENDING",
                or_(TaskOffer.expires_at.is_(None), TaskOffer.expires_at > utcnow_naive()),
                Task.status.in_(["SEARCHING_WORKER", "OFFERED"]),
            )
            .options(selectinload(Task.customer), selectinload(Task.requirements),
                     selectinload(Task.assignments).selectinload(TaskAssignment.worker),
                     selectinload(Task.offers), selectinload(Task.status_history),
                     selectinload(Task.ratings), selectinload(Task.locations))
            .order_by(TaskOffer.created_at.desc())
        )
        return [(o, t) for o, t in self.db.execute(stmt).all()]

    def expired_pending_offers(self) -> list[TaskOffer]:
        stmt = select(TaskOffer).where(
            TaskOffer.status == "PENDING",
            TaskOffer.expires_at.is_not(None),
            TaskOffer.expires_at <= utcnow_naive(),
        )
        return list(self.db.execute(stmt).scalars().all())

    def active_assignment_for_worker(self, worker_id: str) -> tuple[TaskAssignment, Task] | None:
        stmt = (
            select(TaskAssignment, Task)
            .join(Task, Task.id == TaskAssignment.task_id)
            .where(
                TaskAssignment.worker_id == worker_id,
                TaskAssignment.status == "ACTIVE",
                Task.status.notin_(["COMPLETED", "CANCELLED", "DISPUTED"]),
            )
            .options(*self._LOAD)
            .order_by(TaskAssignment.accepted_at.desc())
            .limit(1)
        )
        row = self.db.execute(stmt).first()
        return (row[0], row[1]) if row else None

    def worker_active_task_count(self, worker_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(TaskAssignment)
            .join(Task, Task.id == TaskAssignment.task_id)
            .where(
                TaskAssignment.worker_id == worker_id,
                TaskAssignment.status == "ACTIVE",
                Task.status.notin_(["COMPLETED", "CANCELLED", "DISPUTED"]),
            )
        )
        return self.db.execute(stmt).scalar_one()

    def search_admin(
        self, *, status: str | None = None, task_type: str | None = None, search: str | None = None,
        customer_id: str | None = None, page: int = 1, page_size: int = 20,
    ) -> tuple[list[Task], int]:
        stmt: Select = select(Task).options(*self._LOAD)
        if status:
            stmt = stmt.where(Task.status == status)
        if task_type:
            stmt = stmt.where(Task.task_type == task_type)
        if customer_id:
            stmt = stmt.where(Task.customer_id == customer_id)
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(or_(func.lower(Task.title).like(like), func.lower(Task.description).like(like)))
        stmt = stmt.order_by(Task.created_at.desc())
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = self.db.execute(count_stmt).scalar_one()
        rows = self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().unique().all()
        return list(rows), total

    def count_by_status(self) -> dict[str, int]:
        rows = self.db.execute(select(Task.status, func.count()).group_by(Task.status)).all()
        return {status: count for status, count in rows}

    def tasks_created_between(self, start: datetime, end: datetime) -> int:
        stmt = select(func.count()).select_from(Task).where(
            and_(Task.created_at >= start, Task.created_at < end)
        )
        return self.db.execute(stmt).scalar_one()

    def tasks_completed_between(self, start: datetime, end: datetime) -> int:
        stmt = select(func.count()).select_from(Task).where(
            and_(Task.status == "COMPLETED", Task.completed_at.is_not(None),
                 Task.completed_at >= start, Task.completed_at < end)
        )
        return self.db.execute(stmt).scalar_one()

    def all_tasks(self) -> list[Task]:
        return list(self.db.execute(select(Task).options(*self._LOAD)).scalars().unique().all())
