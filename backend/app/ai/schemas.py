"""Pydantic schemas that every AI provider's raw output MUST validate against.

The rest of the application only ever sees instances of ParsedTaskDraft —
never raw LLM output.
"""

from datetime import date, time

from pydantic import BaseModel, Field, field_validator

from app.ai.task_classifier import skills_for_type
from app.models.enums import TaskType, Urgency
from app.schemas.task import ParsedTaskDraft


class AIRawExtraction(BaseModel):
    """Schema an LLM is asked to fill. Deliberately lenient; ParsedTaskDraft is strict."""

    task_type: str = "other"
    title: str | None = None
    description: str | None = None
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    scheduled_date: str | None = None
    scheduled_time: str | None = None
    time_of_day: str | None = None
    budget: float | None = Field(None, gt=0)
    urgency: str = "normal"
    required_skills: list[str] = Field(default_factory=list)
    estimated_duration_minutes: int = Field(60, ge=15, le=480)
    special_requirements: list[str] = Field(default_factory=list)

    @field_validator("scheduled_date")
    @classmethod
    def validate_date(cls, v: str | None) -> str | None:
        if v in (None, "", "null"):
            return None
        date.fromisoformat(v)  # raises if invalid
        return v

    @field_validator("scheduled_time")
    @classmethod
    def validate_time(cls, v: str | None) -> str | None:
        if v in (None, "", "null"):
            return None
        time.fromisoformat(v)
        return v

    @field_validator("urgency")
    @classmethod
    def validate_urgency(cls, v: str) -> str:
        allowed = {u.value for u in Urgency}
        if v not in allowed:
            return "normal"
        return v


class ProviderUnavailableError(Exception):
    """Raised when a provider has no API key / SDK / connectivity."""


__all__ = ["AIRawExtraction", "ParsedTaskDraft", "ProviderUnavailableError", "skills_for_type", "TaskType"]
