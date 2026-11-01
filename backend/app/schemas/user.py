from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    phone: str
    full_name: str
    role: UserRole
    avatar_url: str | None = None
    city: str | None = None
    is_active: bool
    is_email_verified: bool
    created_at: datetime
    last_login_at: datetime | None = None


class UserPublic(BaseModel):
    """Safe projection used when referencing other users (no email/phone)."""

    id: str
    full_name: str
    avatar_url: str | None = None
    city: str | None = None
    role: str


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=120)
    phone: str | None = Field(None, min_length=8, max_length=20)
    avatar_url: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=100)


class WalletOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    balance: float
    currency: str
    total_earned: float
    total_spent: float


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    amount: float
    balance_after: float
    currency: str
    reference_type: str | None = None
    reference_id: str | None = None
    description: str
    created_at: datetime


class SavedLocationCreate(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    address: str = Field(min_length=4, max_length=500)
    area: str | None = None
    city: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    is_default: bool = False


class SavedLocationOut(SavedLocationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
