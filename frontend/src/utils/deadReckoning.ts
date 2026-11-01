/**
 * Map-matching and dead reckoning for live tracking.
 *
 * GPS fixes arrive a few seconds apart. Between fixes we project the last
 * known position forward along its heading at its reported speed, and we snap
 * raw fixes onto the OSRM route so the marker follows roads instead of
 * cutting across buildings. Both helpers are pure so they are easy to test.
 */

export interface GeoPoint {
  latitude: number;
  longitude: number;
}

export interface TrackFix extends GeoPoint {
  heading?: number | null;
  speed_kmh?: number | null;
}

export interface RouteMatch extends GeoPoint {
  matched: boolean;
  distance_m: number;
  heading: number;
}

export interface DeadReckonedPosition extends GeoPoint {
  age_ms: number;
  distance_m: number;
}

export const MAX_EXTRAPOLATION_MS = 12_000;
export const MAX_SNAP_DISTANCE_M = 75;
export const MIN_MOVING_SPEED_KMH = 2;

const EARTH_RADIUS_M = 6_371_000;

const toRad = (degrees: number) => (degrees * Math.PI) / 180;
const toDeg = (radians: number) => (radians * 180) / Math.PI;

export function haversineMeters(a: GeoPoint, b: GeoPoint): number {
  const dLat = toRad(b.latitude - a.latitude);
  const dLng = toRad(b.longitude - a.longitude);
  const lat1 = toRad(a.latitude);
  const lat2 = toRad(b.latitude);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function bearingDegrees(from: GeoPoint, to: GeoPoint): number {
  const lat1 = toRad(from.latitude);
  const lat2 = toRad(to.latitude);
  const dLng = toRad(to.longitude - from.longitude);
  const y = Math.sin(dLng) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
  return (toDeg(Math.atan2(y, x)) + 360) % 360;
}

export function destinationPoint(origin: GeoPoint, bearing: number, distanceMeters: number): GeoPoint {
  if (distanceMeters <= 0) return { ...origin };
  const angular = distanceMeters / EARTH_RADIUS_M;
  const theta = toRad(bearing);
  const lat1 = toRad(origin.latitude);
  const lng1 = toRad(origin.longitude);

  const sinLat2 = Math.sin(lat1) * Math.cos(angular) + Math.cos(lat1) * Math.sin(angular) * Math.cos(theta);
  const lat2 = Math.asin(Math.max(-1, Math.min(1, sinLat2)));
  const lng2 =
    lng1 +
    Math.atan2(
      Math.sin(theta) * Math.sin(angular) * Math.cos(lat1),
      Math.cos(angular) - Math.sin(lat1) * sinLat2
    );

  return {
    latitude: toDeg(lat2),
    longitude: ((toDeg(lng2) + 540) % 360) - 180,
  };
}

/**
 * Project a fix forward by up to `MAX_EXTRAPOLATION_MS`. Stationary or
 * heading-less fixes stay put; extrapolation is capped so a stalled
 * connection never lets the marker run away from the last real fix.
 */
export function deadReckon(fix: TrackFix, elapsedMs: number): DeadReckonedPosition {
  const age = Math.max(0, Math.min(elapsedMs, MAX_EXTRAPOLATION_MS));
  const speed = Math.max(0, Math.min(fix.speed_kmh ?? 0, 120));
  const heading = fix.heading;
  if (age === 0 || speed < MIN_MOVING_SPEED_KMH || heading == null || !Number.isFinite(heading)) {
    return { latitude: fix.latitude, longitude: fix.longitude, age_ms: age, distance_m: 0 };
  }
  const distance = (speed * 1000) / 3600 * (age / 1000);
  const point = destinationPoint(fix, heading, distance);
  return { ...point, age_ms: age, distance_m: distance };
}

function projectOnSegment(
  point: GeoPoint,
  start: GeoPoint,
  end: GeoPoint
): { point: GeoPoint; t: number } {
  // Local equirectangular projection: accurate at city scale and cheap.
  const latScale = 111_320;
  const lngScale = Math.cos(toRad(point.latitude)) * 111_320;
  const ax = (start.longitude - point.longitude) * lngScale;
  const ay = (start.latitude - point.latitude) * latScale;
  const bx = (end.longitude - point.longitude) * lngScale;
  const by = (end.latitude - point.latitude) * latScale;
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSq = dx * dx + dy * dy;
  const t = lengthSq === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / lengthSq));
  return {
    point: {
      latitude: start.latitude + (end.latitude - start.latitude) * t,
      longitude: start.longitude + (end.longitude - start.longitude) * t,
    },
    t,
  };
}

/**
 * Snap a point to the closest place on the route. Returns the original point
 * (matched=false) when the nearest road is farther than `maxDistanceMeters`,
 * which avoids teleporting a worker onto an unrelated street.
 */
export function matchToRoute(
  point: GeoPoint,
  route: Array<[number, number]> | null | undefined,
  fallbackHeading = 0,
  maxDistanceMeters = MAX_SNAP_DISTANCE_M
): RouteMatch {
  if (!route || route.length === 0) {
    return { ...point, matched: false, distance_m: 0, heading: fallbackHeading };
  }
  if (route.length === 1) {
    const distance = haversineMeters(point, { latitude: route[0][0], longitude: route[0][1] });
    return {
      latitude: route[0][0],
      longitude: route[0][1],
      matched: distance <= maxDistanceMeters,
      distance_m: distance,
      heading: fallbackHeading,
    };
  }

  let best: RouteMatch | null = null;
  for (let i = 0; i < route.length - 1; i += 1) {
    const start = { latitude: route[i][0], longitude: route[i][1] };
    const end = { latitude: route[i + 1][0], longitude: route[i + 1][1] };
    const projected = projectOnSegment(point, start, end);
    const distance = haversineMeters(point, projected.point);
    if (best === null || distance < best.distance_m) {
      best = {
        latitude: projected.point.latitude,
        longitude: projected.point.longitude,
        matched: false,
        distance_m: distance,
        heading: bearingDegrees(start, end),
      };
    }
  }

  const result = best as RouteMatch;
  if (result.distance_m > maxDistanceMeters) {
    return { ...point, matched: false, distance_m: result.distance_m, heading: fallbackHeading };
  }
  return { ...result, matched: true };
}

/** Angular interpolation that always takes the short way around. */
export function lerpAngle(from: number, to: number, t: number): number {
  const delta = ((to - from + 540) % 360) - 180;
  return (from + delta * t + 360) % 360;
}
