from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

import jwt as pyjwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    ConflictException,
    ErrorCode,
    RateLimitException,
    UnauthorizedException,
)
from app.core.google_oauth import verify_google_id_token
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_random_token,
    hash_password,
    verify_password,
)
from app.models import EmailOtp, User
from app.notifications.channels import send_email_smtp, smtp_configured
from app.repositories import AuditRepository, UserRepository

logger = get_logger("auth")

OTP_PURPOSE_EMAIL_VERIFICATION = "EMAIL_VERIFICATION"


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.audit = AuditRepository(db)

    # ---------- registration ----------

    def register(
        self,
        *,
        role: str,
        full_name: str,
        email: str,
        phone: str,
        password: str,
        city: str | None = None,
    ) -> User:
        if role not in (UserRole_CUSTOMER, UserRole_WORKER):
            raise AppException("Please choose customer or worker when registering.", code=ErrorCode.VALIDATION_ERROR)
        if self.users.email_exists(email):
            raise ConflictException("An account with this email already exists.")
        if self.users.phone_exists(phone):
            raise ConflictException("An account with this phone number already exists.")

        user = self.users.create(
            email=email.lower(),
            phone=phone,
            password_hash=hash_password(password),
            full_name=full_name,
            role=role,
            city=city,
            is_email_verified=False,
        )
        self.users.create_customer_profile(user.id)
        self.users.create_wallet(user.id)
        if role == UserRole_WORKER:
            self.users.create_worker_profile(user.id, city=city)

        self.issue_email_otp(user.email, OTP_PURPOSE_EMAIL_VERIFICATION)
        self.audit.log(user_id=user.id, action="user_registered", entity_type="user", entity_id=user.id)
        logger.info("user_registered user=%s role=%s", user.id, role)
        return user

    # ---------- user resolution ----------

    def get_user_by_identifier(self, identifier: str) -> User | None:
        """Look up a user by email address or phone number (with or without '+')."""
        identifier = (identifier or "").strip()
        if "@" in identifier:
            return self.users.get_by_email(identifier)
        return self.users.get_by_phone(identifier)

    # ---------- one-time passcodes ----------

    @staticmethod
    def _hash_code(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def issue_email_otp(self, email: str, purpose: str) -> None:
        email = email.lower()
        last = (
            self.db.query(EmailOtp)
            .filter(EmailOtp.email == email, EmailOtp.purpose == purpose)
            .order_by(EmailOtp.created_at.desc())
            .first()
        )
        if last is not None:
            created = last.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - created).total_seconds()
            if elapsed < settings.otp_resend_cooldown_seconds:
                raise RateLimitException(
                    f"Please wait {settings.otp_resend_cooldown_seconds - int(elapsed) + 1}s before requesting a new code."
                )

        code = f"{secrets.randbelow(1_000_000):06d}"
        otp = EmailOtp(
            email=email,
            code_hash=self._hash_code(code),
            purpose=purpose,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expire_minutes),
        )
        self.db.add(otp)
        self.db.flush()
        self._deliver_otp(email, code)

    def _deliver_otp(self, email: str, code: str) -> None:
        if settings.email_provider.lower() != "smtp" or not smtp_configured():
            raise AppException(
                "Email delivery is not configured. Set SMTP_USER and SMTP_PASSWORD before registering.",
                code=ErrorCode.INTERNAL_ERROR,
                status_code=503,
            )

        subject = f"{code} is your TaskFlex verification code"
        text = (
            f"Hi,\n\nYour TaskFlex verification code is {code}.\n"
            f"It expires in {settings.otp_expire_minutes} minutes.\n\n"
            "If you did not request this, you can ignore this email."
        )
        html = f"""
        <div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;padding:24px">
          <h2 style="margin:0 0 8px;color:#1d4ed8">TaskFlex</h2>
          <p style="color:#334155">Your verification code is:</p>
          <p style="font-size:32px;font-weight:800;letter-spacing:8px;margin:16px 0;color:#0f172a">{code}</p>
          <p style="color:#64748b;font-size:13px">This code expires in {settings.otp_expire_minutes} minutes.
          If you did not request it, you can ignore this email.</p>
        </div>
        """
        try:
            send_email_smtp(email, subject, html, text)
        except Exception:
            logger.exception("otp_email_failed email=%s", email)
            raise AppException(
                "We could not send the verification email right now. Please try again shortly.",
                code=ErrorCode.INTERNAL_ERROR,
                status_code=502,
            )

    def verify_email_otp(self, identifier: str, code: str) -> User:
        user = self.get_user_by_identifier(identifier)
        if user is None:
            raise AppException("Invalid or expired code.", code=ErrorCode.VALIDATION_ERROR)
        if user.is_email_verified:
            raise AppException("This email is already verified. Please sign in.", code=ErrorCode.VALIDATION_ERROR)

        otp = (
            self.db.query(EmailOtp)
            .filter(
                EmailOtp.email == user.email.lower(),
                EmailOtp.purpose == OTP_PURPOSE_EMAIL_VERIFICATION,
                EmailOtp.consumed_at.is_(None),
            )
            .order_by(EmailOtp.created_at.desc())
            .first()
        )
        if otp is None:
            raise AppException("No active code found. Please request a new one.", code=ErrorCode.VALIDATION_ERROR)

        expires = otp.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise AppException("This code has expired. Please request a new one.", code=ErrorCode.VALIDATION_ERROR)
        if otp.attempts >= settings.otp_max_attempts:
            raise AppException("Too many wrong attempts. Please request a new code.", code=ErrorCode.VALIDATION_ERROR)

        if not hmac.compare_digest(otp.code_hash, self._hash_code(code.strip())):
            otp.attempts += 1
            # The request handler rolls the session back when we raise below;
            # commit first so the wrong-attempt tally actually sticks.
            self.db.commit()
            remaining = settings.otp_max_attempts - otp.attempts
            hint = f" {remaining} attempt(s) left." if remaining > 0 else " Please request a new code."
            raise AppException("That code is incorrect." + hint, code=ErrorCode.VALIDATION_ERROR)

        otp.consumed_at = datetime.now(timezone.utc)
        user.is_email_verified = True
        user.email_verification_token = None
        self.db.flush()
        self.audit.log(user_id=user.id, action="email_verified_otp", entity_type="user", entity_id=user.id)
        logger.info("email_verified_via_otp user=%s", user.id)
        return user

    def resend_email_otp(self, identifier: str) -> None:
        user = self.get_user_by_identifier(identifier)
        if user is None or user.is_email_verified:
            return
        self.issue_email_otp(user.email, OTP_PURPOSE_EMAIL_VERIFICATION)

    # ---------- login / tokens ----------

    def login(self, identifier: str, password: str) -> tuple[User, dict]:
        user = self.get_user_by_identifier(identifier)
        if user is not None and user.password_hash is None:
            # Google-only account: there is no password to check.
            raise AppException(
                "This account uses Google sign-in. Please use the 'Sign in with Google' button.",
                code=ErrorCode.VALIDATION_ERROR,
            )
        if user is None or not verify_password(password, user.password_hash):
            # Log only the identifier kind, never the identifier itself.
            self.audit.log(action="login_failed", metadata_json={"identifier_kind": "email" if "@" in identifier else "phone"})
            raise AppException("Incorrect email/phone or password.", code=ErrorCode.INVALID_CREDENTIALS, status_code=401)
        if not user.is_active:
            raise AppException("This account has been disabled.", code=ErrorCode.ACCOUNT_DISABLED, status_code=403)
        if not user.is_email_verified:
            raise AppException(
                "Please verify your email first. We sent you a 6-digit code.",
                code=ErrorCode.EMAIL_NOT_VERIFIED,
                status_code=403,
            )

        self.users.touch_last_login(user)
        self.audit.log(user_id=user.id, action="login_success", entity_type="user", entity_id=user.id)
        tokens = self._token_pair(user)
        logger.info("login_success user=%s", user.id)
        return user, tokens

    def refresh(self, refresh_token: str) -> tuple[User, dict]:
        try:
            payload = decode_token(refresh_token, expected_type="refresh")
        except pyjwt.ExpiredSignatureError as exc:
            raise UnauthorizedException("Session expired. Please sign in again.") from exc
        except pyjwt.InvalidTokenError as exc:
            raise UnauthorizedException("Invalid refresh token.") from exc

        user = self.users.get_by_id(payload["sub"])
        if user is None or not user.is_active:
            raise UnauthorizedException("Account is no longer active.")
        return user, self._token_pair(user)

    @staticmethod
    def _token_pair(user: User) -> dict:
        return {
            "access_token": create_access_token(user.id, user.role),
            "refresh_token": create_refresh_token(user.id),
            "token_type": "bearer",
            "expires_in": settings.access_token_expire_minutes * 60,
        }

    # ---------- google sign-in ----------

    def google_login(self, credential: str, role: str = "CUSTOMER") -> tuple[User, dict, bool]:
        """Verify a Google id_token, then sign in or auto-create the account.

        Accounts are matched by email (Google guarantees it is verified);
        first-time users get customer profile + wallet created automatically.
        Returns (user, tokens, created).
        """
        if role not in (UserRole_CUSTOMER, UserRole_WORKER):
            raise AppException("Please choose customer or worker.", code=ErrorCode.VALIDATION_ERROR)

        claims = verify_google_id_token(credential)
        email = str(claims["email"]).lower()
        full_name = str(claims.get("name") or "").strip() or email.split("@")[0]
        picture = claims.get("picture") or None

        user = self.users.get_by_email(email)
        created = user is None
        if created:
            user = self.users.create(
                email=email,
                phone=None,
                password_hash=None,
                full_name=full_name,
                role=role,
                avatar_url=picture,
                is_email_verified=True,
            )
            self.users.create_customer_profile(user.id)
            self.users.create_wallet(user.id)
            if role == UserRole_WORKER:
                self.users.create_worker_profile(user.id)
            self.audit.log(user_id=user.id, action="user_registered_google", entity_type="user", entity_id=user.id)
            logger.info("user_registered_google user=%s role=%s", user.id, role)
        else:
            if not user.is_active:
                raise AppException("This account has been disabled.", code=ErrorCode.ACCOUNT_DISABLED, status_code=403)
            # Google proved control of this email; trust it and adopt the picture.
            if not user.is_email_verified:
                user.is_email_verified = True
            if picture and not user.avatar_url:
                user.avatar_url = picture
            self.db.flush()

        self.users.touch_last_login(user)
        self.audit.log(
            user_id=user.id,
            action="login_google",
            entity_type="user",
            entity_id=user.id,
            metadata_json={"new_account": created},
        )
        tokens = self._token_pair(user)
        logger.info("login_google user=%s new_account=%s", user.id, created)
        return user, tokens, created

    # ---------- password reset ----------

    def forgot_password(self, email: str) -> str | None:
        """Returns the raw reset token in non-production so dev/demo flows work;
        in production this token would only ever be emailed."""
        user = self.users.get_by_email(email)
        if user is None:
            return None  # do not reveal account existence
        token = generate_random_token(24)
        user.password_reset_token = token
        user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
        self.db.flush()
        self.audit.log(user_id=user.id, action="password_reset_requested", entity_type="user", entity_id=user.id)
        if not settings.is_production:
            return token
        return None

    def reset_password(self, token: str, new_password: str) -> User:
        user = self.db.query(User).filter(User.password_reset_token == token).one_or_none()
        if user is None or user.password_reset_expires is None:
            raise AppException("This reset link is invalid.", code=ErrorCode.VALIDATION_ERROR)
        expires = user.password_reset_expires
        # SQLite round-trips datetimes as naive UTC; treat naive values as UTC.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise AppException("This reset link has expired. Please request a new one.",
                               code=ErrorCode.VALIDATION_ERROR)
        user.password_hash = hash_password(new_password)
        user.password_reset_token = None
        user.password_reset_expires = None
        self.db.flush()
        self.audit.log(user_id=user.id, action="password_reset_completed", entity_type="user", entity_id=user.id)
        return user

    # ---------- email verification ----------


UserRole_CUSTOMER = "CUSTOMER"
UserRole_WORKER = "WORKER"
