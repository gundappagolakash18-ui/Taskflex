import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, RefreshCw, RotateCcw } from "lucide-react";

import { tasksApi } from "@/api/tasks";
import { OtpEntryModal } from "@/components/task/OtpEntryModal";
import { Button, Card } from "@/components/ui";
import { errorMessage } from "@/lib/utils";
import { toast } from "@/stores/toast";
import type { Task } from "@/types";

export default function ReturnHandbackCard({
  task,
  isWorker,
  isCustomer,
}: {
  task: Task;
  isWorker: boolean;
  isCustomer: boolean;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  if (!task.is_round_trip) return null;

  const verified = Boolean(task.return_otp_verified_at);
  const active = ["IN_PROGRESS", "COMPLETION_REQUESTED"].includes(task.status);

  const mutation = useMutation({
    mutationFn: (otp: string) => tasksApi.verifyReturnOtp(task.id, otp),
    onSuccess: () => {
      toast.success("Return handback verified — the task can now be completed and paid out.");
      setOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["task", task.id] });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (verified) {
    return (
      <Card className="border-emerald-200 bg-emerald-50">
        <p className="flex items-center gap-2 text-sm font-semibold text-emerald-900">
          <CheckCircle2 className="h-4 w-4" aria-hidden /> Return handback complete
        </p>
        <p className="mt-1 text-sm text-emerald-800">
          The goods were returned to the pickup point and the customer's return code was verified. Normal completion
          applies from here.
        </p>
      </Card>
    );
  }

  if (isCustomer && active && task.return_otp_display) {
    return (
      <Card className="border-teal-200 bg-teal-50">
        <p className="flex items-center gap-2 text-sm font-semibold text-teal-900">
          <RotateCcw className="h-4 w-4" aria-hidden /> Round-trip return handback
        </p>
        <p className="mt-1 text-sm text-teal-800">
          When your runner brings the goods back to the pickup point, read them this 4-digit return code. The payout
          cannot be released until this handshake completes.
        </p>
        <div className="mt-3 flex items-center justify-between gap-3 rounded-xl bg-white px-4 py-3">
          <span className="text-3xl font-bold tracking-[0.45em] text-slate-900" aria-label="Return handback code">
            {task.return_otp_display}
          </span>
          <Button
            variant="secondary"
            onClick={() => {
              void navigator.clipboard?.writeText(task.return_otp_display ?? "").then(
                () => toast.success("Return code copied."),
                () => toast.info(`Code: ${task.return_otp_display}`)
              );
            }}
          >
            Copy
          </Button>
        </div>
        {task.return_otp_locked && (
          <p className="mt-2 rounded-lg bg-red-100 px-3 py-2 text-xs font-medium text-red-800">
            Too many wrong attempts — the handshake is locked for now and unlocks automatically.
          </p>
        )}
      </Card>
    );
  }

  if (isWorker && active) {
    return (
      <>
        <Card className="border-teal-200 bg-teal-50">
          <p className="flex items-center gap-2 text-sm font-semibold text-teal-900">
            <RotateCcw className="h-4 w-4" aria-hidden /> Return handback required
          </p>
          <p className="mt-1 text-sm text-teal-800">
            This is a round-trip errand. Once you're back at the pickup point with the goods, ask the customer for their
            4-digit return code. The completion code will be rejected until this is verified.
          </p>
          <Button className="mt-3 w-full" onClick={() => { mutation.reset(); setOpen(true); }}>
            <KeyRound className="h-4 w-4" aria-hidden /> Enter return handback code
          </Button>
        </Card>
        <OtpEntryModal
          open={open}
          title="Return handback code"
          description="Enter the customer's 4-digit return code after handing the goods back at the pickup point."
          confirmLabel="Verify handback"
          loading={mutation.isPending}
          error={mutation.error ? errorMessage(mutation.error) : null}
          onClose={() => setOpen(false)}
          onSubmit={(otp) => mutation.mutate(otp)}
        />
      </>
    );
  }

  if (task.status === "COMPLETION_REQUESTED" && isWorker) {
    return (
      <Card className="border-amber-200 bg-amber-50">
        <p className="flex items-center gap-2 text-sm font-semibold text-amber-900">
          <RefreshCw className="h-4 w-4" aria-hidden /> Return handback still pending
        </p>
        <p className="mt-1 text-sm text-amber-800">
          Verify the customer's return code before completion can be released.
        </p>
      </Card>
    );
  }

  return null;
}
