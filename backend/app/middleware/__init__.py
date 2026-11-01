import time
from collections import defaultdict, deque

import jwt as pyjwt
from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import settings
from app.core.exceptions import AppException, ErrorCode
from app.core.logging import get_logger

logger = get_logger("http")


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"success": False, "error": error}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith(f"{settings.api_v1_prefix}") or request.url.path == "/health":
            started = time.perf_counter()
            response = await call_next(request)
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "%s %s -> %s (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )
            return response
        return await call_next(request)


class SecureHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "geolocation=(self), camera=(), microphone=()"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding-window rate limiter for auth endpoints.

    Suitable for single-process deployments; swap for Redis-backed limiting at scale.
    """

    WINDOW_SECONDS = 60
    MAX_REQUESTS = 20

    def __init__(self, app, protected_prefixes: tuple[str, ...] = ("/api/v1/auth",)):
        super().__init__(app)
        self.protected_prefixes = protected_prefixes
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if any(request.url.path.startswith(p) for p in self.protected_prefixes) and request.method == "POST":
            client_ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            window = self._hits[client_ip]
            while window and now - window[0] > self.WINDOW_SECONDS:
                window.popleft()
            if len(window) >= self.MAX_REQUESTS:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content=error_body(ErrorCode.RATE_LIMITED, "Too many attempts. Try again in a minute."),
                )
            window.append(now)
        return await call_next(request)


def install_exception_handlers(app) -> None:
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        logger.info("app_error code=%s path=%s: %s", exc.code, request.url.path, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code.value if hasattr(exc.code, "value") else str(exc.code), exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = {
            ".".join(str(loc) for loc in err["loc"][1:]): err["msg"]
            for err in exc.errors()
        }
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_body(ErrorCode.VALIDATION_ERROR, "Request validation failed.", details),
        )

    @app.exception_handler(pyjwt.PyJWTError)
    async def jwt_exception_handler(request: Request, exc: pyjwt.PyJWTError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=error_body(ErrorCode.UNAUTHORIZED, "Invalid or expired session."),
        )

    @app.exception_handler(SQLAlchemyError)
    async def db_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("database_error path=%s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(ErrorCode.INTERNAL_ERROR, "A database error occurred."),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error path=%s", request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(ErrorCode.INTERNAL_ERROR, "Something went wrong. Please try again."),
        )
