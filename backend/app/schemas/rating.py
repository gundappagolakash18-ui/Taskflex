from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RatingDirection


class RatingCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {"task_id": "<uuid>", "score": 5, "comment": "Quick, polite and reliable."}
    })

    task_id: str
    score: int = Field(ge=1, le=5)
    comment: str | None = Field(None, max_length=1000)
    # Customer-only: mark a 5-star worker as preferred (matched first next time).
    prefer_worker: bool = False
    # Optional tip paid alongside the rating (credited 100% to the worker).
    tip_amount: float | None = Field(None, ge=0, le=50000)


class RatingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    rater_id: str
    ratee_id: str
    direction: RatingDirection
    score: int
    comment: str | None = None
    created_at: datetime


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    author_id: str
    target_user_id: str
    rating_score: int
    body: str
    created_at: datetime
    author_name: str | None = None
