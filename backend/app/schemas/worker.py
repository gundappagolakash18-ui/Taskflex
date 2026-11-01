from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    category: str


class AvailabilityEntry(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    start_time: str = "08:00"
    end_time: str = "20:00"
    is_available: bool = True


class WorkerPublic(BaseModel):
    """Worker listing/profile as seen by customers and admins."""

    id: str  # worker user id
    full_name: str
    avatar_url: str | None = None
    city: str | None = None
    area: str | None = None
    bio: str | None = None
    experience_years: int
    languages: str
    is_online: bool
    is_verified: bool
    rating_average: float
    rating_count: int
    completed_tasks_count: int
    tier: str | None = None
    skills: list[str] = []


class WorkerPrivate(WorkerPublic):
    working_radius_km: float
    max_concurrent_tasks: int
    cancelled_tasks_count: int
    total_earnings: float
    verification_status: str
    availability: list[AvailabilityEntry] = []


class WorkerProfileUpdate(BaseModel):
    bio: str | None = Field(None, max_length=1000)
    address: str | None = Field(None, max_length=500)
    area: str | None = Field(None, max_length=120)
    city: str | None = Field(None, max_length=100)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    experience_years: int | None = Field(None, ge=0, le=60)
    languages: str | None = Field(None, max_length=255)
    working_radius_km: float | None = Field(None, gt=0, le=100)
    max_concurrent_tasks: int | None = Field(None, ge=1, le=10)
    upi_id: str | None = Field(None, min_length=3, max_length=120)
    skill_slugs: list[str] | None = None
    availability: list[AvailabilityEntry] | None = None


class OnlineStatusUpdate(BaseModel):
    is_online: bool


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_type: str
    file_name: str
    mime_type: str
    file_size: int
    status: str
    rejection_reason: str | None = None
    created_at: datetime


class OfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    status: str
    match_score: float
    expires_at: datetime | None = None
    created_at: datetime


class EarningsSummary(BaseModel):
    total_earnings: float
    today_earnings: float
    week_earnings: float
    month_earnings: float
    completed_tasks: int
    pending_clearance: float
    currency: str = "INR"
