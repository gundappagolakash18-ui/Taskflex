import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { deadReckon, lerpAngle, matchToRoute } from "@/utils/deadReckoning";

interface LiveTrackingMapProps {
  destination: { latitude: number; longitude: number };
  route?: [number, number][] | null;
  update?: {
    latitude: number;
    longitude: number;
    heading?: number | null;
    speed_kmph?: number | null;
  } | null;
  className?: string;
}

interface LiveFix {
  latitude: number;
  longitude: number;
  heading: number;
  speed_kmh: number;
  receivedAt: number;
}

const DESTINATION_HTML = `<svg viewBox="0 0 24 24" width="28" height="28"><path d="M12 1C7.9 1 4.5 4.4 4.5 8.5c0 5.6 6.6 13.2 6.9 13.5.3.3.9.3 1.2 0 .3-.3 6.9-7.9 6.9-13.5C19.5 4.4 16.1 1 12 1z" fill="#e11d48" stroke="#fff" stroke-width="1.4"/><circle cx="12" cy="8.5" r="2.6" fill="#fff"/></svg>`;

const VEHICLE_HTML = `<div class="tf-vehicle" style="width:36px;height:36px;display:flex;align-items:center;justify-content:center;transform:rotate(0deg);will-change:transform;">
  <svg viewBox="0 0 24 24" width="30" height="30" style="filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))">
    <circle cx="12" cy="12" r="11" fill="#4f46e5" stroke="#fff" stroke-width="2"/>
    <path d="M12 5.5 L16.5 16.5 L12 14 L7.5 16.5 Z" fill="#fff"/>
  </svg>
</div>`;

const PAN_INTERVAL_MS = 1500;
const SNAP_DISTANCE_M = 45;

export default function LiveTrackingMap({ destination, route, update, className }: LiveTrackingMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const destMarkerRef = useRef<L.Marker | null>(null);
  const routeLineRef = useRef<L.Polyline | null>(null);
  const vehicleRef = useRef<L.Marker | null>(null);
  const arrowRef = useRef<HTMLElement | null>(null);
  const displayRef = useRef<{ lat: number; lng: number; heading: number } | null>(null);
  const fixRef = useRef<LiveFix | null>(null);
  const routeRef = useRef<[number, number][] | null>(null);
  const rafRef = useRef<number>(0);
  const lastFrameRef = useRef(0);
  const lastPanRef = useRef(0);
  const fittedRef = useRef(false);

  routeRef.current = route && route.length > 1 ? route : null;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: true }).setView(
      [destination.latitude, destination.longitude],
      14
    );
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    destMarkerRef.current = L.marker([destination.latitude, destination.longitude], {
      icon: L.divIcon({ className: "", html: DESTINATION_HTML, iconSize: [28, 28], iconAnchor: [14, 27] }),
    }).addTo(map);
    mapRef.current = map;
    const t = window.setTimeout(() => map.invalidateSize(), 80);

    const frame = (now: number) => {
      const liveMap = mapRef.current;
      const fix = fixRef.current;
      if (liveMap && fix) {
        if (!vehicleRef.current) {
          vehicleRef.current = L.marker([fix.latitude, fix.longitude], {
            icon: L.divIcon({ className: "", html: VEHICLE_HTML, iconSize: [36, 36], iconAnchor: [18, 18] }),
            zIndexOffset: 500,
          }).addTo(liveMap);
          arrowRef.current = (vehicleRef.current.getElement()?.firstElementChild as HTMLElement) ?? null;
          displayRef.current = { lat: fix.latitude, lng: fix.longitude, heading: fix.heading };
        }

        // Dead reckoning: project the last real fix forward while we wait
        // for the next telemetry frame, then pull it onto the road polyline.
        const prediction = deadReckon(
          { latitude: fix.latitude, longitude: fix.longitude, heading: fix.heading, speed_kmh: fix.speed_kmh },
          now - fix.receivedAt
        );
        let target = { latitude: prediction.latitude, longitude: prediction.longitude };
        if (routeRef.current) {
          const snapped = matchToRoute(target, routeRef.current, fix.heading, SNAP_DISTANCE_M);
          if (snapped.matched) target = { latitude: snapped.latitude, longitude: snapped.longitude };
        }

        const previous =
          displayRef.current ?? { lat: target.latitude, lng: target.longitude, heading: fix.heading };
        const dt = lastFrameRef.current ? Math.min(120, now - lastFrameRef.current) : 16;
        const easing = 1 - Math.exp(-dt / 220);
        const next = {
          lat: previous.lat + (target.latitude - previous.lat) * easing,
          lng: previous.lng + (target.longitude - previous.lng) * easing,
          heading: lerpAngle(previous.heading, fix.heading, easing),
        };
        displayRef.current = next;
        vehicleRef.current?.setLatLng([next.lat, next.lng]);
        arrowRef.current?.style.setProperty("transform", `rotate(${next.heading}deg)`);

        if (now - lastPanRef.current > PAN_INTERVAL_MS) {
          lastPanRef.current = now;
          const position = L.latLng(next.lat, next.lng);
          if (!liveMap.getBounds().pad(-0.15).contains(position)) {
            liveMap.panTo(position, { animate: true, duration: 0.9 });
          }
        }
      }
      lastFrameRef.current = now;
      rafRef.current = requestAnimationFrame(frame);
    };
    rafRef.current = requestAnimationFrame(frame);

    return () => {
      window.clearTimeout(t);
      cancelAnimationFrame(rafRef.current);
      map.remove();
      mapRef.current = null;
      routeLineRef.current = null;
      destMarkerRef.current = null;
      vehicleRef.current = null;
      arrowRef.current = null;
      displayRef.current = null;
      fixRef.current = null;
      fittedRef.current = false;
      lastFrameRef.current = 0;
      lastPanRef.current = 0;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (destMarkerRef.current) {
      destMarkerRef.current.setLatLng([destination.latitude, destination.longitude]);
    }
  }, [destination.latitude, destination.longitude]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (routeLineRef.current) {
      routeLineRef.current.remove();
      routeLineRef.current = null;
    }
    if (route && route.length > 1) {
      routeLineRef.current = L.polyline(route, {
        color: "#4f46e5",
        weight: 4,
        opacity: 0.85,
        lineCap: "round",
        lineJoin: "round",
      }).addTo(map);
    }
    if (!fittedRef.current) {
      if (routeLineRef.current) {
        map.fitBounds(routeLineRef.current.getBounds().pad(0.25), { maxZoom: 16 });
        fittedRef.current = true;
      } else if (displayRef.current) {
        map.fitBounds(
          L.latLngBounds([
            [destination.latitude, destination.longitude],
            [displayRef.current.lat, displayRef.current.lng],
          ]).pad(0.3),
          { maxZoom: 16 }
        );
        fittedRef.current = true;
      }
    }
  }, [route, destination.latitude, destination.longitude]);

  useEffect(() => {
    if (!mapRef.current || !update) return;

    const raw = { latitude: update.latitude, longitude: update.longitude };
    const snapped = matchToRoute(raw, routeRef.current, update.heading ?? 0);
    const heading = update.heading ?? (snapped.matched ? snapped.heading : fixRef.current?.heading ?? 0);
    fixRef.current = {
      latitude: snapped.matched ? snapped.latitude : raw.latitude,
      longitude: snapped.matched ? snapped.longitude : raw.longitude,
      heading,
      speed_kmh: update.speed_kmph ?? 0,
      receivedAt: performance.now(),
    };

    if (!fittedRef.current) {
      mapRef.current.fitBounds(
        L.latLngBounds([
          [destination.latitude, destination.longitude],
          [fixRef.current.latitude, fixRef.current.longitude],
        ]).pad(0.3),
        { maxZoom: 16 }
      );
      fittedRef.current = true;
    }
  }, [update, destination.latitude, destination.longitude]);

  return <div ref={containerRef} className={className} style={{ height: 340, borderRadius: 12 }} />;
}
