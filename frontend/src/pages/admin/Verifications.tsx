import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FileText } from "lucide-react";
import { adminApi } from "@/api/admin";
import { api } from "@/api/client";
import { Badge, Button, Card, EmptyState, Field, Modal, PageLoader, Textarea } from "@/components/ui";
import { errorMessage } from "@/lib/utils";
import { toast } from "@/stores/toast";
import type { PendingDocument } from "@/api/admin";

const DOC_LABELS: Record<string, string> = {
  id_card: "ID card",
  address_proof: "Address proof",
  police_clearance: "Police clearance",
  other: "Other document",
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function openDocument(documentId: string): Promise<void> {
  const response = await api.get(`/uploads/documents/${documentId}`, { responseType: "blob" });
  const url = URL.createObjectURL(response.data as Blob);
  window.open(url, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export default function Verifications() {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [rejecting, setRejecting] = useState<PendingDocument | null>(null);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | undefined>();

  const pending = useQuery({
    queryKey: ["admin-verifications", page],
    queryFn: () => adminApi.pendingVerifications(page, 20),
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["admin-verifications"] });
    void qc.invalidateQueries({ queryKey: ["admin-workers"] });
    void qc.invalidateQueries({ queryKey: ["admin-dashboard"] });
  };

  const approve = useMutation({
    mutationFn: (doc: PendingDocument) => adminApi.decideVerification(doc.id, true),
    onSuccess: () => {
      toast.success("Document approved.");
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const reject = useMutation({
    mutationFn: ({ doc, note }: { doc: PendingDocument; note: string }) =>
      adminApi.decideVerification(doc.id, false, note),
    onSuccess: () => {
      toast.success("Document rejected. The worker has been notified.");
      setRejecting(null);
      setReason("");
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const rows = pending.data?.items ?? [];
  const total = pending.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 20));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Verifications</h1>
        <p className="text-sm text-slate-500">
          {total} document{total === 1 ? "" : "s"} awaiting review
        </p>
      </div>

      {pending.isLoading ? (
        <PageLoader />
      ) : rows.length === 0 ? (
        <EmptyState
          icon="✅"
          title="Queue is clear"
          description="No verification documents are waiting. New submissions will appear here."
        />
      ) : (
        <div className="space-y-3">
          {rows.map((doc) => (
            <Card key={doc.id} className="p-4">
              <div className="flex flex-wrap items-center gap-4">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
                  <FileText className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold text-slate-800">{DOC_LABELS[doc.document_type] ?? doc.document_type}</p>
                    <Badge className="bg-amber-100 text-amber-700">{doc.status.toLowerCase()}</Badge>
                    <Badge className="bg-slate-100 text-slate-600">{doc.mime_type.split("/")[1]?.toUpperCase() ?? doc.mime_type}</Badge>
                  </div>
                  <p className="truncate text-xs text-slate-500">
                    {doc.worker_name ?? "Unknown worker"} · {doc.file_name} · {formatSize(doc.file_size)} ·{" "}
                    {new Date(doc.created_at).toLocaleString()}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    className="text-xs"
                    onClick={() => openDocument(doc.id).catch(() => toast.error("Could not open document."))}
                  >
                    <ExternalLink className="mr-1 h-3.5 w-3.5" /> Review
                  </Button>
                  <Button
                    variant="secondary"
                    className="text-xs"
                    loading={approve.isPending && approve.variables?.id === doc.id}
                    onClick={() => approve.mutate(doc)}
                  >
                    Approve
                  </Button>
                  <Button variant="danger" className="text-xs" onClick={() => setRejecting(doc)}>
                    Reject
                  </Button>
                </div>
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

      <Modal open={rejecting !== null} onClose={() => setRejecting(null)} title="Reject document">
        <p className="mb-4 text-sm text-slate-600">
          Explain what is wrong with{" "}
          <span className="font-semibold">{rejecting ? DOC_LABELS[rejecting.document_type] ?? rejecting.document_type : ""}</span> so{" "}
          {rejecting?.worker_name ?? "the worker"} can resubmit.
        </p>
        <Field label="Reason" htmlFor="reject-reason">
          <Textarea
            id="reject-reason"
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
              setReasonError(undefined);
            }}
            placeholder="e.g. The ID photo is blurry — please retake it in daylight."
          />
          {reasonError && <p className="mt-1 text-xs text-red-600">{reasonError}</p>}
        </Field>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setRejecting(null)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            loading={reject.isPending}
            onClick={() => {
              if (reason.trim().length < 5) {
                setReasonError("Please give a reason of at least 5 characters.");
                return;
              }
              if (rejecting) reject.mutate({ doc: rejecting, note: reason.trim() });
            }}
          >
            Reject document
          </Button>
        </div>
      </Modal>
    </div>
  );
}
