from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DisputeStatus


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    provider: str
    purpose: str | None = None
    amount: float
    currency: str
    commission_amount: float
    worker_payout_amount: float
    status: str
    created_at: datetime
    captured_at: datetime | None = None


class CheckoutVerifyRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "razorpay_order_id": "order_XXXXXXXXXXXXXX",
            "razorpay_payment_id": "pay_XXXXXXXXXXXXXX",
            "razorpay_signature": "<hmac-sha256 hex>",
        }
    })

    razorpay_order_id: str = Field(min_length=4, max_length=120)
    razorpay_payment_id: str = Field(min_length=4, max_length=120)
    razorpay_signature: str = Field(min_length=16, max_length=256)


class DisputeCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "task_id": "<uuid>",
            "reason": "worker_no_show",
            "description": "The worker never arrived at the location and marked the task complete.",
        }
    })

    task_id: str
    reason: str = Field(min_length=3, max_length=60)
    description: str = Field(min_length=10, max_length=2000)


class DisputeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    raised_by_id: str
    against_id: str | None = None
    reason: str
    description: str
    status: DisputeStatus
    resolution_note: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class DisputeResolveRequest(BaseModel):
    status: DisputeStatus = DisputeStatus.RESOLVED
    resolution_note: str = Field(min_length=5, max_length=2000)
