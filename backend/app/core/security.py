from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import bcrypt
import jwt

from app.core.config import settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _create_token(
    subject: str, secret: str, expires_delta: timedelta, token_type: str, extra: dict[str, Any] | None = None
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": uuid4().hex,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, role: str) -> str:
    return _create_token(
        user_id,
        settings.jwt_secret,
        timedelta(minutes=settings.access_token_expire_minutes),
        "access",
        {"role": role},
    )


def create_refresh_token(user_id: str) -> str:
    return _create_token(
        user_id,
        settings.jwt_refresh_secret,
        timedelta(days=settings.refresh_token_expire_days),
        "refresh",
    )


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    """Decode and validate a JWT. Raises jwt.InvalidTokenError / jwt.ExpiredSignatureError."""
    secret = settings.jwt_secret if expected_type == "access" else settings.jwt_refresh_secret
    payload = jwt.decode(token, secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"Expected {expected_type} token, got {payload.get('type')}")
    return payload


def generate_random_token(n_bytes: int = 32) -> str:
    import secrets

    return secrets.token_urlsafe(n_bytes)
