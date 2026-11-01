import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ExternalLink, MapPin, MapPinOff, RouteOff, ShieldAlert } from "lucide-react";

import { adminApi } from "@/api/admin";
import { Badge, Button, Card, EmptyState, Field, Modal, PageLoader, Textarea } from "@/components/ui";
import { WS_EVENTS } from "@/lib/constants";
import { errorMessage, formatDateTime, timeAgo } from "@/lib/utils";
import { toast } from "@/stores/toast";
import { wsService } from "@/services/websocket";
import type { RideCheckEvent } from "@/types";

const ACTIVE_STATUSES = new Set(["OPEN", "ESCALATED"]);

function typeLabel(type: string): string {
  return type === "UNEXPLAINED_STOP" ? "Unexplained stop" : "Route deviation";
}

function typeIcon(type: string) {
  return type === "UNEXPLAINED_STOP" ? (
    <MapPinOff className="h-4 w-4" aria-hidden />
  ) : (
    <RouteOff className="h-4 w-4" aria-hidden />
  );
}

export default function AdminRideCheck() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [resolving, setResolving] = useState<RideCheckEvent | null>(null);
  const [note, setNote] = useState("");

  const eventsQuery = useQuery({
    queryKey: ["admin-ridecheck", page],
    queryFn: () => adminApi.ridecheckEvents(page, 20),
    refetchInterval: 20_000,
  });

  useEffect(() => {
    const invalidate = () => void queryClient.invalidateQueries({ queryKey: ["admin-ridecheck"] });
    const offAlert = wsService.on(WS_EVENTS.RIDECHECK_ESCALATED, invalidate);
    const offRaised = wsService.on(WS_EVENTS.RIDECHECK_ALERT, invalidate);
    return () => {
      offAlert();
      offRaised();
    };
  }, [queryClient]);

  const resolveMutation = useMutation({
    mutationFn: ({ eventId, note }: { eventId: string; note: string }) =>
      adminApi.resolveRidecheck(eventId, note),
    onSuccess: () => {
      toast.success("RideCheck incident resolved — the safety audit trail has been updated.");
      setResolving(null);
      setNote("");
      void queryClient.invalidateQueries({ queryKey: ["admin-ridecheck"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const rows = eventsQuery.data?.items ?? [];
  const total = eventsQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 20));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">RideCheck safety desk</h1>
          <p className="text-sm text-slate-500">
            Incidents raised when a runner deviates more than 400 m for 3 consecutive pings, stops unexplained for 5+
            minutes, or requests help. Unanswered alerts escalate here automatically after 120 seconds.
          </p>
        </div>
        <span className="flex items-center gap-1.5 rounded-full bg-orange-50 px-3 py-1.5 text-xs font-semibold text-orange-700">
          <ShieldAlert className="h-4 w-4" aria-hidden /> {total} flagged incident{total === 1 ? "" : "s"}
        </span>
      </div>

      {eventsQuery.isLoading ? (
        <PageLoader />
      ) : eventsQuery.isError ? (
        <EmptyState icon="⚠️" title="Couldn't load incidents" description={errorMessage(eventsQuery.error)} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon="🛡️"
          title="No safety incidents"
          description="RideCheck is monitoring live routes. Escalated incidents and help requests will appear here instantly."
        />
      ) : (
        <div className="space-y-3">
          {rows.map((event) => {
            const active = ACTIVE_STATUSES.has(event.status) || !event.resolved_at;
            return (
              <Card key={event.id} className={active ? "border-orange-300 bg-orange-50/40" : undefined}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge className={active ? "bg-orange-600 text-white" : "bg-emerald-100 text-emerald-800"}>
                        {active ? event.status : "Resolved"}
                      </Badge>
                      <Badge className="bg-white text-slate-700">
                        {typeIcon(event.type)} {typeLabel(event.type)}
                      </Badge>
                      {event.admin_flagged_at && (
                        <Badge className="bg-red-100 text-red-700">
                          <AlertTriangle className="h-3 w-3" aria-hidden /> Escalated
                        </Badge>
                      )}
                    </div>
                    <p className="mt-2 text-sm font-medium text-slate-900">
                      {event.task_title ?? `Task ${event.task_id.slice(0, 8)}…`}
                      {event.worker_name ? ` · runner ${event.worker_name}` : ""}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {event.deviation_m != null && <>{Math.round(event.deviation_m)} m off route · </>}
                      {event.stationary_seconds != null && (
                        <>stationary {Math.round(event.stationary_seconds / 60)} min · </>
                      )}
                      raised by {event.message ? "RideCheck" : "the safety engine"} {timeAgo(event.created_at)}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">{formatDateTime(event.created_at)}</p>
                    {event.message && (
                      <p className="mt-2 rounded-lg bg-white px-3 py-2 text-xs text-slate-600">{event.message}</p>
                    )}
                    {event.acknowledgment_reason && (
                      <p className="mt-2 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-800">
                        <span className="font-semibold">Runner response: </span>
                        {event.acknowledgment_reason}
                        {event.acknowledged_at ? ` (${timeAgo(event.acknowledged_at)})` : ""}
                      </p>
                    )}
                    {event.latitude != null && event.longitude != null && (
                      <a
                        href={`https://www.openstreetmap.org/?mlat=${event.latitude}&mlon=${event.longitude}#map=17/${event.latitude}/${event.longitude}`}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:underline"
                      >
                        <MapPin className="h-3.5 w-3.5" aria-hidden />
                        {event.latitude.toFixed(5)}, {event.longitude.toFixed(5)}
                        <ExternalLink className="h-3 w-3" aria-hidden />
                      </a>
                    )}
                  </div>
                  {active && (
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setResolving(event);
                        setNote("");
                      }}
                    >
                      <CheckCircle2 className="mr-1.5 h-4 w-4" aria-hidden /> Resolve
                    </Button>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <span className="text-sm text-slate-500">
            Page {page} of {totalPages}
          </span>
          <Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      )}

      <Modal open={resolving !== null} onClose={() => setResolving(null)} title="Resolve RideCheck incident">
        <p className="text-sm text-slate-600">
          Confirm the runner is safe and the situation is understood. The resolution is written to the safety audit trail.
        </p>
        <div className="mt-4">
          <Field label="Resolution note" htmlFor="ridecheck-note" hint="What did support verify? Kept for audit.">
            <Textarea
              id="ridecheck-note"
              rows={3}
              maxLength={1000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Called the runner; traffic diversion confirmed via GPS; route resumed."
            />
          </Field>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setResolving(null)}>
            Cancel
          </Button>
          <Button
            loading={resolveMutation.isPending}
            disabled={note.trim().length < 5}
            onClick={() => {
              if (resolving) resolveMutation.mutate({ eventId: resolving.id, note: note.trim() });
            }}
          >
            Resolve incident
          </Button>
        </div>
      </Modal>
    </div>
  );
}
