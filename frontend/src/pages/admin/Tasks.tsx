import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { adminApi } from "@/api/admin";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge, Button, Card, EmptyState, Field, Input, Modal, PageLoader, Select, Textarea } from "@/components/ui";
import { TASK_STATUS_LABELS, TASK_TYPE_LABELS } from "@/lib/constants";
import { errorMessage } from "@/lib/utils";
import { toast } from "@/stores/toast";
import type { Task } from "@/types";

const STATUS_OPTIONS = [
  "",
  "PENDING_CONFIRMATION",
  "CONFIRMED",
  "SEARCHING_WORKER",
  "OFFERED",
  "ACCEPTED",
  "WORKER_ON_THE_WAY",
  "ARRIVED_AT_LOCATION",
  "IN_PROGRESS",
  "COMPLETION_REQUESTED",
  "COMPLETED",
  "CANCELLED",
  "DISPUTED",
  "EMERGENCY_ALERT",
];

export default function AdminTasks() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [taskType, setTaskType] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [cancelling, setCancelling] = useState<Task | null>(null);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | undefined>();

  const tasks = useQuery({
    queryKey: ["admin-tasks", status, taskType, query, page],
    queryFn: () =>
      adminApi.tasks({
        status: status || undefined,
        task_type: taskType || undefined,
        search: query || undefined,
        page,
        page_size: 20,
      }),
  });

  const cancel = useMutation({
    mutationFn: ({ taskId, note }: { taskId: string; note: string }) => adminApi.cancelTask(taskId, note),
    onSuccess: () => {
      toast.success("Task cancelled.");
      setCancelling(null);
      setReason("");
      void qc.invalidateQueries({ queryKey: ["admin-tasks"] });
      void qc.invalidateQueries({ queryKey: ["admin-dashboard"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const rows = tasks.data?.items ?? [];
  const total = tasks.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 20));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Tasks</h1>
        <p className="text-sm text-slate-500">{total} errands on the platform</p>
      </div>

      <Card className="flex flex-wrap items-center gap-3 p-4">
        <form
          className="relative flex-1 min-w-56"
          onSubmit={(e) => {
            e.preventDefault();
            setPage(1);
            setQuery(search);
          }}
        >
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search title, area or city…"
            className="pl-9"
          />
        </form>
        <Select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
          className="w-52"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s === "" ? "Any status" : TASK_STATUS_LABELS[s as keyof typeof TASK_STATUS_LABELS] ?? s}
            </option>
          ))}
        </Select>
        <Select
          value={taskType}
          onChange={(e) => {
            setTaskType(e.target.value);
            setPage(1);
          }}
          className="w-52"
        >
          <option value="">Any type</option>
          {Object.entries(TASK_TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
      </Card>

      {tasks.isLoading ? (
        <PageLoader />
      ) : rows.length === 0 ? (
        <EmptyState icon="📋" title="No tasks match" description="Try a different status or clear the search." />
      ) : (
        <div className="space-y-3">
          {rows.map((t) => (
            <Card key={t.id} className="p-4">
              <div className="flex flex-wrap items-start gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate font-semibold text-slate-800">{t.title}</p>
                    <StatusBadge status={t.status} />
                    {t.parsed_by_ai && (
                      <Badge className="bg-purple-100 text-purple-700" >
                        AI {Math.round(t.ai_confidence * 100)}%
                      </Badge>
                    )}
                  </div>
                  <p className="truncate text-xs text-slate-500">
                    {TASK_TYPE_LABELS[t.task_type] ?? t.task_type} · ₹{t.budget.toLocaleString()} ·{" "}
                    {[t.area_name, t.city].filter(Boolean).join(", ") || "No location"}
                  </p>
                  <p className="truncate text-xs text-slate-400">
                    {t.customer?.full_name ?? "Unknown customer"}
                    {t.worker ? ` → ${t.worker.full_name}` : ""} · created{" "}
                    {t.created_at ? new Date(t.created_at).toLocaleDateString() : "—"}
                    {t.cancellation_reason ? ` · cancelled: ${t.cancellation_reason}` : ""}
                  </p>
                </div>
                {!["COMPLETED", "CANCELLED", "DISPUTED"].includes(t.status) && (
                  <Button
                    variant="danger"
                    className="text-xs"
                    onClick={() => {
                      setCancelling(t);
                      setReason("");
                      setReasonError(undefined);
                    }}
                  >
                    Force cancel
                  </Button>
                )}
              </div>
            </Card>
          ))}
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

      <Modal open={cancelling !== null} onClose={() => setCancelling(null)} title="Force cancel task">
        <p className="mb-4 text-sm text-slate-600">
          Cancelling <span className="font-semibold">{cancelling?.title}</span> notifies both parties and releases any
          pending offers. This cannot be undone.
        </p>
        <Field label="Reason (shared with both parties)" htmlFor="cancel-reason">
          <Textarea
            id="cancel-reason"
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
              setReasonError(undefined);
            }}
            placeholder="e.g. Cancelled by platform — the requested location is outside our service area."
          />
          {reasonError && <p className="mt-1 text-xs text-red-600">{reasonError}</p>}
        </Field>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setCancelling(null)}>
            Keep task
          </Button>
          <Button
            variant="danger"
            loading={cancel.isPending}
            onClick={() => {
              if (reason.trim().length < 3) {
                setReasonError("Please enter a reason of at least 3 characters.");
                return;
              }
              if (cancelling) cancel.mutate({ taskId: cancelling.id, note: reason.trim() });
            }}
          >
            Cancel task
          </Button>
        </div>
      </Modal>
    </div>
  );
}
