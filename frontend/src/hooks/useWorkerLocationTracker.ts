import { useCallback, useEffect, useRef, useState } from "react";

import { wsService } from "@/services/websocket";

export interface WorkerPosition {
  latitude: number;
  longitude: number;
  heading: number | null;
  speed_kmph: number | null;
  at: number;
}

export function useWorkerLocationTracker(taskId: string, active: boolean) {
  const [position, setPosition] = useState<WorkerPosition | null>(null);
  const [error, setError] = useState<string | null>(null);
  const watchId = useRef<number | null>(null);
  const taskRef = useRef(taskId);
  taskRef.current = taskId;

  const emit = useCallback((latitude: number, longitude: number, heading: number | null = null, speed_kmph: number | null = null) => {
    setPosition({ latitude, longitude, heading, speed_kmph, at: Date.now() });
    wsService.send({
      event: "location_update",
      data: { task_id: taskRef.current, latitude, longitude, heading, speed_kmph },
    });
  }, []);

  useEffect(() => {
    if (!active || !taskId) return;
    if (!("geolocation" in navigator)) {
      setError("Geolocation is not supported by this browser.");
      return;
    }
    setError(null);
    watchId.current = navigator.geolocation.watchPosition(
      (pos) => {
        const c = pos.coords;
        emit(c.latitude, c.longitude, c.heading ?? null, c.speed != null ? c.speed * 3.6 : null);
      },
      (err) => setError(err.message || "Unable to read your location."),
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 15000 }
    );
    return () => {
      if (watchId.current != null) navigator.geolocation.clearWatch(watchId.current);
      watchId.current = null;
      setPosition(null);
    };
  }, [active, taskId, emit]);

  return { position, error, emit };
}
