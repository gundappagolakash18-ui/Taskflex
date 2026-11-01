import { useEffect, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, LifeBuoy, MapPinOff, ShieldAlert } from "lucide-react";

import { tasksApi } from "@/api/tasks";
import { Badge, Button, Card } from "@/components/ui";
import { WS_EVENTS } from "@/lib/constants";
import { errorMessage, timeAgo } from "@/lib/utils";
import { toast } from "@/stores/toast";
import { wsService } from "@/services/websocket";
import type { RideCheckEvent } from "@/types";

const ACTIVE_STATUSES = new Set(["OPEN", "ESCALATED"]);

function typeLabel(type: string): string {
  return type === "UNEXPLAINED_STOP" ? "Unexplained stop" : "Route deviation";
}

function typeIcon(type: string) {
  return type === "UNEXPLAINED_STOP" ? (
    <MapPinOff className="h-5 w-5" aria-hidden />
  ) : (
    <AlertTriangle className="h-5 w-5" aria-hidden />
  );
}

export default function RideCheckBanner({
  taskId,
  role,
  enabled,
}: {
  taskId: string;
  role: "CUSTOMER" | "WORKER";
  enabled: boolean;
}) {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["ridecheck", taskId],
    queryFn: () => tasksApi.ridecheck(taskId),
    enabled,
    refetchInterval: enabled ? 8_000 : false,
  });

  useEffect(() => {
    if (!enabled) return;
    const invalidate = () => {
      void queryClient.invalidateQueries({ queryKey: ["ridecheck", taskId] });
    };
    const offAlert = wsService.on(WS_EVENTS.RIDECHECK_ALERT, (frame) => {
      const data = frame.data as { task_id?: string };
      if (!data.task_id || data.task_id === taskId) invalidate();
    });
    const offUpdate = wsService.on(WS_EVENTS.RIDECHECK_UPDATE, invalidate);
    const offEscalated = wsService.on(WS_EVENTS.RIDECHECK_ESCALATED, invalidate);
    return () => {
      offAlert();
      offUpdate();
      offEscalated();
    };
  }, [enabled, taskId, queryClient]);

  const ackMutation = useMutation({
    mutationFn: ({ event, action, reason }: { event: RideCheckEvent; action: "SAFE" | "HELP"; reason?: string }) =>
      tasksApi.acknowledgeRidecheck(event.id, action, reason),
    onSuccess: (event, variables) => {
      if (variables.action === "HELP") {
        toast.error("Help requested — the TaskFlex safety team has been alerted.");
      } else {
        toast.success("Checked in as safe. The route was refreshed and the customer notified.");
      }
      queryClient.setQueryData(["ridecheck", taskId], (prev: { active: RideCheckEvent | null; events: RideCheckEvent[] } | undefined) =>
        prev ? { ...prev, active: ACTIVE_STATUSES.has(event.status) ? event : null } : prev
      );
      void queryClient.invalidateQueries({ queryKey: ["ridecheck", taskId] });
      void queryClient.invalidateQueries({ queryKey: ["task", taskId] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const active = query.data?.active ?? null;
  const history = useMemo(
    () => (query.data?.events ?? []).filter((event) => !ACTIVE_STATUSES.has(event.status)).slice(0, 3),
    [query.data?.events]
  );

  if (!enabled || !active) return null;

  const escalated = active.status === "ESCALATED" || Boolean(active.admin_flagged_at);
  const tone = escalated
    ? "border-red-400 bg-red-50"
    : active.type === "ROUTE_DEVIATION"
      ? "border-orange-300 bg-orange-50"
      : "border-amber-300 bg-amber-50";

  return (
    <Card className={`${tone} border-2`} >
      <div role="alert" aria-live="assertive" className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className={escalated ? "text-red-600" : "text-orange-600"}>{typeIcon(active.type)}</div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-bold text-slate-900">RideCheck: {typeLabel(active.type)}</p>
              <Badge className={escalated ? "bg-red-600 text-white" : "bg-white text-slate-700"}>
                Non-dismissible alert
              </Badge>
              {escalated && (
                <Badge className="bg-red-600 text-white">
                  <ShieldAlert className="h-3 w-3" aria-hidden /> Safety team alerted
                </Badge>
              )}
            </div>
            <p className="mt-1 text-sm text-slate-700">
              {active.message ??
                (active.type === "ROUTE_DEVIATION"
                  ? "Your live location moved far away from the planned route."
                  : "Your live location has stayed still for an unusually long time.")}
            </p>
            <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
              {active.deviation_m != null && <span>{Math.round(active.deviation_m)} m off route</span>}
              {active.stationary_seconds != null && <span>Stationary for {Math.round(active.stationary_seconds / 60)} min</span>}
              {active.created_at && <span>Raised {timeAgo(active.created_at)}</span>}
              {active.latitude != null && active.longitude != null && (
                <span>
                  {active.latitude.toFixed(5)}, {active.longitude.toFixed(5)}
                </span>
              )}
            </p>
            {role === "CUSTOMER" && (
              <p className="mt-2 text-xs font-medium text-slate-600">
                We've asked your runner to check in. If anything feels wrong, use the SOS button below.
              </p>
            )}
          </div>
        </div>

        {role === "WORKER" && (
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">
            <Button
              variant="secondary"
              className="flex-1 sm:flex-none"
              loading={ackMutation.isPending && ackMutation.variables?.action === "SAFE"}
              onClick={() => ackMutation.mutate({ event: active, action: "SAFE", reason: "Traffic" })}
            >
              <CheckCircle2 className="h-4 w-4" aria-hidden /> I'm safe — traffic
            </Button>
            <Button
              variant="secondary"
              className="flex-1 sm:flex-none"
              disabled={ackMutation.isPending}
              onClick={() => ackMutation.mutate({ event: active, action: "SAFE", reason: "Detour" })}
            >
              <CheckCircle2 className="h-4 w-4" aria-hidden /> I'm safe — detour
            </Button>
            <Button
              variant="danger"
              className="flex-1 sm:flex-none"
              loading={ackMutation.isPending && ackMutation.variables?.action === "HELP"}
              onClick={() => ackMutation.mutate({ event: active, action: "HELP", reason: "Worker requested help" })}
            >
              <LifeBuoy className="h-4 w-4" aria-hidden /> Need help / SOS
            </Button>
          </div>
        )}
      </div>

      {history.length > 0 && (
        <div className="mt-3 rounded-lg bg-white/70 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Recent safety checks</p>
          <ul className="mt-1.5 space-y-1 text-xs text-slate-600">
            {history.map((event) => (
              <li key={event.id} className="flex flex-wrap items-center justify-between gap-2">
                <span>{typeLabel(event.type)}</span>
                <span className="text-slate-400">
                  {event.status.toLowerCase().replaceAll("_", " ")}
                  {event.created_at ? ` · ${timeAgo(event.created_at)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
