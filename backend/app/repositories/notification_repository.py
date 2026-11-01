from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Notification


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **fields) -> Notification:
        n = Notification(**fields)
        self.db.add(n)
        self.db.flush()
        return n

    def for_user(self, user_id: str, unread_only: bool = False, page: int = 1, page_size: int = 20):
        stmt = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        stmt = stmt.order_by(Notification.created_at.desc())
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = self.db.execute(count_stmt).scalar_one()
        items = self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
        return list(items), total

    def mark_read(self, notification: Notification) -> Notification:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        self.db.flush()
        return notification

    def mark_all_read(self, user_id: str) -> int:
        stmt = select(Notification).where(Notification.user_id == user_id, Notification.is_read.is_(False))
        unread = list(self.db.execute(stmt).scalars().all())
        now = datetime.now(timezone.utc)
        for n in unread:
            n.is_read = True
            n.read_at = now
        self.db.flush()
        return len(unread)

    def unread_count(self, user_id: str) -> int:
        stmt = select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id, Notification.is_read.is_(False)
        )
        return self.db.execute(stmt).scalar_one()
