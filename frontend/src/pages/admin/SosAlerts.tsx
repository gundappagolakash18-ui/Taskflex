import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, MapPin, Siren } from "lucide-react";

import { adminApi } from "@/api/admin";
import { Badge, Button, Card, EmptyState, Field, Modal, PageLoader, Textarea } from "@/components/ui";
import { SOS_RESOLVED_EVENT } from "@/lib/constants";
import { errorMessage, formatDateTime, timeAgo } from "@/lib/utils";
import { toast } from "@/stores/toast";
import type { SosAlert } from "@/types";

const FILTERS = [
  { value: "OPEN", label: "Open" },
  { value: "RESOLVED", label: "Resolved" },
  { value: "", label: "All alerts" },
];

export default function AdminSosAlerts() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("OPEN");
  const [page, setPage] = useState(1);
  const [resolving, setResolving] = useState<SosAlert | null>(null);
  const [note, setNote] = useState("");

  const alertsQuery = useQuery({
    queryKey: ["admin-sos", status, page],
    queryFn: () => adminApi.sosAlerts({ status: status || undefined, page, page_size: 20 }),
    refetchInterval: 15_000,
  });

  const resolveMutation = useMutation({
    mutationFn: ({ alertId, note }: { alertId: string; note: string }) =>
      adminApi.resolveSosAlert(alertId, note),
    onSuccess: () => {
      toast.success("Emergency alert resolved — the task resumed its previous state.");
      window.dispatchEvent(new Event(SOS_RESOLVED_EVENT));
      setResolving(null);
      setNote("");
      void queryClient.invalidateQueries({ queryKey: ["admin-sos"] });
      void queryClient.invalidateQueries({ queryKey: ["admin-tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["admin-dashboard"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const rows = alertsQuery.data?.items ?? [];
  const total = alertsQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 20));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">SOS desk</h1>
          <p className="text-sm text-slate-500">
            Emergency alerts with frozen GPS evidence. Resolving an alert restores the task's previous status.
          </p>
        </div>
        <span className="flex items-center gap-1.5 rounded-full bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700">
          <Siren className="h-4 w-4" aria-hidden /> {total} matching alert{total === 1 ? "" : "s"}
        </span>
      </div>

      <div className="flex gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => {
              setStatus(f.value);
              setPage(1);
            }}
            className={
              status === f.value
                ? "rounded-full bg-primary-600 px-3.5 py-1.5 text-sm font-medium text-white"
                : "rounded-full bg-white px-3.5 py-1.5 text-sm font-medium text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
            }
          >
            {f.label}
          </button>
        ))}
      </div>

      {alertsQuery.isLoading ? (
        <PageLoader />
      ) : alertsQuery.isError ? (
        <EmptyState icon="⚠️" title="Couldn't load alerts" description={errorMessage(alertsQuery.error)} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon="🛟"
          title={status === "OPEN" ? "No open emergency alerts" : "Nothing here"}
          description={
            status === "OPEN"
              ? "When a customer or runner raises SOS, the alert appears here instantly over the live admin socket."
              : "Try a different filter."
          }
        />
      ) : (
        <div className="space-y-3">
          {rows.map((alert) => {
            const open = alert.status === "OPEN";
            return (
              <Card key={alert.id} className={open ? "border-red-300 bg-red-50/40" : undefined}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge className={open ? "bg-red-600 text-white" : "bg-emerald-100 text-emerald-800"}>
                        {open ? "OPEN — action needed" : "Resolved"}
                      </Badge>
                      <span className="text-xs font-medium text-slate-500">
                        Raised by {alert.raised_by_role.toLowerCase()} · {timeAgo(alert.created_at)}
                      </span>
                    </div>
                    <p className="mt-2 text-sm font-medium text-slate-900">
                      {alert.message ?? "No message supplied — review the frozen GPS trail."}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      Task {alert.task_id.slice(0, 8)}… · previous status{" "}
                      {alert.previous_status ?? "unknown"} · {alert.location_history.length} frozen position
                      {alert.location_history.length === 1 ? "" : "s"}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">Raised {formatDateTime(alert.created_at)}</p>
                    {alert.latitude != null && alert.longitude != null && (
                      <a
                        href={`https://www.openstreetmap.org/?mlat=${alert.latitude}&mlon=${alert.longitude}#map=17/${alert.latitude}/${alert.longitude}`}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:underline"
                      >
                        <MapPin className="h-3.5 w-3.5" aria-hidden />
                        {alert.latitude.toFixed(5)}, {alert.longitude.toFixed(5)}
                        <ExternalLink className="h-3 w-3" aria-hidden />
                      </a>
                    )}
                    {!open && alert.resolution_note && (
                      <p className="mt-2 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                        <span className="font-semibold">Resolution: </span>
                        {alert.resolution_note}
                      </p>
                    )}
                  </div>
                  {open && (
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setResolving(alert);
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

      <Modal open={resolving !== null} onClose={() => setResolving(null)} title="Resolve emergency alert">
        <p className="text-sm text-slate-600">
          Confirm that the people involved are safe and support has handled the situation. The task will return to{" "}
          <span className="font-semibold">{resolving?.previous_status ?? "its previous status"}</span> and both
          participants will be notified.
        </p>
        <div className="mt-4">
          <Field
            label="Resolution note"
            htmlFor="sos-note"
            hint="Record what support did — this is kept in the audit trail."
          >
            <Textarea
              id="sos-note"
              rows={3}
              maxLength={1000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Called both parties; runner confirmed safe; task resumed."
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
              if (resolving) resolveMutation.mutate({ alertId: resolving.id, note: note.trim() });
            }}
          >
            Resolve & resume task
          </Button>
        </div>
      </Modal>
    </div>
  );
}
