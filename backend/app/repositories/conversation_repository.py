from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Conversation, Message, Task, User


class ConversationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, conversation_id: str) -> Conversation | None:
        stmt = (
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.messages))
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def find_for_task_pair(self, task_id: str | None, user_a: str, user_b: str) -> Conversation | None:
        stmt = (
            select(Conversation)
            .where(
                Conversation.customer_id.in_([user_a, user_b]),
                Conversation.worker_id.in_([user_a, user_b]),
                Conversation.task_id == task_id if task_id else Conversation.task_id.is_(None),
            )
            .options(selectinload(Conversation.messages))
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def for_user(self, user_id: str) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where((Conversation.customer_id == user_id) | (Conversation.worker_id == user_id))
            .options(selectinload(Conversation.messages))
            .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def add_message(self, conversation: Conversation, sender_id: str, body: str) -> Message:
        from datetime import datetime, timezone

        message = Message(conversation_id=conversation.id, sender_id=sender_id, body=body)
        self.db.add(message)
        conversation.last_message_at = datetime.now(timezone.utc)
        self.db.flush()
        return message

    def unread_count_for(self, conversation: Conversation, viewer_id: str) -> int:
        return sum(1 for m in conversation.messages if not m.is_read and m.sender_id != viewer_id)

    def user_by_id(self, user_id: str) -> User | None:
        return self.db.get(User, user_id)

    def task_by_id(self, task_id: str) -> Task | None:
        return self.db.get(Task, task_id)
