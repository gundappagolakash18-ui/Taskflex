from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import UserRole


def _clean_identifier(v: str) -> str:
    """Accept either an email address or a phone number in one field."""
    v = v.strip()
    if "@" in v:
        return v.lower()
    cleaned = "".join(c for c in v if c.isdigit() or c == "+")
    if len(cleaned.replace("+", "")) < 8:
        raise ValueError("Enter a valid email address or phone number.")
    return cleaned


class RegisterRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "role": "CUSTOMER",
            "full_name": "Ananya Desai",
            "email": "ananya@example.com",
            "phone": "+919812345678",
            "password": "StrongPass123!",
            "city": "Belagavi",
        }
    })

    role: UserRole = UserRole.CUSTOMER
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=8, max_length=20)
    password: str = Field(min_length=8, max_length=128)
    city: str | None = None

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        cleaned = "".join(c for c in v if c.isdigit() or c == "+")
        if len(cleaned.replace("+", "")) < 8:
            raise ValueError("Phone number must contain at least 8 digits")
        return cleaned


class LoginRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {"identifier": "ananya@example.com", "password": "StrongPass123!"}
    })

    identifier: str = Field(min_length=3, max_length=255, description="Email address or phone number")
    password: str = Field(min_length=1, max_length=128)

    @field_validator("identifier")
    @classmethod
    def clean_identifier(cls, v: str) -> str:
        return _clean_identifier(v)


class RefreshRequest(BaseModel):
    refresh_token: str


class GoogleAuthRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {"credential": "<Google id_token from GIS callback>", "role": "CUSTOMER"}
    })

    credential: str = Field(min_length=20, max_length=4096)
    role: UserRole = UserRole.CUSTOMER


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthUser(BaseModel):
    id: str
    full_name: str
    email: str
    phone: str | None = None
    role: str
    avatar_url: str | None = None
    city: str | None = None
    is_email_verified: bool
    created_at: str


class AuthResponse(BaseModel):
    user: AuthUser
    tokens: TokenPair


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=255, description="Email address or phone number")
    code: str = Field(min_length=4, max_length=8, pattern=r"^\d{4,8}$")

    @field_validator("identifier")
    @classmethod
    def clean_identifier(cls, v: str) -> str:
        return _clean_identifier(v)


class ResendOtpRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=255, description="Email address or phone number")

    @field_validator("identifier")
    @classmethod
    def clean_identifier(cls, v: str) -> str:
        return _clean_identifier(v)
