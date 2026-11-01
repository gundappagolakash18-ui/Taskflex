from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.privacy import mask_phone_numbers
from app.schemas.task import WorkerBrief


class ConversationCreate(BaseModel):
    task_id: str | None = None
    participant_id: str | None = None


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    sender_id: str
    body: str
    is_read: bool
    created_at: datetime

    @field_validator("body")
    @classmethod
    def _mask_contact_info(cls, value: str) -> str:
        # Messages stored before masking shipped still contain raw numbers.
        return mask_phone_numbers(value)


class ConversationOut(BaseModel):
    id: str
    task_id: str | None = None
    task_title: str | None = None
    counterpart: WorkerBrief | None = None
    last_message: str | None = None
    last_message_at: datetime | None = None
    unread_count: int = 0
    created_at: datetime
