import { describe, expect, it } from "vitest";

import {
  MAX_EXTRAPOLATION_MS,
  bearingDegrees,
  deadReckon,
  destinationPoint,
  haversineMeters,
  lerpAngle,
  matchToRoute,
} from "./deadReckoning";

const HANJI_NAGAR = { latitude: 15.8497, longitude: 74.4977 };

describe("haversineMeters", () => {
  it("returns zero for identical points", () => {
    expect(haversineMeters(HANJI_NAGAR, HANJI_NAGAR)).toBe(0);
  });

  it("measures one degree of latitude as roughly 111 km", () => {
    const north = { latitude: HANJI_NAGAR.latitude + 1, longitude: HANJI_NAGAR.longitude };
    expect(haversineMeters(HANJI_NAGAR, north)).toBeGreaterThan(110_000);
    expect(haversineMeters(HANJI_NAGAR, north)).toBeLessThan(112_500);
  });
});

describe("bearingDegrees", () => {
  it("points north for a positive latitude delta", () => {
    const north = { latitude: HANJI_NAGAR.latitude + 0.01, longitude: HANJI_NAGAR.longitude };
    expect(bearingDegrees(HANJI_NAGAR, north)).toBeCloseTo(0, 3);
  });

  it("points east for a positive longitude delta", () => {
    const east = { latitude: HANJI_NAGAR.latitude, longitude: HANJI_NAGAR.longitude + 0.01 };
    expect(bearingDegrees(HANJI_NAGAR, east)).toBeCloseTo(90, 1);
  });
});

describe("destinationPoint", () => {
  it("moves north when bearing is zero", () => {
    const moved = destinationPoint(HANJI_NAGAR, 0, 1_000);
    expect(moved.latitude).toBeGreaterThan(HANJI_NAGAR.latitude);
    expect(moved.longitude).toBeCloseTo(HANJI_NAGAR.longitude, 5);
    expect(haversineMeters(HANJI_NAGAR, moved)).toBeCloseTo(1_000, 0);
  });

  it("returns the origin for zero distance", () => {
    expect(destinationPoint(HANJI_NAGAR, 120, 0)).toEqual(HANJI_NAGAR);
  });
});

describe("deadReckon", () => {
  it("projects a moving fix forward at the reported speed", () => {
    const fix = { ...HANJI_NAGAR, heading: 90, speed_kmh: 36 };
    const position = deadReckon(fix, 5_000);
    expect(position.distance_m).toBeCloseTo(50, 5);
    expect(position.age_ms).toBe(5_000);
    expect(position.longitude).toBeGreaterThan(fix.longitude);
    expect(haversineMeters(fix, position)).toBeCloseTo(50, 0);
  });

  it("keeps stationary or heading-less fixes in place", () => {
    expect(deadReckon({ ...HANJI_NAGAR, heading: 90, speed_kmh: 0 }, 5_000)).toMatchObject({
      ...HANJI_NAGAR,
      distance_m: 0,
    });
    expect(deadReckon({ ...HANJI_NAGAR, speed_kmh: 40 }, 5_000)).toMatchObject({
      ...HANJI_NAGAR,
      distance_m: 0,
    });
  });

  it("caps extrapolation so a stalled feed cannot run away", () => {
    const fix = { ...HANJI_NAGAR, heading: 0, speed_kmh: 40 };
    expect(deadReckon(fix, 60_000).age_ms).toBe(MAX_EXTRAPOLATION_MS);
    expect(deadReckon(fix, -1_000).age_ms).toBe(0);
  });
});

describe("matchToRoute", () => {
  const street: Array<[number, number]> = [
    [15.849, 74.497],
    [15.849, 74.498],
  ];

  it("snaps a nearby fix onto the closest road segment", () => {
    const raw = { latitude: 15.84905, longitude: 74.4974 };
    const match = matchToRoute(raw, street);
    expect(match.matched).toBe(true);
    expect(match.latitude).toBeCloseTo(15.849, 6);
    expect(match.distance_m).toBeLessThan(10);
  });

  it("leaves far-away points unmatched instead of teleporting them", () => {
    const raw = { latitude: 15.86, longitude: 74.51 };
    const match = matchToRoute(raw, street, 45);
    expect(match.matched).toBe(false);
    expect(match.latitude).toBe(raw.latitude);
    expect(match.longitude).toBe(raw.longitude);
    expect(match.heading).toBe(45);
  });

  it("handles empty and single-point routes", () => {
    expect(matchToRoute(HANJI_NAGAR, []).matched).toBe(false);
    const single = matchToRoute(HANJI_NAGAR, [[15.8497, 74.4977]]);
    expect(single.matched).toBe(true);
    expect(single.distance_m).toBe(0);
  });
});

describe("lerpAngle", () => {
  it("takes the short way across the 0/360 boundary", () => {
    expect(lerpAngle(350, 10, 0.5)).toBeCloseTo(0, 5);
    expect(lerpAngle(10, 350, 0.5)).toBeCloseTo(0, 5);
    expect(lerpAngle(0, 90, 0.5)).toBeCloseTo(45, 5);
  });
});
