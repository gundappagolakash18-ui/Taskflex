"""OSRM road routing and map-matching with a small TTL cache.

Fetches driving routes from a self-hosted or public OSRM server and converts
them into RouteState objects. GPS fixes are snapped to the road network with
the match/nearest services so a noisy fix never puts the worker in a building
or a lake. When OSRM is unreachable both degrade gracefully (straight-line
route, raw fix) so tracking keeps working."""

import time
from collections import OrderedDict

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.tracking.geo import RouteState, build_route_state, haversine_km

logger = get_logger("tracking.routing")

_FALLBACK_SPEED_KMPH = 22.0  # conservative city traffic average

Point = tuple[float, float]

_cache: OrderedDict[tuple, tuple[float, RouteState]] = OrderedDict()
_snap_cache: OrderedDict[tuple, tuple[float, Point | None]] = OrderedDict()


def _cache_key(origin: Point, destination: Point) -> tuple:
    def q(v: float) -> float:
        return round(v, 4)  # ~11 m granularity

    return (q(origin[0]), q(origin[1]), q(destination[0]), q(destination[1]))


def _cached(key: tuple) -> RouteState | None:
    hit = _cache.get(key)
    if hit is None:
        return None
    ts, route = hit
    if time.monotonic() - ts > settings.tracking_route_cache_seconds:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return route


def _fallback_route(origin: Point, destination: Point) -> RouteState:
    distance = haversine_km(origin[0], origin[1], destination[0], destination[1])
    duration = distance / _FALLBACK_SPEED_KMPH * 60.0
    return build_route_state([origin, destination], duration)


def clear_route_cache() -> None:
    _cache.clear()
    _snap_cache.clear()


async def fetch_route(
    origin: tuple[float, float], destination: tuple[float, float]
) -> RouteState:
    """Driving route from OSRM as a (lat, lng) polyline.

    Raises nothing: network or parse failures return a straight-line fallback.
    """
    key = _cache_key(origin, destination)
    cached = _cached(key)
    if cached is not None:
        return cached

    url = (
        f"{settings.osrm_base_url}/route/v1/driving/"
        f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
        "?overview=full&geometries=geojson"
    )
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        route_obj = data["routes"][0]
        coords_raw = route_obj["geometry"]["coordinates"]  # GeoJSON: [lng, lat]
        coordinates = [(float(latlng[1]), float(latlng[0])) for latlng in coords_raw]
        if len(coordinates) < 2:
            raise ValueError("OSRM returned an empty geometry")
        route = build_route_state(coordinates, float(route_obj["duration"]) / 60.0)
    except Exception:
        logger.warning("osrm_route_failed origin=%s dest=%s; using straight-line fallback",
                       f"{origin[0]:.4f},{origin[1]:.4f}", f"{destination[0]:.4f},{destination[1]:.4f}")
        route = _fallback_route(origin, destination)

    _cache[key] = (time.monotonic(), route)
    if len(_cache) > 256:
        _cache.popitem(last=False)
    return route


# ---------- map-matching (snap GPS fixes to roads) ----------


def _snap_cache_key(point: Point, radius_m: int) -> tuple[float, float, float]:
    return (round(point[0], 5), round(point[1], 5), float(radius_m))


def _snap_cached(key: tuple) -> tuple[bool, Point | None]:
    hit = _snap_cache.get(key)
    if hit is None:
        return False, None
    ts, snapped = hit
    if time.monotonic() - ts > settings.tracking_route_cache_seconds:
        _snap_cache.pop(key, None)
        return False, None
    _snap_cache.move_to_end(key)
    return True, snapped


def _remember_snap(key: tuple, snapped: Point | None) -> None:
    _snap_cache[key] = (time.monotonic(), snapped)
    if len(_snap_cache) > 512:
        _snap_cache.popitem(last=False)


async def snap_point(point: Point, *, radius_m: int | None = None) -> Point | None:
    """Snap a single GPS fix to the nearest road via OSRM /nearest.

    Returns None when no road is within the radius or OSRM is unreachable —
    callers then keep the raw fix rather than dropping telemetry.
    """
    if not settings.tracking_map_match_enabled:
        return None
    radius = radius_m or settings.tracking_snap_radius_m
    key = _snap_cache_key(point, radius)
    hit, cached = _snap_cached(key)
    if hit:
        return cached

    url = (
        f"{settings.osrm_base_url}/nearest/v1/driving/{point[1]},{point[0]}"
        f"?number=1&radiuses={radius}"
    )
    snapped: Point | None = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        waypoint = data["waypoints"][0]
        distance = float(waypoint.get("distance", 0.0))
        if waypoint.get("location") and distance <= radius:
            snapped = (float(waypoint["location"][1]), float(waypoint["location"][0]))
    except Exception:
        logger.warning("osrm_nearest_failed point=%s", f"{point[0]:.5f},{point[1]:.5f}")

    _remember_snap(key, snapped)
    return snapped


async def snap_trace(points: list[Point], *, radius_m: int | None = None) -> list[Point | None] | None:
    """Map-match a short trace with OSRM /match (needs >= 2 fixes).

    Returns one entry per input point; an entry is None where OSRM could not
    match that fix. Returns None when the whole request fails so the caller
    can fall back to /nearest or the raw fix.
    """
    if len(points) < 2 or not settings.tracking_map_match_enabled:
        return None
    radius = radius_m or settings.tracking_snap_radius_m
    coords = ";".join(f"{p[1]},{p[0]}" for p in points)
    radiuses = ";".join(str(radius) for _ in points)
    url = (
        f"{settings.osrm_base_url}/match/v1/driving/{coords}"
        f"?geometries=geojson&overview=false&tidy=true&radiuses={radiuses}"
    )
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        tracepoints = data.get("tracepoints") or []
        if len(tracepoints) != len(points):
            raise ValueError("OSRM match returned an unexpected tracepoint count")
        matched: list[Point | None] = []
        for tracepoint in tracepoints:
            if not tracepoint or not tracepoint.get("location"):
                matched.append(None)
                continue
            matched.append((float(tracepoint["location"][1]), float(tracepoint["location"][0])))
        return matched
    except Exception:
        logger.warning("osrm_match_failed points=%d", len(points))
        return None
