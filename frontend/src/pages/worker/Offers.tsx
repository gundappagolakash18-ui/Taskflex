import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Check, Clock, Gavel, MapPin, Star, X, Zap } from "lucide-react";

import { TASK_TYPE_ICONS, TASK_TYPE_LABELS, WS_EVENTS } from "@/lib/constants";
import { cn, errorMessage, formatMoney, scorePercent } from "@/lib/utils";
import { Badge, Button, Card, EmptyState, PageLoader } from "@/components/ui";
import { workersApi } from "@/api/workers";
import BidComposer from "@/components/marketplace/BidComposer";
import { toast } from "@/stores/toast";
import { wsService } from "@/services/websocket";
import type { OfferWithTask, Task } from "@/types";

const DEFAULT_WINDOW_SECONDS = 30;

function secondsBetween(expiresAt: string | null, from: number): number | null {
  if (!expiresAt) return null;
  return Math.max(0, Math.ceil((new Date(expiresAt).getTime() - from) / 1000));
}

function windowSeconds(pair: OfferWithTask): number {
  const { expires_at, created_at } = pair.offer;
  if (!expires_at) return 0;
  const total = Math.floor((new Date(expires_at).getTime() - new Date(created_at).getTime()) / 1000);
  return total > 0 ? total : DEFAULT_WINDOW_SECONDS;
}

function countdownLabel(seconds: number): string {
  if (seconds >= 60) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${String(secs).padStart(2, "0")}`;
  }
  return String(seconds);
}

function CountdownRing({ remaining, total }: { remaining: number; total: number }) {
  const radius = 18;
  const circumference = 2 * Math.PI * radius;
  const fraction = total > 0 ? Math.min(1, remaining / total) : 0;
  const tone =
    fraction > 0.5 ? "stroke-emerald-500" : fraction > 0.2 ? "stroke-amber-500" : "stroke-red-500";
  const textTone =
    fraction > 0.5 ? "text-emerald-700" : fraction > 0.2 ? "text-amber-700" : "text-red-600";

  return (
    <div
      className="relative h-12 w-12 shrink-0"
      role="timer"
      aria-label={`${remaining} seconds left to respond`}
    >
      <svg viewBox="0 0 44 44" className="h-12 w-12 -rotate-90" aria-hidden>
        <circle cx="22" cy="22" r={radius} fill="none" strokeWidth="4" className="stroke-slate-200" />
        <circle
          cx="22"
          cy="22"
          r={radius}
          fill="none"
          strokeWidth="4"
          strokeLinecap="round"
          className={cn("transition-[stroke-dashoffset] duration-500 ease-linear", tone)}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - fraction)}
        />
      </svg>
      <span
        className={cn(
          "absolute inset-0 flex items-center justify-center text-[10px] font-bold tabular-nums",
          textTone
        )}
      >
        {countdownLabel(remaining)}
      </span>
    </div>
  );
}

function OfferCard({
  pair,
  now,
  onAccept,
  onReject,
  onCounter,
  busy,
}: {
  pair: OfferWithTask;
  now: number;
  onAccept: (offerId: string, taskId: string) => void;
  onReject: (offerId: string) => void;
  onCounter: (task: Task) => void;
  busy: boolean;
}) {
  const { offer, task } = pair;
  const total = windowSeconds(pair);
  const remaining = secondsBetween(offer.expires_at, now);
  const expired = remaining !== null && remaining <= 0;
  const urgent = remaining !== null && remaining <= 10 && !expired;

  return (
    <Card
      className={cn(
        "relative overflow-hidden transition",
        expired && "opacity-60",
        urgent && "border-red-300 ring-1 ring-red-200"
      )}
    >
      {urgent && (
        <span className="absolute inset-x-0 top-0 h-1 animate-pulse bg-red-500" aria-hidden />
      )}
      {offer.badge && !expired && (
        <div className="mb-3 flex items-center gap-2 rounded-lg bg-gradient-to-r from-amber-100 to-orange-100 px-3 py-2 text-xs font-bold text-amber-900">
          <Star className="h-3.5 w-3.5 fill-amber-500 text-amber-500" aria-hidden />
          {offer.badge}
        </div>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-2xl">
            {TASK_TYPE_ICONS[task.task_type] ?? "🧭"}
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-bold text-slate-900">{task.title}</p>
            <p className="mt-0.5 text-xs text-slate-500">
              {TASK_TYPE_LABELS[task.task_type] ?? task.task_type}
              {task.area_name ? ` · ${task.area_name}` : ""}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <p className="text-xl font-bold text-slate-900">{formatMoney(task.budget, task.currency)}</p>
            <p className="text-xs text-slate-400">you'd receive {formatMoney(task.worker_payout_amount, task.currency)}</p>
            {offer.estimated_earnings != null && (
              <p className="text-[11px] font-medium text-emerald-600">
                est. {formatMoney(offer.estimated_earnings, task.currency)} incl. chaining
              </p>
            )}
          </div>
          {remaining !== null && <CountdownRing remaining={remaining} total={total || DEFAULT_WINDOW_SECONDS} />}
        </div>
      </div>

      <p className="mt-3 line-clamp-2 text-sm text-slate-600">{task.description}</p>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <Badge className="bg-indigo-50 text-indigo-700">
          <Star className="h-3 w-3" aria-hidden /> {scorePercent(offer.match_score)}% match
        </Badge>
        {remaining !== null && (
          <Badge
            className={cn(
              expired
                ? "bg-red-50 text-red-600"
                : urgent
                  ? "bg-red-100 text-red-700"
                  : "bg-slate-100 text-slate-600"
            )}
          >
            <Clock className="h-3 w-3" aria-hidden />
            {expired ? "Expired" : urgent ? `Only ${remaining}s left!` : `${countdownLabel(remaining)} left`}
          </Badge>
        )}
        {task.urgency === "urgent" && (
          <Badge className="bg-orange-100 text-orange-800">
            <Zap className="h-3 w-3" aria-hidden /> Urgent
          </Badge>
        )}
        {task.scheduled_date && (
          <Badge className="bg-slate-100 text-slate-600">
            <MapPin className="h-3 w-3" aria-hidden /> {task.scheduled_date}{task.scheduled_time ? ` ${task.scheduled_time}` : ""}
          </Badge>
        )}
      </div>

      <div className="mt-4 flex gap-2">
        <Button
          className="flex-1"
          disabled={expired}
          loading={busy}
          onClick={() => onAccept(offer.id, task.id)}
        >
          <Check className="mr-1.5 h-4 w-4" aria-hidden /> {expired ? "Offer expired" : "Accept"}
        </Button>
        <Button
          variant="secondary"
          className="flex-1"
          disabled={busy || expired}
          onClick={() => onCounter(task)}
        >
          <Gavel className="mr-1.5 h-4 w-4" aria-hidden /> Counter-offer
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => onReject(offer.id)} aria-label="Decline offer">
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </div>
      <p className="mt-2 text-center text-[11px] text-slate-400">
        First runner to accept wins. Declining quickly sends this errand to the next best match.
      </p>
    </Card>
  );
}

export default function WorkerOffers() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [bidTask, setBidTask] = useState<Task | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const expiredKeyRef = useRef("");

  const query = useQuery({
    queryKey: ["worker-offers"],
    queryFn: () => workersApi.myOffers(),
    refetchInterval: 10_000,
  });

  const items: OfferWithTask[] = query.data?.items ?? [];

  useEffect(() => {
    const off = wsService.on(WS_EVENTS.TASK_OFFER, () => {
      void queryClient.invalidateQueries({ queryKey: ["worker-offers"] });
    });
    const offStatus = wsService.on(WS_EVENTS.TASK_STATUS, () => {
      void queryClient.invalidateQueries({ queryKey: ["worker-offers"] });
    });
    return () => {
      off();
      offStatus();
    };
  }, [queryClient]);

  useEffect(() => {
    if (items.length === 0) return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [items.length]);

  useEffect(() => {
    const expiredIds = items
      .filter((pair) => {
        const expires = pair.offer.expires_at;
        return expires !== null && new Date(expires).getTime() <= now;
      })
      .map((pair) => pair.offer.id)
      .sort()
      .join(",");
    if (!expiredIds || expiredIds === expiredKeyRef.current) return;
    expiredKeyRef.current = expiredIds;
    void queryClient.invalidateQueries({ queryKey: ["worker-offers"] });
  }, [items, now, queryClient]);

  const acceptMutation = useMutation({
    mutationFn: (offerId: string) => workersApi.acceptOffer(offerId),
    onSuccess: (task) => {
      toast.success("Offer accepted — you've got the task!");
      void queryClient.invalidateQueries({ queryKey: ["worker-offers"] });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      navigate(`/worker/tasks/${task.id}`);
    },
    onError: (e) => {
      toast.error(errorMessage(e));
      void queryClient.invalidateQueries({ queryKey: ["worker-offers"] });
    },
    onSettled: () => setBusyId(null),
  });

  const rejectMutation = useMutation({
    mutationFn: (offerId: string) => workersApi.rejectOffer(offerId),
    onSuccess: () => {
      toast.info("Offer declined.");
      void queryClient.invalidateQueries({ queryKey: ["worker-offers"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => setBusyId(null),
  });

  if (query.isLoading) return <PageLoader label="Checking for offers…" />;

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Offers</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Errands matched to your profile right now. Each offer runs on a short countdown — accept one and it's yours.
        </p>
      </div>

      {items.length === 0 ? (
        <EmptyState
          icon="📭"
          title="No pending offers"
          description="Make sure you're online from the home screen. Offers appear here the moment the matching engine picks you."
          action={
            <Link to="/worker">
              <Button variant="secondary">Back to home</Button>
            </Link>
          }
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {items.map((pair) => (
            <OfferCard
              key={pair.offer.id}
              pair={pair}
              now={now}
              busy={busyId === pair.offer.id}
              onAccept={(offerId) => {
                setBusyId(offerId);
                acceptMutation.mutate(offerId);
              }}
              onReject={(offerId) => {
                setBusyId(offerId);
                rejectMutation.mutate(offerId);
              }}
              onCounter={(task) => setBidTask(task)}
            />
          ))}
        </div>
      )}

      {bidTask && (
        <BidComposer task={bidTask} open={bidTask !== null} onClose={() => setBidTask(null)} />
      )}
    </div>
  );
}
