from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DashboardMetrics(BaseModel):
    total_users: int
    total_customers: int
    total_workers: int
    active_workers: int
    verified_workers: int
    total_tasks: int
    active_tasks: int
    completed_tasks: int
    cancelled_tasks: int
    disputed_tasks: int
    completion_rate: float
    cancellation_rate: float
    total_revenue: float
    platform_commission: float
    worker_payouts: float
    average_task_value: float
    average_rating: float
    open_disputes: int
    pending_verifications: int


class TimeSeriesPoint(BaseModel):
    date: str
    value: float | int


class AnalyticsResponse(BaseModel):
    dau: list[TimeSeriesPoint]
    mau: list[TimeSeriesPoint]
    tasks_created: list[TimeSeriesPoint]
    tasks_completed: list[TimeSeriesPoint]
    task_type_distribution: list[dict]
    status_distribution: list[dict]
    metrics: DashboardMetrics


class SystemSettingOut(BaseModel):
    key: str
    value: str
    value_type: str
    description: str | None = None


class SystemSettingsUpdate(BaseModel):
    settings: dict[str, str] = Field(
        description="Map of setting key -> new value", examples=[{"platform_commission_percent": "12.5"}]
    )


class SosResolveRequest(BaseModel):
    note: str | None = Field(None, max_length=1000, description="What support did to resolve the alert.")


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    ip_address: str | None = None
    metadata_json: dict = Field(default_factory=dict, validation_alias="metadata_json")
    created_at: datetime
