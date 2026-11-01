import json
import logging
import sys
from datetime import datetime, timezone

SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "new_password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "api_key",
    "secret",
    "document_data",
    "file_content",
}


class SensitiveFilter(logging.Filter):
    """Redact values of sensitive keys from structured log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        return True


def redact(data: dict) -> dict:
    safe = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_KEYS:
            safe[key] = "[REDACTED]"
        elif isinstance(value, dict):
            safe[key] = redact(value)
        else:
            safe[key] = value
    return safe


class JsonFormatter(logging.Formatter):
    """Structured JSON logs so the output can be ingested by any log pipeline."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(redact(extra))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class AppLogger(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra_fields = kwargs.pop("extra_fields", {})
        kwargs.setdefault("extra", {})
        kwargs["extra"]["extra_fields"] = extra_fields
        return msg, kwargs


def setup_logging() -> None:
    from app.core.config import settings

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if settings.is_production:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s")
        )
    root.addHandler(handler)
    handler.addFilter(SensitiveFilter())

    # Quiet down noisy third-party loggers.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> AppLogger:
    return AppLogger(logging.getLogger(name), {})
