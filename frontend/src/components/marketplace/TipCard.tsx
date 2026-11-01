import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Gift, HeartHandshake, IndianRupee } from "lucide-react";

import { paymentsApi } from "@/api";
import { tasksApi } from "@/api/tasks";
import { openRazorpayCheckout } from "@/lib/razorpay";
import { Button, Card, Input } from "@/components/ui";
import { cn, errorMessage, formatMoney } from "@/lib/utils";
import { toast } from "@/stores/toast";
import { useAuthStore } from "@/stores/auth";
import type { Task } from "@/types";

const PRESETS = [20, 50, 100];

export default function TipCard({ task }: { task: Task }) {
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const [amount, setAmount] = useState(50);
  const [custom, setCustom] = useState("");

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["task", task.id] });
    void queryClient.invalidateQueries({ queryKey: ["wallet"] });
    void queryClient.invalidateQueries({ queryKey: ["transactions"] });
    void queryClient.invalidateQueries({ queryKey: ["worker-earnings"] });
  };

  const mutation = useMutation({
    mutationFn: (value: number) => tasksApi.tip(task.id, value),
    onSuccess: async (result) => {
      if (result.tip.settled) {
        toast.success("Tip sent — 100% reached your runner. No commission taken.");
        invalidate();
        return;
      }
      if (result.payment?.required && result.payment.key_id && result.payment.order_id) {
        try {
          await openRazorpayCheckout({
            key_id: result.payment.key_id,
            order_id: result.payment.order_id,
            amount: result.payment.amount ?? Math.round(result.tip.amount * 100),
            currency: result.payment.currency ?? task.currency,
            name: result.payment.name ?? "TaskFlex tip",
            description: result.payment.description ?? `Tip for ${task.title}`,
            prefill: {
              name: result.payment.prefill?.name ?? user?.full_name,
              email: result.payment.prefill?.email ?? user?.email,
            },
            onSuccess: async (payload) => {
              try {
                await paymentsApi.verify(payload);
                toast.success("Tip paid — your runner receives the full amount.");
                invalidate();
              } catch (error) {
                toast.error(errorMessage(error));
              }
            },
            onDismiss: () => toast.info("Tip payment not completed. You can retry anytime before the task closes."),
            onFailure: (message) => toast.error(message),
          });
        } catch (error) {
          toast.error(errorMessage(error));
        }
      } else {
        toast.success("Tip recorded — it's held in escrow and released when the task completes.");
      }
      invalidate();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const numericCustom = Number(custom);
  const effectiveAmount = custom.trim() ? numericCustom : amount;
  const valid = Number.isFinite(effectiveAmount) && effectiveAmount >= 1 && effectiveAmount <= 50_000;
  const totalTip = Number(task.tip_amount ?? 0);

  return (
    <Card className="border-rose-200 bg-rose-50/40">
      <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-rose-500">
        <Gift className="h-4 w-4" aria-hidden /> Tip your runner
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        100% of every tip goes to your runner — TaskFlex takes no commission.{" "}
        {task.status === "COMPLETED"
          ? "Post-task tips are settled instantly."
          : "In-flight tips are held with your payment and settle at completion."}
      </p>

      {totalTip > 0 && (
        <p className="mt-2 rounded-lg bg-white px-3 py-2 text-xs font-medium text-rose-700">
          You have tipped {formatMoney(totalTip, task.currency)} on this task so far.
        </p>
      )}

      <div className="mt-3 grid grid-cols-3 gap-2">
        {PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            onClick={() => {
              setAmount(preset);
              setCustom("");
            }}
            className={cn(
              "rounded-xl border px-2 py-2.5 text-sm font-bold transition",
              !custom.trim() && amount === preset
                ? "border-rose-400 bg-white text-rose-700 shadow-sm"
                : "border-rose-200 bg-white/70 text-slate-700 hover:border-rose-300"
            )}
          >
            +₹{preset}
          </button>
        ))}
      </div>

      <div className="mt-2 flex gap-2">
        <div className="relative flex-1">
          <IndianRupee className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden />
          <Input
            className="bg-white pl-9"
            type="number"
            min={1}
            max={50000}
            placeholder="Custom tip"
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            aria-label="Custom tip amount"
          />
        </div>
        <Button
          className="shrink-0 bg-rose-600 hover:bg-rose-700"
          loading={mutation.isPending}
          disabled={!valid}
          onClick={() => mutation.mutate(effectiveAmount)}
        >
          <HeartHandshake className="h-4 w-4" aria-hidden /> Send {formatMoney(valid ? effectiveAmount : 0, task.currency)}
        </Button>
      </div>
      <p className="mt-2 text-[11px] text-slate-400">Tips are voluntary and never affect your task terms.</p>
    </Card>
  );
}
