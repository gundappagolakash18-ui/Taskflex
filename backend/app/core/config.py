from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "TASKFLEX"
    app_tagline: str = "Real-world tasks. Made simple."
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    frontend_origin: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Database
    database_url: str = "sqlite:///./taskflex.db"

    # Security
    jwt_secret: str = "dev-access-secret-do-not-use-in-production"
    jwt_refresh_secret: str = "dev-refresh-secret-do-not-use-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    # Google sign-in — OAuth 2.0 Web Client ID from Google Cloud Console
    google_client_id: str = ""

    # AI
    ai_provider: str = "mock"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Maps
    maps_provider: str = "osm"
    maps_api_key: str = ""

    # Live tracking
    osrm_base_url: str = "https://router.project-osrm.org"
    redis_url: str = ""  # empty -> in-process tracking broker (single instance)
    tracking_min_interval_seconds: float = 3.0
    tracking_offroute_deviation_m: float = 200.0
    tracking_route_cache_seconds: int = 300
    tracking_map_match_enabled: bool = True
    # The public OSRM demo rejects /match with radiuses above 30 m; a
    # self-hosted instance accepts larger values.
    tracking_snap_radius_m: int = 30
    tracking_history_points: int = 20

    # Payments
    payment_provider: str = "mock"
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # Business rules
    platform_commission_percent: float = 10.0
    default_worker_radius_km: float = 8.0
    offer_ttl_minutes: int = 15
    max_offers_per_task: int = 6

    # Notifications
    email_provider: str = "log"  # "log" | "smtp"
    sms_provider: str = "log"

    # Email (Gmail SMTP) — app password, never the account password
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""  # falls back to smtp_user when empty

    # One-time passcodes
    otp_expire_minutes: int = 10
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60

    # Task handshake OTPs (start / completion) — pepper for the HMAC digest
    otp_pepper: str = "dev-otp-pepper-do-not-use-in-production"
    otp_lock_minutes: int = 15

    # Dynamic fare floor
    pricing_base_fare: float = 80.0
    pricing_per_km: float = 12.0
    pricing_per_wait_minute: float = 2.5
    pricing_recommended_factor: float = 1.15

    # Uploads
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 10
    allowed_upload_mime_types: str = "image/jpeg,image/png,image/webp,application/pdf"

    # Proof of execution
    proof_max_distance_m: int = 500
    proof_max_per_task: int = 10

    # Incidental expenses
    expense_max_amount: float = 20_000.0
    expense_max_per_task: int = 10

    # Task chat — read/write access closes this many hours after the task closes
    chat_close_after_hours: int = 24
    chat_sweep_interval_seconds: int = 300

    # Public live-tracking share links
    tracking_share_default_hours: int = 24
    tracking_share_max_hours: int = 72

    # Demo
    seed_on_start: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def google_oauth_enabled(self) -> bool:
        return bool(self.google_client_id.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_upload_mime_list(self) -> list[str]:
        return [m.strip() for m in self.allowed_upload_mime_types.split(",") if m.strip()]

    @field_validator("database_url")
    @classmethod
    def fix_postgres_driver(cls, v: str) -> str:
        # Accept postgres:// URLs (heroku style) and normalize to psycopg2 driver.
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+psycopg2://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg2://", 1)
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
