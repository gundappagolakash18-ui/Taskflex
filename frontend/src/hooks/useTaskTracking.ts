import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { WS_EVENTS } from "@/lib/constants";
import { wsService } from "@/services/websocket";
import { tasksApi } from "@/api/tasks";
import type { TrackingUpdate } from "@/types";

const RESUBSCRIBE_MS = 8000;

export function useTaskTracking(taskId: string, enabled: boolean) {
  const queryClient = useQueryClient();
  const [update, setUpdate] = useState<TrackingUpdate | null>(null);

  const snapshotQuery = useQuery({
    queryKey: ["task-tracking", taskId],
    queryFn: () => tasksApi.tracking(taskId),
    enabled: enabled && !!taskId,
    refetchInterval: 30_000,
  });

  useEffect(() => {
    if (!enabled || !taskId) {
      setUpdate(null);
      return;
    }

    const subscribe = () => wsService.send({ event: "subscribe_tracking", data: { task_id: taskId } });
    subscribe();
    const resubscribe = setInterval(subscribe, RESUBSCRIBE_MS);

    const offTracking = wsService.on(WS_EVENTS.TRACKING, (data) => {
      const payload = data.data as unknown as TrackingUpdate;
      if (payload.task_id === taskId) setUpdate(payload);
    });

    const offStatus = wsService.on(WS_EVENTS.TASK_STATUS, (frame) => {
      const payload = frame.data as { task_id?: string };
      if (payload.task_id === taskId) {
        setUpdate(null);
        void queryClient.invalidateQueries({ queryKey: ["task-tracking", taskId] });
      }
    });

    return () => {
      clearInterval(resubscribe);
      offTracking();
      offStatus();
      wsService.send({ event: "unsubscribe_tracking", data: { task_id: taskId } });
    };
  }, [enabled, taskId, queryClient]);

  const snapshot = enabled ? snapshotQuery.data ?? null : null;
  return {
    snapshot,
    update: update ?? snapshot?.latest ?? null,
    isLoading: snapshotQuery.isLoading,
  };
}
