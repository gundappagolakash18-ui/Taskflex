from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TaskStatus, TaskType, Urgency
from app.schemas.worker import WorkerPublic


# ---------- AI parsing ----------


class TaskParseRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "text": "I need someone to submit my documents at the government office tomorrow morning. My budget is 300 rupees."
        }
    })

    text: str = Field(min_length=10, max_length=2000)


class ParsedTaskDraft(BaseModel):
    """Structured, validated AI interpretation of a natural-language request."""

    task_type: TaskType = TaskType.OTHER
    title: str = ""
    description: str = ""
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    scheduled_date: date | None = None
    scheduled_time: time | None = None
    time_of_day: str | None = None  # morning / afternoon / evening / night
    budget: float | None = Field(None, gt=0)
    currency: str = "INR"
    urgency: Urgency = Urgency.NORMAL
    required_skills: list[str] = []
    estimated_duration_minutes: int = Field(60, ge=15, le=480)
    special_requirements: list[str] = []
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    provider: str = "mock"
    missing_fields: list[str] = []
    clarification_questions: list[str] = []

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "task_type": "document_submission",
            "title": "Document submission at government office",
            "description": "Submit documents at the government office.",
            "location": "Government Office",
            "scheduled_date": "2026-10-05",
            "time_of_day": "morning",
            "budget": 300,
            "urgency": "normal",
            "required_skills": ["document_handling"],
            "estimated_duration_minutes": 60,
            "confidence": 0.85,
            "provider": "mock",
            "missing_fields": [],
            "clarification_questions": [],
        }
    })


# ---------- Task CRUD ----------


class TaskCreate(BaseModel):
    """Creates a task in PENDING_CONFIRMATION. Dispatch never happens implicitly."""

    title: str = Field(min_length=4, max_length=160)
    description: str = Field(min_length=10, max_length=4000)
    task_type: TaskType = TaskType.OTHER
    urgency: Urgency = Urgency.NORMAL
    scheduled_date: date | None = None
    scheduled_time: time | None = None
    estimated_duration_minutes: int = Field(60, ge=15, le=480)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    address_text: str | None = Field(None, max_length=500)
    area_name: str | None = Field(None, max_length=120)
    city: str | None = Field(None, max_length=100)
    budget: float = Field(gt=0, le=1_000_000)
    special_requirements: str | None = Field(None, max_length=1000)
    required_skills: list[str] = []
    parsed_by_ai: bool = False
    ai_confidence: float = Field(0.0, ge=0.0, le=1.0)

    # Round-trip errand: worker collects at the pickup, completes the errand
    # at latitude/longitude, then returns the goods to the pickup origin.
    is_round_trip: bool = False
    pickup_latitude: float | None = Field(None, ge=-90, le=90)
    pickup_longitude: float | None = Field(None, ge=-180, le=180)
    pickup_address: str | None = Field(None, max_length=500)


class TaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=4, max_length=160)
    description: str | None = Field(None, min_length=10, max_length=4000)
    task_type: TaskType | None = None
    urgency: Urgency | None = None
    scheduled_date: date | None = None
    scheduled_time: time | None = None
    estimated_duration_minutes: int | None = Field(None, ge=15, le=480)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    address_text: str | None = Field(None, max_length=500)
    area_name: str | None = Field(None, max_length=120)
    city: str | None = Field(None, max_length=100)
    budget: float | None = Field(None, gt=0)
    special_requirements: str | None = Field(None, max_length=1000)


class CancelTaskRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class OtpVerifyRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"otp": "4821"}})

    otp: str = Field(pattern=r"^\d{4}$")


class TaskCompleteRequest(OtpVerifyRequest):
    """Worker submits the completion code the customer read out."""


class FareEstimateRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "origin_latitude": 15.8497, "origin_longitude": 74.4977,
            "destination_latitude": 15.8610, "destination_longitude": 74.5100,
            "wait_minutes": 10, "urgency": "high", "proposed_budget": 300,
        }
    })

    origin_latitude: float | None = Field(None, ge=-90, le=90)
    origin_longitude: float | None = Field(None, ge=-180, le=180)
    destination_latitude: float | None = Field(None, ge=-90, le=90)
    destination_longitude: float | None = Field(None, ge=-180, le=180)
    wait_minutes: float = Field(0, ge=0, le=240)
    urgency: Urgency = Urgency.NORMAL
    proposed_budget: float | None = Field(None, gt=0, le=1_000_000)
    is_round_trip: bool = False


class SosTriggerRequest(BaseModel):
    """Optional last-known fix from the device; the server's own telemetry
    history is what gets frozen as evidence."""

    model_config = ConfigDict(json_schema_extra={
        "example": {"latitude": 15.8497, "longitude": 74.4977, "message": "Unsafe area, please call."}
    })

    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    message: str | None = Field(None, max_length=500)


class TaskStatusUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {"status": "IN_PROGRESS", "note": "Started document submission."}
    })

    status: TaskStatus
    note: str | None = Field(None, max_length=500)


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    skill_name: str
    is_required: bool


class WorkerBrief(BaseModel):
    id: str
    full_name: str
    avatar_url: str | None = None
    city: str | None = None
    is_verified: bool = False
    rating_average: float = 0.0
    rating_count: int = 0
    completed_tasks_count: int = 0


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    task_type: str
    status: TaskStatus
    urgency: str
    scheduled_date: date | None = None
    scheduled_time: time | None = None
    estimated_duration_minutes: int
    latitude: float | None = None
    longitude: float | None = None
    address_text: str | None = None
    area_name: str | None = None
    city: str | None = None
    budget: float
    currency: str
    special_requirements: str | None = None
    parsed_by_ai: bool
    ai_confidence: float
    assigned_worker_id: str | None = None
    payment_status: str | None = None
    commission_amount: float = 0
    worker_payout_amount: float = 0
    tip_amount: float = 0
    is_scheduled: bool = False
    scheduled_for: datetime | None = None
    worker_confirmed_readiness: bool = False
    is_round_trip: bool = False
    return_otp_verified_at: datetime | None = None
    worker_completed_at: datetime | None = None
    customer_confirmed_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    customer: WorkerBrief | None = None
    worker: WorkerBrief | None = None
    requirements: list[RequirementOut] = []
    my_offer_status: str | None = None  # populated for worker views


class StatusHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: str | None = None
    to_status: str
    note: str | None = None
    changed_by_role: str | None = None
    created_at: datetime


class MatchBreakdown(BaseModel):
    distance: float
    skill_match: float
    availability: float
    rating: float
    reliability: float
    workload: float
    final_score: float
    distance_km: float
    tier_boost: float = 0
    preferred_boost: float = 0
    preferred: bool = False
    chained: bool = False
    chain_task_id: str | None = None


class MatchOut(BaseModel):
    worker: WorkerPublic
    breakdown: MatchBreakdown


class TaskListFilters(BaseModel):
    status: str | None = None
    task_type: str | None = None
    search: str | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
