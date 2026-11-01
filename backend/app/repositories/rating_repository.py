from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Rating, Review, User, WorkerProfile


class RatingRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, rating_id: str) -> Rating | None:
        return self.db.get(Rating, rating_id)

    def add(self, rating: Rating) -> Rating:
        self.db.add(rating)
        self.db.flush()
        return rating

    def for_task(self, task_id: str) -> list[Rating]:
        stmt = select(Rating).where(Rating.task_id == task_id)
        return list(self.db.execute(stmt).scalars().all())

    def for_ratee(self, ratee_id: str, page: int = 1, page_size: int = 20) -> tuple[list[tuple[Rating, User]], int]:
        stmt = select(Rating, User).join(User, User.id == Rating.rater_id).where(Rating.ratee_id == ratee_id)
        stmt = stmt.order_by(Rating.created_at.desc())
        from sqlalchemy import func

        total = self.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
        rows = self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
        return list(rows), total

    def add_review(self, review: Review) -> Review:
        self.db.add(review)
        self.db.flush()
        return review

    def reviews_for(self, target_user_id: str, page: int = 1, page_size: int = 20) -> tuple[list[dict], int]:
        from sqlalchemy import func

        stmt = select(Review, User).join(User, User.id == Review.author_id).where(
            Review.target_user_id == target_user_id, Review.is_public.is_(True)
        ).order_by(Review.created_at.desc())
        total = self.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
        rows = self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
        items = [
            {
                "id": r.id,
                "task_id": r.task_id,
                "author_id": r.author_id,
                "target_user_id": r.target_user_id,
                "rating_score": r.rating_score,
                "body": r.body,
                "created_at": r.created_at.isoformat(),
                "author_name": u.full_name,
                "author_avatar": u.avatar_url,
            }
            for r, u in rows
        ]
        return items, total

    def update_worker_rating_summary(self, worker_profile: WorkerProfile) -> None:
        from sqlalchemy import func

        stmt = select(func.avg(Rating.score), func.count()).where(
            Rating.ratee_id == worker_profile.user_id,
            Rating.direction == "CUSTOMER_TO_WORKER",
        )
        avg, count = self.db.execute(stmt).one()
        worker_profile.rating_average = round(float(avg), 2) if avg is not None else 0.0
        worker_profile.rating_count = int(count or 0)
        self.db.flush()
