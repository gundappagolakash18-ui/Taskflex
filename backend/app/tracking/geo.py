"""Geometry for live tracking: bearings, polyline projection, route math."""

from dataclasses import dataclass
import math

from app.matching.geo import haversine_km

_EARTH_RADIUS_M = 6_371_000.0


def bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Initial heading from point 1 to point 2, degrees clockwise from north."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lng2 - lng1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _to_xy_m(lat: float, lng: float, lat0: float) -> tuple[float, float]:
    """Equirectangular projection to local metres; accurate over city-scale segments."""
    x = math.radians(lng) * _EARTH_RADIUS_M * math.cos(math.radians(lat0))
    y = math.radians(lat) * _EARTH_RADIUS_M
    return x, y


@dataclass
class RouteState:
    """A driving route as an ordered polyline plus cumulative distances."""

    coordinates: list[tuple[float, float]]  # (lat, lng)
    distance_km: float
    duration_min: float
    cumulative_km: list[float]  # cumulative distance at each vertex; same length

    @property
    def destination(self) -> tuple[float, float]:
        return self.coordinates[-1]


def build_route_state(coordinates: list[tuple[float, float]], duration_min: float) -> RouteState:
    cumulative: list[float] = [0.0]
    for (lat_a, lng_a), (lat_b, lng_b) in zip(coordinates, coordinates[1:]):
        cumulative.append(cumulative[-1] + haversine_km(lat_a, lng_a, lat_b, lng_b))
    return RouteState(
        coordinates=coordinates,
        distance_km=round(cumulative[-1], 3),
        duration_min=round(max(duration_min, 0.0), 1),
        cumulative_km=[round(c, 4) for c in cumulative],
    )


@dataclass
class Projection:
    segment_index: int
    along_km: float
    deviation_km: float


def project_onto_route(route: RouteState, lat: float, lng: float) -> Projection:
    """Locate a point along the polyline: nearest segment, distance travelled,
    and perpendicular deviation from the route."""
    coords = route.coordinates
    if len(coords) == 1:
        dev = haversine_km(lat, lng, coords[0][0], coords[0][1])
        return Projection(0, 0.0, dev)

    best = Projection(0, 0.0, float("inf"))
    for i in range(len(coords) - 1):
        lat_a, lng_a = coords[i]
        lat_b, lng_b = coords[i + 1]
        lat0 = (lat_a + lat_b) / 2.0
        ax, ay = _to_xy_m(lat_a, lng_a, lat0)
        bx, by = _to_xy_m(lat_b, lng_b, lat0)
        px, py = _to_xy_m(lat, lng, lat0)

        abx, aby = bx - ax, by - ay
        ab2 = abx * abx + aby * aby
        t = 0.0 if ab2 == 0 else max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / ab2))
        cx, cy = ax + t * abx, ay + t * aby
        dev = math.hypot(px - cx, py - cy)
        if dev < best.deviation_km * 1000.0:
            seg_km = (route.cumulative_km[i + 1] - route.cumulative_km[i]) * t
            best = Projection(i, route.cumulative_km[i] + seg_km, dev / 1000.0)
    return best


def remaining_km(route: RouteState, along_km: float) -> float:
    return max(route.distance_km - along_km, 0.0)


def eta_minutes(remaining_km_value: float, speed_kmph: float, duration_min: float, route: RouteState, along_km: float) -> float:
    """Prefer live speed; fall back to the route's planned duration pro-rated
    by how much of the polyline is left."""
    if speed_kmph > 2.0:
        return round(remaining_km_value / speed_kmph * 60.0, 1)
    if route.distance_km > 0:
        fraction = max(remaining_km_value / route.distance_km, 0.0)
        return round(duration_min * fraction, 1)
    return round(duration_min, 1)
