"""Service layer: business logic lives here, never in route handlers.

Matching (rank → offer dispatch) is orchestrated by TaskService._dispatch_offers,
which wraps MatchingEngine directly — there is deliberately no separate
matching_service module.
"""
from app.services.admin_service import AdminService
from app.services.affinity_service import AffinityService
from app.services.analytics_service import AnalyticsService
from app.services.auth_service import AuthService
from app.services.bidding_service import BiddingService
from app.services.dispute_service import DisputeService
from app.services.execution_service import ExecutionService
from app.services.gamification_service import GamificationService
from app.services.location_service import get_geocoder, map_embed_url
from app.services.messaging_service import MessagingService
from app.services.payment_service import PaymentService
from app.services.rating_service import RatingService
from app.services.ridecheck_monitor import RideCheckMonitor
from app.services.safety_service import SafetyService
from app.services.share_service import ShareService
from app.services.task_service import TaskService
from app.services.upload_service import UploadService
from app.services.wallet_service import WalletService
from app.services.worker_service import WorkerService

__all__ = [
    "AdminService",
    "AffinityService",
    "AnalyticsService",
    "AuthService",
    "BiddingService",
    "DisputeService",
    "ExecutionService",
    "GamificationService",
    "MessagingService",
    "PaymentService",
    "RatingService",
    "RideCheckMonitor",
    "SafetyService",
    "ShareService",
    "TaskService",
    "UploadService",
    "WalletService",
    "WorkerService",
    "get_geocoder",
    "map_embed_url",
]
