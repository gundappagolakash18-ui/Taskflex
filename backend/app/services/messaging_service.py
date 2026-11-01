"""Task-scoped chat between customer and worker.

A conversation stays writable while the task is live and for
`chat_close_after_hours` after it completes or is cancelled. Closing is
enforced server-side on REST and WebSocket paths; a background sweeper
persists the closed timestamp so list endpoints report the final state."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ChatClosedException, ForbiddenException, NotFoundException
from app.core.logging import get_logger
from app.core.privacy import mask_phone_numbers
from app.core.timeutils import as_aware, utcnow
from app.models import Conversation, Message, NotificationType, Task, User
from app.models.enums import TaskStatus
from app.notifications.dispatcher import notify_users
from app.repositories import ConversationRepository
from app.websocket.manager import manager

logger = get_logger("taskflex.messaging")

MAX_MESSAGE_LENGTH = 2000
TASK_CLOSED_STATUSES = {TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value}


class MessagingService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ConversationRepository(db)

    # ------------------------------------------------------------------
    # Lifecycle: conversations close 24 h after the task closes
    # ------------------------------------------------------------------

    def task_for(self, conversation: Conversation) -> Task | None:
        return self.repo.task_by_id(conversation.task_id) if conversation.task_id else None

    def chat_closes_at(self, task: Task | None) -> datetime | None:
        """When the chat becomes read-only, or None while the task is live."""
        if task is None or task.status not in TASK_CLOSED_STATUSES:
            return None
        closed = task.completed_at or task.cancelled_at
        if closed is None:
            return None
        return as_aware(closed) + timedelta(hours=settings.chat_close_after_hours)

    def is_closed(self, conversation: Conversation, task: Task | None = None) -> bool:
        if conversation.closed_at is not None:
            return True
        closes_at = self.chat_closes_at(task if task is not None else self.task_for(conversation))
        return closes_at is not None and utcnow() >= closes_at

    def assert_open(self, conversation: Conversation, task: Task | None = None) -> None:
        if self.is_closed(conversation, task):
            raise ChatClosedException()

    def close_due_conversations(self, *, now: datetime | None = None) -> int:
        """Persist closed_at for every conversation past its grace period.
        Safe to run repeatedly; returns the number of conversations closed."""
        now = now or utcnow()
        rows = self.db.execute(
            select(Conversation, Task)
            .join(Task, Conversation.task_id == Task.id)
            .where(
                Conversation.closed_at.is_(None),
                Task.status.in_(TASK_CLOSED_STATUSES),
            )
        ).all()
        closed = 0
        for conversation, task in rows:
            closes_at = self.chat_closes_at(task)
            if closes_at is not None and now >= closes_at:
                conversation.closed_at = now
                closed += 1
        if closed:
            self.db.flush()
            logger.info("chat_auto_closed conversations=%d", closed)
        return closed

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_conversations(self, user: User) -> list[dict]:
        conversations = self.repo.for_user(user.id)
        items = []
        for conv in conversations:
            counterpart_id = conv.worker_id if user.id == conv.customer_id else conv.customer_id
            counterpart = self.repo.user_by_id(counterpart_id)
            task = self.repo.task_by_id(conv.task_id) if conv.task_id else None
            closes_at = self.chat_closes_at(task)
            is_closed = conv.closed_at is not None or (closes_at is not None and utcnow() >= closes_at)
            items.append(
                {
                    "id": conv.id,
                    "task_id": conv.task_id,
                    "task_title": task.title if task else None,
                    "counterpart_id": counterpart_id,
                    "counterpart_name": counterpart.full_name if counterpart else "User",
                    "counterpart_avatar": counterpart.avatar_url if counterpart else None,
                    "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
                    "unread_count": self.repo.unread_count_for(conv, user.id),
                    "chat_open": not is_closed,
                    "closes_at": closes_at.isoformat() if closes_at else None,
                    "closed_at": conv.closed_at.isoformat() if conv.closed_at else None,
                }
            )
        return items

    def get_or_create_for_task(self, task: Task, requester: User) -> Conversation:
        if requester.id not in (task.customer_id, task.assigned_worker_id):
            raise ForbiddenException("Only task participants can open this conversation.")
        if task.assigned_worker_id is None:
            raise NotFoundException("Chat opens once a worker is assigned to the task.")
        conv = self.repo.find_for_task_pair(task.id, task.customer_id, task.assigned_worker_id)
        if conv is None:
            conv = Conversation(
                task_id=task.id,
                customer_id=task.customer_id,
                worker_id=task.assigned_worker_id,
            )
            self.db.add(conv)
            self.db.flush()
        return conv

    def assert_participant(self, conversation: Conversation, user: User) -> None:
        if user.id not in conversation.participant_ids():
            raise ForbiddenException("You are not part of this conversation.")

    def get_conversation_or_404(self, conversation_id: str) -> Conversation:
        conversation = self.repo.get(conversation_id)
        if conversation is None:
            raise NotFoundException("Conversation not found.")
        return conversation

    def messages_for(self, conversation: Conversation, page: int = 1, page_size: int = 50):
        messages = sorted(conversation.messages, key=lambda m: m.created_at or datetime.min.replace(tzinfo=timezone.utc))
        total = len(messages)
        start = (max(page, 1) - 1) * page_size
        return messages[start : start + page_size], total

    def get_message_or_404(self, message_id: str) -> Message:
        message = self.db.get(Message, message_id)
        if message is None:
            raise NotFoundException("Message not found.")
        return message

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def message_payload(self, message: Message, sender: User, conversation: Conversation) -> dict:
        return {
            "conversation_id": conversation.id,
            "task_id": conversation.task_id,
            "message_id": message.id,
            "sender_id": sender.id,
            "sender_name": sender.full_name,
            "body": mask_phone_numbers(message.body),
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }

    async def send_message(self, conversation: Conversation, sender: User, body: str) -> Message:
        self.assert_participant(conversation, sender)
        self.assert_open(conversation)
        text = mask_phone_numbers((body or "").strip())
        if not text:
            raise NotFoundException("Message body cannot be empty.")
        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[:MAX_MESSAGE_LENGTH]

        message = self.repo.add_message(conversation, sender.id, text)
        counterpart_id = (
            conversation.worker_id if sender.id == conversation.customer_id else conversation.customer_id
        )

        # Chat content stays in-app + WebSocket only: never forward message
        # bodies over email/SMS, where they would leave the platform's control.
        await notify_users(
            [counterpart_id],
            notification_type=NotificationType.MESSAGE_RECEIVED,
            title=f"New message from {sender.full_name}",
            body=text[:120],
            data={"conversation_id": conversation.id, "message_id": message.id},
            push_ws=False,
            deliver_email=False,
            deliver_sms=False,
            db=self.db,
        )
        await manager.send_to_user(
            counterpart_id,
            "message",
            self.message_payload(message, sender, conversation),
        )
        return message

    def mark_read(self, conversation: Conversation, viewer: User) -> int:
        self.assert_participant(conversation, viewer)
        self.assert_open(conversation)
        now = datetime.now(timezone.utc)
        count = 0
        for message in self.db.scalars(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.is_read.is_(False),
                Message.sender_id != viewer.id,
            )
        ):
            message.is_read = True
            message.read_at = now
            count += 1
        if count:
            self.db.flush()
        return count


async def chat_close_sweeper(stop_event: asyncio.Event) -> None:
    """Background loop started from the app lifespan. Exceptions are logged so
    a transient database error never kills future sweeps."""
    from app.db.session import SessionLocal

    while not stop_event.is_set():
        try:
            db = SessionLocal()
            try:
                closed = MessagingService(db).close_due_conversations()
                db.commit()
                if closed:
                    logger.info("chat_sweeper_closed count=%d", closed)
            finally:
                db.close()
        except Exception:
            logger.exception("chat_sweeper_failed")
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.chat_sweep_interval_seconds
            )
        except TimeoutError:
            continue
