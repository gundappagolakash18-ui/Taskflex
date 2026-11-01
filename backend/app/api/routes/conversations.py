from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.core.responses import success_response
from app.models import User
from app.schemas.conversation import MessageCreate
from app.services import MessagingService, TaskService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
def list_conversations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = MessagingService(db)
    conversations = service.list_conversations(user)
    return success_response({"items": conversations, "total": len(conversations)})


@router.post("", status_code=201)
async def open_conversation(
    task_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task_service = TaskService(db)
    task = task_service.get_task_or_404(task_id)
    service = MessagingService(db)
    conversation = service.get_or_create_for_task(task, user)
    return success_response(
        {
            "conversation": {
                "id": conversation.id,
                "task_id": conversation.task_id,
                "chat_open": not service.is_closed(conversation, task),
                "closes_at": (
                    service.chat_closes_at(task).isoformat()
                    if service.chat_closes_at(task)
                    else None
                ),
            }
        },
        status_code=201,
    )


@router.get("/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = MessagingService(db)
    conversation = service.get_conversation_or_404(conversation_id)
    service.assert_participant(conversation, user)
    service.assert_open(conversation)
    messages, total = service.messages_for(conversation, page, page_size)
    service.mark_read(conversation, user)
    from app.schemas.conversation import MessageOut

    return success_response(
        {
            "items": [MessageOut.model_validate(m).model_dump(mode="json") for m in messages],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/{conversation_id}/messages", status_code=201)
async def send_message(
    conversation_id: str,
    payload: MessageCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = MessagingService(db)
    conversation = service.get_conversation_or_404(conversation_id)
    service.assert_participant(conversation, user)
    message = await service.send_message(conversation, user, payload.body)
    from app.schemas.conversation import MessageOut

    return success_response(
        {"message": MessageOut.model_validate(message).model_dump(mode="json")},
        status_code=201,
    )
