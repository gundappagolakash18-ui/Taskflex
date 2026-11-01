"""Telemetry ingestion and tracking snapshots.

Workers push GPS positions over WebSocket; this module validates them,
derives route progress (remaining distance, ETA, heading) from the OSRM
route, and publishes updates to everyone watching the task."""

import math
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import Task, User
from app.models.enums import TaskStatus
from app.repositories import UserRepository
from app.tracking import fetch_route, hub, snap_point, snap_trace
from app.tracking.geo import RouteState, bearing_deg, eta_minutes, project_onto_route, remaining_km

logger = get_logger("tracking.service")

TRACKING_STATUSES = (
    TaskStatus.ACCEPTED,
    TaskStatus.WORKER_ON_THE_WAY,
    TaskStatus.ARRIVED_AT_LOCATION,
    TaskStatus.IN_PROGRESS,
    TaskStatus.COMPLETION_REQUESTED,
    TaskStatus.EMERGENCY_ALERT,
)

_last_ping: dict[tuple[str, str], float] = {}
_routes: dict[str, RouteState] = {}


def tracked_route(task_id: str) -> RouteState | None:
    return _routes.get(task_id)


def reset_task_route(task_id: str) -> None:
    _routes.pop(task_id, None)


def tracking_destination(task: Task) -> tuple[float, float]:
    """Current navigation target. A round-trip errand navigates to the errand
    destination first, then back to the pickup origin once work is underway."""
    if task.is_round_trip and task.status in (
        TaskStatus.IN_PROGRESS.value,
        TaskStatus.COMPLETION_REQUESTED.value,
    ):
        origin = sorted(
            (loc for loc in (task.locations or []) if loc.label in ("pickup", "return")),
            key=lambda loc: loc.sequence,
        )
        if origin:
            return float(origin[0].latitude), float(origin[0].longitude)
    return float(task.latitude), float(task.longitude)


async def route_for_task(
    task_id: str, origin: tuple[float, float], destination: tuple[float, float], *, force: bool = False
) -> RouteState:
    cached = None if force else _routes.get(task_id)
    if cached is not None:
        return cached
    route = await fetch_route(origin, destination)
    _routes[task_id] = route
    return route


def _is_throttled(worker_id: str, task_id: str) -> bool:
    key = (worker_id, task_id)
    last = _last_ping.get(key)
    now = time.monotonic()
    if last is not None and now - last < settings.tracking_min_interval_seconds:
        return True
    _last_ping[key] = now
    if len(_last_ping) > 1024:
        # Drop the oldest half; this is a throttle, not a source of truth.
        for k, _ in sorted(_last_ping.items(), key=lambda kv: kv[1])[:512]:
            _last_ping.pop(k, None)
    return False


async def _snap_position(task_id: str, raw: tuple[float, float]) -> tuple[tuple[float, float], bool]:
    """Map-match the newest fix onto the road network, using the previous fix
    as trace context for /match; a lone fix falls back to /nearest. Returns
    the fix to broadcast and whether OSRM actually matched it."""
    recent = await hub.history(task_id, limit=2)
    previous = [
        (float(point["latitude"]), float(point["longitude"]))
        for point in recent
        if point.get("latitude") is not None and point.get("longitude") is not None
    ]
    if previous:
        matched = await snap_trace([previous[-1], raw])
        if matched and matched[-1] is not None:
            return matched[-1], True
    nearest = await snap_point(raw)
    if nearest is not None:
        return nearest, True
    return raw, False


async def ingest_worker_position(
    db: Session,
    worker: User,
    task_id: str,
    latitude: float,
    longitude: float,
    heading: float | None = None,
    speed_kmph: float | None = None,
) -> dict | None:
    """Validate and broadcast one worker position. Returns the published
    payload, or None when the ping is rejected (not assigned, wrong state,
    throttled, or a malformed position)."""
    task = db.get(Task, task_id)
    if task is None or task.assigned_worker_id != worker.id:
        return None
    if TaskStatus(task.status) not in TRACKING_STATUSES:
        _routes.pop(task_id, None)
        return None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None
    if _is_throttled(worker.id, task_id):
        return None

    snapped, snapped_ok = await _snap_position(task_id, (latitude, longitude))

    destination = tracking_destination(task)
    route = await route_for_task(task_id, snapped, destination)
    projection = project_onto_route(route, snapped[0], snapped[1])

    # Far off the planned road: rebuild the route from where the worker is.
    if projection.deviation_km * 1000.0 > settings.tracking_offroute_deviation_m:
        route = await route_for_task(task_id, snapped, destination, force=True)
        projection = project_onto_route(route, snapped[0], snapped[1])

    left = remaining_km(route, projection.along_km)

    if heading is None or not math.isfinite(heading):
        coords = route.coordinates
        idx = min(projection.segment_index, len(coords) - 2)
        heading = bearing_deg(coords[idx][0], coords[idx][1], coords[idx + 1][0], coords[idx + 1][1])

    payload = {
        "task_id": task_id,
        "status": task.status,
        "latitude": round(snapped[0], 6),
        "longitude": round(snapped[1], 6),
        "snapped": snapped_ok,
        "heading": round(float(heading) % 360.0, 1),
        "speed_kmph": round(float(speed_kmph), 1) if speed_kmph is not None and math.isfinite(speed_kmph) and speed_kmph >= 0 else None,
        "remaining_km": round(left, 2),
        "eta_minutes": eta_minutes(left, float(speed_kmph or 0.0), route.duration_min, route, projection.along_km),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        from app.services.ridecheck_monitor import RideCheckMonitor

        RideCheckMonitor(db).evaluate(
            task,
            worker,
            latitude=snapped[0],
            longitude=snapped[1],
            deviation_m=projection.deviation_km * 1000.0,
            remaining_km=left,
            speed_kmph=payload["speed_kmph"],
        )
    except Exception:
        # Safety analysis must never interrupt telemetry delivery.
        logger.exception("ridecheck_evaluation_failed task=%s", task_id)

    await hub.publish(task_id, payload)
    return payload


async def tracking_snapshot(db: Session, task: Task) -> dict:
    """Everything the tracking screen needs on load: route polyline, worker
    summary, destination, and the newest known position (if any)."""
    destination_coords = tracking_destination(task)
    destination = {"latitude": destination_coords[0], "longitude": destination_coords[1]}
    worker_profile = UserRepository(db).get_worker_profile(task.assigned_worker_id) if task.assigned_worker_id else None

    latest = await hub.latest(task.id)
    route_state = _routes.get(task.id)

    origin: tuple[float, float] | None = None
    if latest:
        origin = (latest["latitude"], latest["longitude"])
    elif worker_profile and worker_profile.latitude is not None and worker_profile.longitude is not None:
        origin = (float(worker_profile.latitude), float(worker_profile.longitude))

    route_payload = None
    eta = None
    if origin and (abs(origin[0] - destination["latitude"]) > 1e-6 or abs(origin[1] - destination["longitude"]) > 1e-6):
        route = await route_for_task(task.id, origin, (destination["latitude"], destination["longitude"]))
        route_state = route
        projection = project_onto_route(route, origin[0], origin[1])
        left = remaining_km(route, projection.along_km)
        route_payload = {
            "coordinates": [[lat, lng] for lat, lng in route.coordinates],
            "distance_km": route.distance_km,
            "duration_min": route.duration_min,
        }
        if latest:
            eta = latest.get("eta_minutes")
        else:
            eta = eta_minutes(left, 0.0, route.duration_min, route, projection.along_km)

    return {
        "task_id": task.id,
        "status": task.status,
        "tracking_active": TaskStatus(task.status) in TRACKING_STATUSES,
        "destination": destination,
        "route": route_payload,
        "latest": latest,
        "eta_minutes": eta,
        "remaining_km": latest.get("remaining_km") if latest else None,
        "worker": {
            "id": task.assigned_worker_id,
            "full_name": task.assigned_worker.full_name if task.assigned_worker else None,
            "avatar_url": task.assigned_worker.avatar_url if task.assigned_worker else None,
        },
    }
