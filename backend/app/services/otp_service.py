"""Task handshake OTPs — start and completion codes.

Codes are 4 digits, stored only as an HMAC-SHA256 digest (peppered via
settings.otp_pepper, bound to the task id AND the handshake purpose). A
plaintext display copy stays on the task row and is exposed only to the
task's customer, who reads it out to the worker. Wrong attempts are counted
per task; after settings.otp_max_attempts the handshake locks for
settings.otp_lock_minutes. Redis mirrors the counter at
rate:otp:task:{task_id} for fast rejection; the database columns are the
durable source of truth."""

import hmac
import re
import secrets
from datetime import timedelta
from hashlib import sha256

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import OtpInvalidException, OtpLockedException
from app.core.logging import get_logger
from app.core.redis_sync import delete_key, incr_with_ttl
from app.core.timeutils import as_aware, utcnow
from app.models import Task

logger = get_logger("taskflex.otp")

PURPOSE_START = "start"
PURPOSE_COMPLETION = "completion"
PURPOSE_RETURN = "return"

_CODE_RE = re.compile(r"^\d{4}$")


def generate_code() -> str:
    return f"{secrets.randbelow(10000):04d}"


def hash_code(task_id: str, purpose: str, code: str) -> str:
    message = f"{task_id}:{purpose}:{code}".encode()
    return hmac.new(settings.otp_pepper.encode(), message, sha256).hexdigest()


def lock_key(task_id: str, purpose: str) -> str:
    base = f"rate:otp:task:{task_id}"
    return base if purpose == PURPOSE_START else f"{base}:{purpose}"


def _fields(task: Task, purpose: str) -> tuple:
    if purpose == PURPOSE_START:
        return ("start_otp_hash", "start_otp_display", "start_otp_attempts", "start_otp_locked_at")
    if purpose == PURPOSE_RETURN:
        return ("return_otp_hash", "return_otp_display", "return_otp_attempts", "return_otp_locked_at")
    return ("completion_otp_hash", "completion_otp_display", "completion_otp_attempts", "completion_otp_locked_at")


def issue_otp(task: Task, purpose: str) -> None:
    """Generate a fresh code for the purpose: new digest, plaintext display
    copy for the customer, attempts/lock reset."""
    code = generate_code()
    hash_attr, display_attr, attempts_attr, locked_attr = _fields(task, purpose)
    setattr(task, hash_attr, hash_code(task.id, purpose, code))
    setattr(task, display_attr, code)
    setattr(task, attempts_attr, 0)
    setattr(task, locked_attr, None)
    delete_key(lock_key(task.id, purpose))
    logger.info("otp_issued task=%s purpose=%s", task.id, purpose)


def verify_otp(db: Session, task: Task, purpose: str, code: str) -> None:
    """Verify `code` against the stored digest. Raises OtpInvalidException on a
    wrong code (counting the attempt) and OtpLockedException once locked; an
    expired lock window resets the counter and allows a fresh set of attempts."""
    hash_attr, _display, attempts_attr, locked_attr = _fields(task, purpose)
    stored = getattr(task, hash_attr)
    if not stored:
        raise OtpInvalidException("No verification code is active for this task.")

    lock_window = timedelta(minutes=settings.otp_lock_minutes)
    now = utcnow()
    attempts = getattr(task, attempts_attr) or 0

    locked_at = getattr(task, locked_attr)
    if locked_at is not None:
        elapsed = now - as_aware(locked_at)
        if elapsed < lock_window:
            remaining_min = int((lock_window - elapsed).total_seconds() // 60) + 1
            raise OtpLockedException(
                f"Too many wrong attempts. Try again in {remaining_min} minute(s).",
                details={"retry_after_minutes": remaining_min},
            )
        attempts = 0
        setattr(task, locked_attr, None)

    ok = bool(_CODE_RE.match(code or "")) and hmac.compare_digest(
        hash_code(task.id, purpose, code), stored
    )
    if ok:
        setattr(task, attempts_attr, 0)
        setattr(task, locked_attr, None)
        delete_key(lock_key(task.id, purpose))
        db.flush()
        return

    attempts += 1
    setattr(task, attempts_attr, attempts)
    ttl = int(lock_window.total_seconds())
    if attempts >= settings.otp_max_attempts:
        setattr(task, locked_attr, now)
        incr_with_ttl(lock_key(task.id, purpose), ttl)
        db.flush()
        logger.warning("otp_locked task=%s purpose=%s attempts=%d", task.id, purpose, attempts)
        raise OtpLockedException(
            f"Too many wrong attempts. The code is locked for {settings.otp_lock_minutes} minute(s).",
            details={"retry_after_minutes": settings.otp_lock_minutes},
        )
    incr_with_ttl(lock_key(task.id, purpose), ttl)
    db.flush()
    remaining = settings.otp_max_attempts - attempts
    raise OtpInvalidException(
        f"Incorrect code. {remaining} attempt(s) left before the handshake locks.",
        details={"attempts_remaining": remaining},
    )
