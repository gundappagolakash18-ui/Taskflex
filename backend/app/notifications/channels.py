"""Notification delivery channels.

InAppChannel persists to the notifications table (always on).
Email is delivered through the configured SMTP account when
EMAIL_PROVIDER=smtp, or logged when EMAIL_PROVIDER=log. SMS remains
log-backed until a provider is configured.
"""

from abc import ABC, abstractmethod
import html as html_lib
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("notify")


class OutgoingNotification:
    def __init__(self, user_id: str, type: str, title: str, body: str,
                 data: dict | None = None, link: str | None = None):
        self.user_id = user_id
        self.type = type
        self.title = title
        self.body = body
        self.data = data or {}
        self.link = link


class NotificationChannel(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, notification: OutgoingNotification) -> bool:
        """Deliver a notification. Return False to signal non-fatal failure."""


class InAppChannel(NotificationChannel):
    name = "in_app"

    def send(self, notification: OutgoingNotification, db: Session | None = None) -> bool:
        from app.db.session import SessionLocal
        from app.repositories import NotificationRepository

        fields = dict(
            user_id=notification.user_id,
            type=notification.type,
            title=notification.title,
            body=notification.body,
            data=notification.data,
            link=notification.link,
        )
        if db is not None:
            # Join the caller's transaction: avoids a second SQLite writer and
            # commits the notification atomically with the event it describes.
            NotificationRepository(db).create(**fields)
            return True

        owned = SessionLocal()
        try:
            NotificationRepository(owned).create(**fields)
            owned.commit()
            return True
        except Exception:
            owned.rollback()
            raise
        finally:
            owned.close()


class LogEmailChannel(NotificationChannel):
    """Development stand-in for a real email provider."""

    name = "log_email"

    def send(self, notification: OutgoingNotification) -> bool:
        logger.info("EMAIL to_user=%s subject=%r body=%r", notification.user_id, notification.title, notification.body)
        return True


class LogSMSChannel(NotificationChannel):
    """Development stand-in for a real SMS provider."""

    name = "log_sms"

    def send(self, notification: OutgoingNotification) -> bool:
        logger.info("SMS to_user=%s text=%r", notification.user_id, notification.title)
        return True


class SmtpEmailChannel(NotificationChannel):
    """Delivers notification email to the user's registered address."""

    name = "smtp_email"

    def send(self, notification: OutgoingNotification) -> bool:
        if not smtp_configured():
            logger.warning("email_notification_skipped smtp_not_configured")
            return False

        from app.db.session import SessionLocal
        from app.models import User

        owned = SessionLocal()
        try:
            user = owned.get(User, notification.user_id)
            to_address = user.email if user is not None else None
        finally:
            owned.close()
        if not to_address:
            return False

        link = notification.link or ""
        if link.startswith("/"):
            base = (settings.cors_origins.split(",")[0] or "").strip()
            link = f"{base}{link}" if base else link

        safe_title = html_lib.escape(notification.title)
        safe_body = html_lib.escape(notification.body)
        html = f"<h2>{safe_title}</h2><p>{safe_body}</p>"
        text = notification.body
        if link:
            html += f'<p><a href="{html_lib.escape(link)}">Open in TaskFlex</a></p>'
            text += f"\n\n{link}"
        return send_email_smtp(
            to_address,
            f"TaskFlex: {notification.title}",
            html,
            text,
        )


class NoopChannel(NotificationChannel):
    name = "noop"

    def send(self, notification: OutgoingNotification) -> bool:
        return True


def get_email_channel() -> NotificationChannel:
    if settings.email_provider == "smtp":
        return SmtpEmailChannel()
    if settings.email_provider == "log":
        return LogEmailChannel()
    return NoopChannel()


def get_sms_channel() -> NotificationChannel:
    return LogSMSChannel() if settings.sms_provider == "log" else NoopChannel()


def smtp_configured() -> bool:
    return bool(settings.smtp_user and settings.smtp_password)


def send_email_smtp(to: str, subject: str, html: str, text: str) -> bool:
    """Send one email via SMTP (Gmail by default). Caller handles failures."""
    from_addr = settings.email_from or settings.smtp_user
    msg = EmailMessage()
    msg["From"] = formataddr(("TaskFlex", from_addr))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
    logger.info("email_sent via_smtp to=%s subject=%r", to, subject)
    return True
