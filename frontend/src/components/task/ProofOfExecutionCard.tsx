import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Camera, CheckCircle2, MapPin, ShieldCheck } from "lucide-react";

import { PROOF_UPLOAD_STATUSES } from "@/lib/constants";
import { cn, errorMessage, formatDateTime } from "@/lib/utils";
import { Button, Card } from "@/components/ui";
import { PrivateImage } from "@/components/task/PrivateFile";
import { tasksApi } from "@/api/tasks";
import { toast } from "@/stores/toast";
import type { Task } from "@/types";

export function ProofOfExecutionCard({
  task,
  isWorker,
  isCustomer,
}: {
  task: Task;
  isWorker: boolean;
  isCustomer: boolean;
}) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);

  const proofs = task.execution_proofs ?? [];
  const canUpload = isWorker && PROOF_UPLOAD_STATUSES.includes(task.status);
  const canRequestCompletion = isWorker && task.status === "IN_PROGRESS";

  const requestMutation = useMutation({
    mutationFn: () => tasksApi.requestCompletion(task.id),
    onSuccess: () => {
      toast.success("Completion requested. Ask your customer for the 4-digit completion code.");
      void queryClient.invalidateQueries({ queryKey: ["task", task.id] });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const upload = async (file: File) => {
    setUploading(true);
    try {
      await tasksApi.uploadProof(task.id, file);
      toast.success("Proof photo verified and stored privately.");
      void queryClient.invalidateQueries({ queryKey: ["task", task.id] });
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  if (!canUpload && proofs.length === 0) return null;

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Proof of execution</h2>
        {proofs.length > 0 && (
          <span className="flex items-center gap-1 text-xs font-medium text-emerald-600">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> {proofs.length} verified photo{proofs.length > 1 ? "s" : ""}
          </span>
        )}
      </div>

      {proofs.length > 0 ? (
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          {proofs.map((proof) => (
            <div key={proof.id} className="overflow-hidden rounded-lg border border-slate-200">
              <PrivateImage
                queryKey={["proof-file", task.id, proof.id]}
                fetcher={() => tasksApi.proofFile(task.id, proof.id)}
                alt="Proof of execution"
                className="h-28 w-full sm:h-32"
              />
              <div className="space-y-0.5 bg-slate-50 px-2 py-1.5 text-[10px] text-slate-500">
                <p className="flex items-center gap-1">
                  <MapPin className="h-3 w-3" aria-hidden />
                  {proof.latitude != null && proof.longitude != null
                    ? `${proof.latitude.toFixed(5)}, ${proof.longitude.toFixed(5)}`
                    : "Location recorded"}
                </p>
                <p>{proof.captured_at ? formatDateTime(proof.captured_at) : formatDateTime(proof.created_at)}</p>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-sm text-slate-500">
          No proof photos yet. A location-tagged photo taken at the task site is required before completion.
        </p>
      )}

      {canUpload && (
        <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4">
          <p className="flex items-center gap-2 text-sm font-medium text-slate-800">
            <Camera className="h-4 w-4 text-primary-600" aria-hidden /> Capture evidence at the work site
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Location tagging (GPS) must be on for your camera. Photos are checked against the task location
            (within 500 m), re-encoded to strip metadata, and stored privately — only the customer sees them.
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            capture="environment"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void upload(file);
            }}
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              variant="secondary"
              loading={uploading}
              onClick={() => fileInputRef.current?.click()}
            >
              <Camera className="mr-1.5 h-4 w-4" aria-hidden /> Take / choose photo
            </Button>
            {canRequestCompletion && (
              <Button
                loading={requestMutation.isPending}
                disabled={proofs.length === 0}
                onClick={() => requestMutation.mutate()}
              >
                <CheckCircle2 className="mr-1.5 h-4 w-4" aria-hidden /> Request completion
              </Button>
            )}
          </div>
          {canRequestCompletion && proofs.length === 0 && (
            <p className="mt-2 text-xs text-amber-700">Upload at least one valid proof photo to request completion.</p>
          )}
        </div>
      )}

      {task.status === "COMPLETION_REQUESTED" && (
        <p className="mt-3 rounded-lg bg-violet-50 px-3 py-2 text-xs text-violet-800">
          {isCustomer
            ? "Review the photos above, then share the completion code from the handshake panel."
            : "Completion requested. Ask your customer to read out the 4-digit completion code."}
        </p>
      )}

      {task.status === "COMPLETED" && proofs.length > 0 && (
        <p className={cn("mt-3 text-xs text-slate-500", isWorker && "text-slate-500")}>
          Evidence retained privately with this task.
        </p>
      )}
    </Card>
  );
}
