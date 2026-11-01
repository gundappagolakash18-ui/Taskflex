"""Phase 4 marketplace schemas: bids, tips, payouts, RideCheck."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BidCreate(BaseModel):
    proposed_amount: float = Field(gt=0, le=1_000_000)
    note: str | None = Field(None, max_length=140)
    estimated_arrival_minutes: int = Field(0, ge=0, le=600)


class BidOut(BaseModel):
    id: str
    task_id: str
    worker_id: str
    proposed_amount: float
    note: str | None = None
    estimated_arrival_minutes: int = 0
    status: str
    expires_at: datetime | None = None
    responded_at: datetime | None = None
    created_at: datetime | None = None
    worker_name: str | None = None
    worker_avatar: str | None = None
    worker_rating: float = 0.0
    worker_rating_count: int = 0
    worker_completed_tasks: int = 0
    worker_tier: str | None = None
    distance_km: float | None = None


class TipRequest(BaseModel):
    amount: float = Field(gt=0, le=50_000)


class TipOut(BaseModel):
    amount: float
    settlement: str
    payment: dict | None = None


class UpiUpdateRequest(BaseModel):
    upi_id: str = Field(min_length=3, max_length=120)


class WithdrawRequest(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    upi_id: str | None = Field(None, min_length=3, max_length=120)


class PayoutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    amount: float
    currency: str
    upi_id: str
    status: str
    utr: str | None = None
    requested_at: datetime | None = None
    completed_at: datetime | None = None


class RideCheckAckRequest(BaseModel):
    action: str = Field(pattern="^(SAFE|HELP)$")
    reason: str | None = Field(None, max_length=120)


class ReadinessConfirmRequest(BaseModel):
    """Placeholder for an optional note; readiness is a simple confirmation."""

    note: str | None = Field(None, max_length=200)
