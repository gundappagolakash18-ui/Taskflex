import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Clock, Gavel, MapPin, Star, X } from "lucide-react";

import { bidsApi } from "@/api/bids";
import { Badge, Button, Card, EmptyState, SkeletonList } from "@/components/ui";
import { BID_WINDOW_SECONDS, TIER_ICONS, TIER_LABELS, WS_EVENTS } from "@/lib/constants";
import { cn, errorMessage, formatMoney } from "@/lib/utils";
import { toast } from "@/stores/toast";
import { wsService } from "@/services/websocket";
import type { Task, TaskBid } from "@/types";

function remainingSeconds(bid: TaskBid, now: number): number {
  if (!bid.expires_at) return 0;
  return Math.max(0, Math.ceil((new Date(bid.expires_at).getTime() - now) / 1000));
}

function totalSeconds(bid: TaskBid): number {
  if (!bid.expires_at || !bid.created_at) return BID_WINDOW_SECONDS;
  const total = Math.floor((new Date(bid.expires_at).getTime() - new Date(bid.created_at).getTime()) / 1000);
  return total > 0 ? total : BID_WINDOW_SECONDS;
}

function countdownLabel(seconds: number): string {
  if (seconds >= 60) {
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  }
  return `${seconds}s`;
}

function BidCountdown({ bid, now }: { bid: TaskBid; now: number }) {
  const remaining = remainingSeconds(bid, now);
  const total = totalSeconds(bid);
  const fraction = total > 0 ? Math.min(1, remaining / total) : 0;
  const tone =
    fraction > 0.5 ? "stroke-emerald-500" : fraction > 0.2 ? "stroke-amber-500" : "stroke-red-500";
  const radius = 15;
  const circumference = 2 * Math.PI * radius;

  return (
    <div className="relative h-10 w-10 shrink-0" role="timer" aria-label={`${remaining} seconds left for this bid`}>
      <svg viewBox="0 0 38 38" className="h-10 w-10 -rotate-90" aria-hidden>
        <circle cx="19" cy="19" r={radius} fill="none" strokeWidth="3.5" className="stroke-slate-200" />
        <circle
          cx="19"
          cy="19"
          r={radius}
          fill="none"
          strokeWidth="3.5"
          strokeLinecap="round"
          className={cn("transition-[stroke-dashoffset] duration-500 ease-linear", tone)}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - fraction)}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-[9px] font-bold tabular-nums text-slate-700">
        {countdownLabel(remaining)}
      </span>
    </div>
  );
}

export default function CustomerBidStack({ task, enabled }: { task: Task; enabled: boolean }) {
  const queryClient = useQueryClient();
  const [now, setNow] = useState(() => Date.now());
  const [busyId, setBusyId] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["task-bids", task.id],
    queryFn: () => bidsApi.forTask(task.id),
    enabled,
    refetchInterval: enabled ? 5_000 : false,
  });

  const bids = useMemo(
    () => (query.data?.items ?? []).filter((bid) => bid.status === "PENDING"),
    [query.data?.items]
  );

  useEffect(() => {
    if (!enabled) return;
    const invalidate = () => void queryClient.invalidateQueries({ queryKey: ["task-bids", task.id] });
    const offBid = wsService.on(WS_EVENTS.TASK_BID_RECEIVED, (frame) => {
      const data = frame.data as { task_id?: string };
      if (data.task_id === task.id) invalidate();
    });
    const offStatus = wsService.on(WS_EVENTS.TASK_STATUS, (frame) => {
      const data = frame.data as { task_id?: string };
      if (data.task_id === task.id) invalidate();
    });
    return () => {
      offBid();
      offStatus();
    };
  }, [enabled, task.id, queryClient]);

  useEffect(() => {
    if (bids.length === 0) return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [bids.length]);

  useEffect(() => {
    if (bids.length === 0) return;
    if (bids.every((bid) => remainingSeconds(bid, now) > 0)) return;
    const timer = window.setTimeout(
      () => void queryClient.invalidateQueries({ queryKey: ["task-bids", task.id] }),
      1200
    );
    return () => window.clearTimeout(timer);
  }, [bids, now, queryClient, task.id]);

  const acceptMutation = useMutation({
    mutationFn: (bidId: string) => bidsApi.accept(bidId),
    onSuccess: (updated) => {
      toast.success(`Counter-offer accepted — ${updated.worker?.full_name ?? "your runner"} is assigned at ${formatMoney(updated.budget, updated.currency)}.`);
      void queryClient.invalidateQueries({ queryKey: ["task", task.id] });
      void queryClient.invalidateQueries({ queryKey: ["task-bids", task.id] });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["task-payment", task.id] });
      void queryClient.invalidateQueries({ queryKey: ["wallet"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
    onSettled: () => setBusyId(null),
  });

  const declineMutation = useMutation({
    mutationFn: (bidId: string) => bidsApi.decline(bidId),
    onSuccess: () => {
      toast.info("Counter-offer declined.");
      void queryClient.invalidateQueries({ queryKey: ["task-bids", task.id] });
    },
    onError: (error) => toast.error(errorMessage(error)),
    onSettled: () => setBusyId(null),
  });

  if (!enabled) return null;

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
          <Gavel className="h-4 w-4" aria-hidden /> Counter-offers
        </h2>
        <Badge className="bg-indigo-50 text-indigo-700">
          {bids.length} active · respond within 45 s
        </Badge>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Runners can bid above your budget. Accepting one assigns that runner instantly at the agreed price; the extra
        amount is held in escrow and only released when you approve completion.
      </p>

      {query.isLoading ? (
        <div className="mt-3">
          <SkeletonList rows={2} />
        </div>
      ) : bids.length === 0 ? (
        <div className="mt-3">
          <EmptyState
            icon="🤝"
            title="No counter-offers yet"
            description="We're still ringing nearby runners with your budget. A counter-offer will pop up here the moment one lands."
          />
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          {bids.map((bid) => {
            const remaining = remainingSeconds(bid, now);
            const expired = remaining <= 0;
            const urgent = remaining > 0 && remaining <= 10;
            const busy = busyId === bid.id;
            return (
              <div
                key={bid.id}
                className={cn(
                  "rounded-xl border p-4 transition",
                  expired ? "border-slate-200 bg-slate-50 opacity-70" : "border-indigo-200 bg-white",
                  urgent && "border-red-300 ring-1 ring-red-100"
                )}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    {bid.worker_avatar ? (
                      <img src={bid.worker_avatar} alt={bid.worker_name ?? "Runner"} className="h-11 w-11 rounded-full object-cover" />
                    ) : (
                      <div className="flex h-11 w-11 items-center justify-center rounded-full bg-indigo-100 text-sm font-bold text-indigo-700">
                        {(bid.worker_name ?? "R")
                          .split(" ")
                          .filter(Boolean)
                          .slice(0, 2)
                          .map((part) => part[0]!.toUpperCase())
                          .join("")}
                      </div>
                    )}
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm font-bold text-slate-900">{bid.worker_name ?? "Runner"}</p>
                        {bid.worker_tier && (
                          <Badge className="bg-amber-50 text-amber-800">
                            {TIER_ICONS[bid.worker_tier] ?? ""} {TIER_LABELS[bid.worker_tier] ?? bid.worker_tier}
                          </Badge>
                        )}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                        <span className="flex items-center gap-1 text-amber-600">
                          <Star className="h-3 w-3 fill-amber-400 text-amber-400" aria-hidden />
                          {bid.worker_rating.toFixed(1)} ({bid.worker_rating_count})
                        </span>
                        <span>{bid.worker_completed_tasks} tasks done</span>
                        {bid.distance_km != null && (
                          <span className="flex items-center gap-1">
                            <MapPin className="h-3 w-3" aria-hidden /> {bid.distance_km.toFixed(1)} km away
                          </span>
                        )}
                        {bid.estimated_arrival_minutes > 0 && <span>~{bid.estimated_arrival_minutes} min away</span>}
                      </div>
                      {bid.note && <p className="mt-1.5 text-xs text-slate-600">“{bid.note}”</p>}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="text-right">
                      <p className="text-lg font-bold text-slate-900">{formatMoney(bid.proposed_amount, task.currency)}</p>
                      <p className="text-[11px] text-slate-400">budget {formatMoney(task.budget, task.currency)}</p>
                    </div>
                    <BidCountdown bid={bid} now={now} />
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                  <span
                    className={cn(
                      "flex items-center gap-1 text-xs",
                      expired ? "text-red-600" : urgent ? "text-red-600 font-semibold" : "text-slate-500"
                    )}
                  >
                    <Clock className="h-3.5 w-3.5" aria-hidden />
                    {expired ? "Bid window closed" : urgent ? `Only ${remaining}s left to respond!` : `Respond within ${countdownLabel(remaining)}`}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      disabled={busy || expired}
                      onClick={() => {
                        setBusyId(bid.id);
                        declineMutation.mutate(bid.id);
                      }}
                    >
                      <X className="h-4 w-4" aria-hidden /> Decline
                    </Button>
                    <Button
                      disabled={busy || expired}
                      loading={busy && acceptMutation.isPending}
                      onClick={() => {
                        setBusyId(bid.id);
                        acceptMutation.mutate(bid.id);
                      }}
                    >
                      <Check className="h-4 w-4" aria-hidden /> Accept at {formatMoney(bid.proposed_amount, task.currency)}
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
