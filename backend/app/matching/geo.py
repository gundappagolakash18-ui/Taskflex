import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def is_within_radius(
    lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None, radius_km: float
) -> bool:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return True  # unknown location never excludes a candidate
    return haversine_km(lat1, lon1, lat2, lon2) <= radius_km


def bearing_hint(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    """Compass-direction hint used in demos ('~2.4 km north-east')."""
    import math as m

    angle = m.degrees(m.atan2(lon2 - lon1, lat2 - lat1))
    directions = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
    idx = int(((angle + 360) % 360) // 45)
    return directions[idx % 8]
