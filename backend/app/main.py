import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.middleware import (
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    SecureHeadersMiddleware,
    install_exception_handlers,
)

setup_logging()
logger = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s (%s) — %s", settings.app_name, settings.environment, settings.app_tagline)
    if settings.is_production:
        if settings.jwt_secret.startswith("dev-") or settings.jwt_refresh_secret.startswith("dev-"):
            raise RuntimeError("Refusing to start in production with default JWT secrets. Set JWT_SECRET and JWT_REFRESH_SECRET.")
        if settings.otp_pepper.startswith("dev-"):
            raise RuntimeError("Refusing to start in production with the default OTP pepper. Set OTP_PEPPER.")
        if not (settings.smtp_user and settings.smtp_password):
            raise RuntimeError("Refusing to start in production without SMTP. Email verification is mandatory for signup — set SMTP_USER/SMTP_PASSWORD.")
    if settings.seed_on_start:
        from app.db.seed_runner import seed_if_empty

        seed_if_empty()

    from app.tracking.hub import hub
    from app.websocket.manager import capture_main_loop
    from app.services.messaging_service import chat_close_sweeper
    from app.services.reserve_watchdog import run_operations_watchdog

    capture_main_loop()
    await hub.start()
    chat_stop = asyncio.Event()
    chat_sweeper = asyncio.create_task(chat_close_sweeper(chat_stop))
    logger.info("chat_sweeper started (grace=%dh)", settings.chat_close_after_hours)
    ops_stop = asyncio.Event()
    ops_watchdog = asyncio.create_task(run_operations_watchdog(ops_stop))
    yield
    chat_stop.set()
    ops_stop.set()
    for task in (chat_sweeper, ops_watchdog):
        try:
            await task
        except asyncio.CancelledError:
            pass
    await hub.close()
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    expose_docs = not settings.is_production
    app = FastAPI(
        title=f"{settings.app_name} API",
        description=(
            "AI-powered on-demand marketplace for real-world errands. "
            "Customers describe tasks in natural language, an AI service structures them, "
            "and a matching engine assigns nearby gig workers."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecureHeadersMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RateLimitMiddleware)
    install_exception_handlers(app)

    from app.api.routes import api_router

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    from app.api.routes.websocket import chat_ws_router, ws_router

    app.include_router(ws_router)
    app.include_router(chat_ws_router)
    # Convenience alias for deployments that only route /api/* to the backend.
    app.include_router(chat_ws_router, prefix=settings.api_v1_prefix)

    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {"success": True, "data": {"status": "ok", "app": settings.app_name}}

    return app


app = create_app()
