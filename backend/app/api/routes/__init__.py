"""Aggregated v1 API router. Every route module plugs in exactly once here."""

from fastapi import APIRouter

from app.api.routes import (
    admin,
    auth,
    bids,
    conversations,
    disputes,
    execution,
    location,
    notifications,
    payments,
    public,
    ratings,
    share,
    tasks,
    uploads,
    users,
    wallet,
    workers,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(tasks.router)
api_router.include_router(bids.router)
api_router.include_router(wallet.router)
api_router.include_router(share.router)
api_router.include_router(execution.router)
api_router.include_router(workers.router)
api_router.include_router(ratings.router)
api_router.include_router(notifications.router)
api_router.include_router(conversations.router)
api_router.include_router(payments.router)
api_router.include_router(disputes.router)
api_router.include_router(uploads.router)
api_router.include_router(location.router)
api_router.include_router(admin.router)
api_router.include_router(public.router)
