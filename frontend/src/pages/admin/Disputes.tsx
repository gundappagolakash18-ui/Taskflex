import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { disputesApi } from "@/api/social";
import { Badge, Button, Card, EmptyState, Field, Modal, PageLoader, Select, Textarea } from "@/components/ui";
import { errorMessage } from "@/lib/utils";
import { toast } from "@/stores/toast";
import type { Dispute } from "@/types";

const REASON_LABELS: Record<string, string> = {
  worker_no_show: "Runner no-show",
  work_not_done: "Errand not completed",
  behaviour: "Unacceptable behaviour",
  payment_issue: "Payment issue",
  safety_concern: "Safety concern",
  other: "Other",
};

const STATUS_STYLES: Record<string, string> = {
  OPEN: "bg-red-100 text-red-700",
  UNDER_REVIEW: "bg-amber-100 text-amber-700",
  RESOLVED: "bg-emerald-100 text-emerald-700",
  REJECTED: "bg-slate-200 text-slate-600",
};

const TABS = ["", "OPEN", "UNDER_REVIEW", "RESOLVED", "REJECTED"];

function DisputeCard({ dispute, onResolve }: { dispute: Dispute; onResolve: (d: Dispute) => void }) {
  const isOpen = dispute.status === "OPEN" || dispute.status === "UNDER_REVIEW";
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={STATUS_STYLES[dispute.status] ?? "bg-slate-100 text-slate-600"}>
              {dispute.status.replace("_", " ").toLowerCase()}
            </Badge>
            <span className="font-semibold text-slate-800">
              {REASON_LABELS[dispute.reason] ?? dispute.reason}
            </span>
          </div>
          <p className="mt-1 line-clamp-2 text-sm text-slate-600">{dispute.description}</p>
          <p className="mt-1 text-xs text-slate-400">
            Filed {new Date(dispute.created_at).toLocaleString()} · task{" "}
            <Link to={`/admin/tasks`} className="font-mono text-primary-600 hover:underline">
              {dispute.task_id.slice(0, 8)}…
            </Link>
          </p>
          {dispute.resolution_note && (
            <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <span className="font-semibold">Resolution:</span> {dispute.resolution_note}
            </p>
          )}
        </div>
        {isOpen && (
          <Button className="text-xs" onClick={() => onResolve(dispute)}>
            Resolve
          </Button>
        )}
      </div>
    </Card>
  );
}

export default function Disputes() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [resolving, setResolving] = useState<Dispute | null>(null);
  const [outcome, setOutcome] = useState("RESOLVED");
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState<string | undefined>();

  const disputes = useQuery({
    queryKey: ["admin-disputes", status, page],
    queryFn: () => disputesApi.list(status || undefined, page, 20),
  });

  const resolve = useMutation({
    mutationFn: (payload: { disputeId: string; outcome: string; note: string }) =>
      disputesApi.resolve(payload.disputeId, { status: payload.outcome, resolution_note: payload.note }),
    onSuccess: () => {
      toast.success("Dispute resolved.");
      setResolving(null);
      setNote("");
      void qc.invalidateQueries({ queryKey: ["admin-disputes"] });
      void qc.invalidateQueries({ queryKey: ["admin-dashboard"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const rows = disputes.data?.items ?? [];
  const total = disputes.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 20));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Disputes</h1>
        <p className="text-sm text-slate-500">{total} filed overall</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => {
              setStatus(t);
              setPage(1);
            }}
            className={
              status === t
                ? "rounded-full bg-slate-900 px-4 py-1.5 text-sm font-medium text-white"
                : "rounded-full bg-white px-4 py-1.5 text-sm font-medium text-slate-500 ring-1 ring-slate-200 hover:text-slate-800"
            }
          >
            {t === "" ? "All" : t.replace("_", " ").toLowerCase()}
          </button>
        ))}
      </div>

      {disputes.isLoading ? (
        <PageLoader />
      ) : rows.length === 0 ? (
        <EmptyState icon="⚖️" title="Nothing here" description="No disputes match this filter." />
      ) : (
        <div className="space-y-3">
          {rows.map((d) => (
            <DisputeCard key={d.id} dispute={d} onResolve={setResolving} />
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

      <Modal open={resolving !== null} onClose={() => setResolving(null)} title="Resolve dispute">
        <p className="mb-4 text-sm text-slate-600">
          Recording a decision notifies both parties and closes the case on task{" "}
          <span className="font-mono text-xs">{resolving?.task_id.slice(0, 8)}…</span>
        </p>
        <div className="space-y-4">
          <Field label="Outcome" htmlFor="dispute-outcome">
            <Select id="dispute-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="RESOLVED">Resolved — complaint upheld, action taken</option>
              <option value="UNDER_REVIEW">Keep under review</option>
              <option value="REJECTED">Rejected — no violation found</option>
            </Select>
          </Field>
          <Field label="Resolution note" htmlFor="dispute-note" hint="Shared with both parties in their notification.">
            <Textarea
              id="dispute-note"
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
                setNoteError(undefined);
              }}
              placeholder="e.g. Reviewed chat logs and location data; runner confirmed no-show. Task fee refunded to the customer."
            />
            {noteError && <p className="mt-1 text-xs text-red-600">{noteError}</p>}
          </Field>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setResolving(null)}>
            Cancel
          </Button>
          <Button
            loading={resolve.isPending}
            onClick={() => {
              if (note.trim().length < 5) {
                setNoteError("A resolution note of at least 5 characters is required.");
                return;
              }
              if (resolving) resolve.mutate({ disputeId: resolving.id, outcome, note: note.trim() });
            }}
          >
            Record decision
          </Button>
        </div>
      </Modal>
    </div>
  );
}
