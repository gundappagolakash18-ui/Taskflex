"""Mutual ratings: customer rates worker, worker rates customer."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.core.logging import get_logger
from app.models import (
    AffinityType,
    CustomerWorkerAffinity,
    NotificationType,
    Rating,
    RatingDirection,
    Review,
    Task,
    User,
    UserRole,
    WorkerProfile,
)
from app.notifications.dispatcher import notify_users_sync
from app.repositories import RatingRepository, UserRepository
from app.schemas.rating import RatingCreate
from app.services.payment_service import PaymentService

logger = get_logger("taskflex.ratings")


class RatingService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = RatingRepository(db)
        self.users = UserRepository(db)
        self.payments = PaymentService(db)

    def _set_affinity(self, customer_id: str, worker_id: str, affinity: str) -> CustomerWorkerAffinity:
        row = self.db.scalar(
            select(CustomerWorkerAffinity).where(
                CustomerWorkerAffinity.customer_id == customer_id,
                CustomerWorkerAffinity.worker_id == worker_id,
            )
        )
        if row is None:
            row = CustomerWorkerAffinity(
                customer_id=customer_id, worker_id=worker_id, affinity_type=affinity
            )
            self.db.add(row)
        else:
            row.affinity_type = affinity
        self.db.flush()
        return row

    def rate_task(self, task: Task, rater: User, payload: RatingCreate) -> tuple[Rating, dict | None]:
        if task.status != "COMPLETED":
            raise ConflictException("Only completed tasks can be rated.")
        if task.customer_id != rater.id and task.assigned_worker_id != rater.id:
            raise ForbiddenException("Only task participants can leave a rating.")

        is_customer = task.customer_id == rater.id
        direction = (
            RatingDirection.CUSTOMER_TO_WORKER if is_customer else RatingDirection.WORKER_TO_CUSTOMER
        )
        ratee_id = task.assigned_worker_id if is_customer else task.customer_id
        if ratee_id is None:
            raise ConflictException("This task has no counterpart to rate.")

        existing = self.db.scalar(
            select(Rating).where(Rating.task_id == task.id, Rating.direction == direction)
        )
        if existing:
            raise ConflictException("You have already rated this task.")

        if not 1 <= payload.score <= 5:
            raise ConflictException("Score must be between 1 and 5.")

        rating = Rating(
            task_id=task.id,
            rater_id=rater.id,
            ratee_id=ratee_id,
            direction=direction,
            score=payload.score,
            comment=(payload.comment or "")[:1000] or None,
        )
        self.repo.add(rating)

        if is_customer:
            profile = self.users.get_worker_profile(ratee_id)
            if profile:
                self.repo.update_worker_rating_summary(profile)
            if payload.score <= 2:
                # Poor experience: never auto-match this worker with this
                # customer again (hard exclusion in the matching engine).
                self._set_affinity(task.customer_id, ratee_id, AffinityType.BLACKLISTED.value)
                logger.info(
                    "worker_auto_blacklisted customer=%s worker=%s score=%d",
                    task.customer_id, ratee_id, payload.score,
                )
            elif payload.score == 5 and payload.prefer_worker:
                self._set_affinity(task.customer_id, ratee_id, AffinityType.PREFERRED.value)
                notify_users_sync(
                    [ratee_id],
                    notification_type=NotificationType.RATING_RECEIVED,
                    title="You're a preferred worker",
                    body=f"The customer loved your work on '{task.title}' and marked you "
                         f"as their preferred runner for next time.",
                    data={"task_id": task.id, "preferred": True},
                    db=self.db,
                )

        if payload.comment and payload.comment.strip():
            review = Review(
                task_id=task.id,
                author_id=rater.id,
                target_user_id=ratee_id,
                rating_score=payload.score,
                body=payload.comment.strip()[:2000],
                is_public=True,
            )
            self.repo.add_review(review)

        notify_users_sync(
            [ratee_id],
            notification_type=NotificationType.RATING_RECEIVED,
            title="You received a new rating",
            body=f"Your work on '{task.title}' was rated {payload.score}/5.",
            data={"task_id": task.id, "score": payload.score},
            db=self.db,
        )

        tip_checkout = None
        if is_customer and payload.tip_amount and float(payload.tip_amount) > 0:
            _payment, tip_checkout = self.payments.tip(task, rater, float(payload.tip_amount))

        self.db.flush()
        logger.info(
            "rating_created",
            extra_fields={"task_id": task.id, "rater_id": rater.id, "score": payload.score},
        )
        return rating, tip_checkout

    def ratings_for_task(self, task: Task, viewer: User) -> list[Rating]:
        if (
            viewer.role != UserRole.ADMIN.value
            and viewer.id not in (task.customer_id, task.assigned_worker_id)
        ):
            raise ForbiddenException("Only task participants can view private ratings.")
        return self.repo.for_task(task.id)

    def reviews_for(self, target_user_id: str, page: int, page_size: int):
        return self.repo.reviews_for(target_user_id, page=page, page_size=page_size)

    def worker_rating_summary(self, worker_user_id: str) -> dict:
        profile = self.users.get_worker_profile(worker_user_id)
        if profile is None:
            raise NotFoundException("Worker profile not found.")
        return {"average": profile.rating_average, "count": profile.rating_count}
