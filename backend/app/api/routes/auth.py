from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.serializers import serialize_auth_user
from app.core.config import settings
from app.db.session import get_db
from app.core.responses import success_response
from app.models import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    GoogleAuthRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResendOtpRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
)
from app.services import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    user = service.register(
        role=payload.role.value,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        password=payload.password,
        city=payload.city,
    )
    return success_response(
        {"user": serialize_auth_user(user), "needs_verification": True},
        message="Account created! Check your email for the 6-digit verification code.",
        status_code=201,
    )


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    user, tokens = service.login(payload.identifier, payload.password)
    return success_response(
        {"user": serialize_auth_user(user), "tokens": tokens},
        message="Signed in successfully.",
    )


@router.get("/google/config")
def google_config():
    # The frontend loads the GIS button only when this reports enabled=true.
    return success_response(
        {"enabled": settings.google_oauth_enabled, "client_id": settings.google_client_id or None}
    )


@router.post("/google")
def google_auth(payload: GoogleAuthRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    user, tokens, created = service.google_login(payload.credential, role=payload.role.value)
    message = "Welcome to TaskFlex! Your account is ready." if created else "Signed in successfully."
    return success_response(
        {"user": serialize_auth_user(user), "tokens": tokens, "created": created},
        message=message,
    )


@router.post("/refresh")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    user, tokens = service.refresh(payload.refresh_token)
    return success_response(
        {"user": serialize_auth_user(user), "tokens": tokens},
        message="Session refreshed.",
    )


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    token = service.forgot_password(payload.email)
    data: dict = {"message": "If an account exists for this email, a reset link has been sent."}
    if token:
        data["reset_token"] = token  # dev/demo convenience only; never returned in production
    return success_response(data)


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    service.reset_password(payload.token, payload.new_password)
    return success_response({"message": "Password updated. You can now sign in."})


@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    user = service.verify_email_otp(payload.identifier, payload.code)
    tokens = service._token_pair(user)
    service.users.touch_last_login(user)
    return success_response(
        {"user": serialize_auth_user(user), "tokens": tokens},
        message="Email verified. Welcome to TaskFlex!",
    )


@router.post("/resend-otp")
def resend_otp(payload: ResendOtpRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    service.resend_email_otp(payload.identifier)
    return success_response({"message": "If the code can be resent, a new one is on its way."})


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return success_response({"user": serialize_auth_user(user)})
