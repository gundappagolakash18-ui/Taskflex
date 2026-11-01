import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleDollarSign, Info, Send } from "lucide-react";

import { bidsApi } from "@/api/bids";
import { Badge, Button, Field, Input, Modal, Textarea } from "@/components/ui";
import { errorMessage, formatMoney } from "@/lib/utils";
import { toast } from "@/stores/toast";
import type { Task } from "@/types";

const QUICK_DELTAS = [30, 50, 100];

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export default function BidComposer({
  task,
  open,
  onClose,
}: {
  task: Task;
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const budget = Number(task.budget);
  const minBid = Math.ceil(budget + 10);
  const maxBid = Math.floor(budget * 1.5);
  const [amount, setAmount] = useState(() => String(clamp(Math.round(budget * 1.15), minBid, maxBid)));
  const [note, setNote] = useState("");
  const [eta, setEta] = useState("15");

  const existingQuery = useQuery({
    queryKey: ["my-bid", task.id],
    queryFn: () => bidsApi.myBid(task.id),
    enabled: open,
  });
  const existing = existingQuery.data ?? null;
  const pendingBid = existing && existing.status === "PENDING" ? existing : null;

  useEffect(() => {
    if (!open) return;
    setAmount(String(clamp(Math.round(budget * 1.15), minBid, maxBid)));
    setNote("");
    setEta("15");
  }, [open, budget, minBid, maxBid]);

  const numericAmount = Number(amount);
  const valid =
    Number.isFinite(numericAmount) &&
    numericAmount >= minBid &&
    numericAmount <= maxBid &&
    numericAmount <= 1_000_000;
  const tooHigh = Number.isFinite(numericAmount) && numericAmount > maxBid;
  const tooLow = Number.isFinite(numericAmount) && numericAmount < minBid;

  const mutation = useMutation({
    mutationFn: () =>
      bidsApi.place(task.id, {
        proposed_amount: numericAmount,
        note: note.trim() || null,
        estimated_arrival_minutes: Number(eta) || 0,
      }),
    onSuccess: () => {
      toast.success("Counter-offer sent — the customer has 45 seconds to respond.");
      void queryClient.invalidateQueries({ queryKey: ["worker-offers"] });
      void queryClient.invalidateQueries({ queryKey: ["worker-bids"] });
      void queryClient.invalidateQueries({ queryKey: ["my-bid", task.id] });
      onClose();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const quickOptions = useMemo(
    () =>
      QUICK_DELTAS.map((delta) => {
        const value = Math.min(maxBid, Math.ceil(budget + delta));
        return { delta, value, disabled: value <= budget };
      }),
    [budget, maxBid]
  );

  return (
    <Modal open={open} onClose={onClose} title="Send a counter-offer">
      <div className="space-y-4">
        <div className="rounded-xl bg-slate-50 p-3">
          <p className="text-sm font-semibold text-slate-900">{task.title}</p>
          <p className="mt-0.5 text-xs text-slate-500">
            Customer's budget <span className="font-semibold text-slate-700">{formatMoney(budget, task.currency)}</span> ·
            You'd receive the full counter-offer amount less the platform fee.
          </p>
        </div>

        {pendingBid ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
            <p className="text-sm font-semibold text-amber-900">Counter-offer already pending</p>
            <p className="mt-1 text-sm text-amber-800">
              You offered <span className="font-bold">{formatMoney(pendingBid.proposed_amount, task.currency)}</span>. The
              customer has until {pendingBid.expires_at ? new Date(pendingBid.expires_at).toLocaleTimeString() : "soon"} to
              respond. You can still accept or decline the normal offer.
            </p>
          </div>
        ) : (
          <>
            <div>
              <p className="text-sm font-medium text-slate-700">Your price</p>
              <p className="mt-0.5 text-xs text-slate-500">
                Allowed range {formatMoney(minBid, task.currency)} – {formatMoney(maxBid, task.currency)} (budget + ₹10 up
                to 1.5× the budget).
              </p>
              <div className="mt-2 grid grid-cols-3 gap-2">
                {quickOptions.map((option) => (
                  <button
                    key={option.delta}
                    type="button"
                    disabled={option.disabled}
                    onClick={() => setAmount(String(option.value))}
                    className={
                      Number(amount) === option.value
                        ? "rounded-lg border border-primary-500 bg-primary-50 px-2 py-2 text-sm font-semibold text-primary-700"
                        : "rounded-lg border border-slate-200 bg-white px-2 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                    }
                  >
                    +₹{option.delta}
                    <span className="block text-[10px] font-normal text-slate-400">
                      {formatMoney(option.value, task.currency)}
                    </span>
                  </button>
                ))}
              </div>
              <div className="relative mt-3">
                <CircleDollarSign className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden />
                <Input
                  className="pl-9"
                  type="number"
                  min={minBid}
                  max={maxBid}
                  step="1"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  aria-label="Counter-offer amount"
                />
              </div>
              {tooLow && <p className="mt-1 text-xs text-red-600">Minimum counter-offer is {formatMoney(minBid, task.currency)}.</p>}
              {tooHigh && <p className="mt-1 text-xs text-red-600">Maximum counter-offer is {formatMoney(maxBid, task.currency)}.</p>}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Note (optional)" htmlFor="bid-note">
                <Textarea
                  id="bid-note"
                  rows={2}
                  maxLength={140}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="e.g. I'm 1 km away and can start immediately."
                />
              </Field>
              <Field label="Arrival in (minutes)" htmlFor="bid-eta">
                <Input
                  id="bid-eta"
                  type="number"
                  min={0}
                  max={600}
                  value={eta}
                  onChange={(e) => setEta(e.target.value)}
                />
              </Field>
            </div>

            <div className="flex items-start gap-2 rounded-lg bg-indigo-50 px-3 py-2 text-xs text-indigo-800">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              Accepting the customer's offer is still the fastest way to win. A counter-offer waits for their decision.
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button
                loading={mutation.isPending}
                disabled={!valid}
                onClick={() => mutation.mutate()}
              >
                <Send className="h-4 w-4" aria-hidden /> Send counter-offer
              </Button>
            </div>
          </>
        )}

        {existing && !pendingBid && existingQuery.isFetched && (
          <Badge className="bg-slate-100 text-slate-600">Last bid status: {existing.status.toLowerCase()}</Badge>
        )}
      </div>
    </Modal>
  );
}
