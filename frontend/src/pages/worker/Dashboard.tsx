import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { CalendarClock, ChevronRight, Crown, Moon, Star, Sun, Zap } from "lucide-react";

import {
  TASK_STATUS_LABELS,
  TASK_STATUS_STYLES,
  TASK_TYPE_ICONS,
  TIER_ICONS,
  TIER_LABELS,
  TIER_STYLES,
} from "@/lib/constants";
import { cn, errorMessage, formatMoney } from "@/lib/utils";
import { Badge, Button, Card, EmptyState, PageLoader, SkeletonList } from "@/components/ui";
import { tasksApi } from "@/api/tasks";
import { workersApi } from "@/api/workers";
import { toast } from "@/stores/toast";
import { wsService } from "@/services/websocket";
import { useAuthStore } from "@/stores/auth";

const ACTIVE_STATUSES = [
  "ACCEPTED",
  "QUEUED_NEXT",
  "SCHEDULED_ASSIGNED",
  "WORKER_ON_THE_WAY",
  "ARRIVED_AT_LOCATION",
  "IN_PROGRESS",
  "COMPLETION_REQUESTED",
  "DISPUTED",
  "EMERGENCY_ALERT",
];

export default function WorkerDashboard() {
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const [justWentOnline, setJustWentOnline] = useState(false);

  const profileQuery = useQuery({ queryKey: ["worker-profile"], queryFn: () => workersApi.myProfile() });
  const offersQuery = useQuery({
    queryKey: ["worker-offers"],
    queryFn: () => workersApi.myOffers(),
    refetchInterval: 20_000,
  });
  const tasksQuery = useQuery({
    queryKey: ["tasks", "worker-active"],
    queryFn: () => tasksApi.list({ page_size: 50 }),
    refetchInterval: 30_000,
  });

  useEffect(() => {
    const off = wsService.onAny(() => {
      void queryClient.invalidateQueries({ queryKey: ["worker-offers"] });
      void queryClient.invalidateQueries({ queryKey: ["tasks", "worker-active"] });
    });
    return off;
  }, [queryClient]);

  const onlineMutation = useMutation({
    mutationFn: (is_online: boolean) => workersApi.setOnline(is_online),
    onSuccess: (worker) => {
      toast.success(worker.is_online ? "You're online — new offers can reach you now." : "You're offline. Take care!");
      setJustWentOnline(worker.is_online);
      void queryClient.invalidateQueries({ queryKey: ["worker-profile"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (profileQuery.isLoading) return <PageLoader label="Loading your runner profile…" />;

  const profile = profileQuery.data;
  const offers = offersQuery.data?.items ?? [];
  const activeTasks = (tasksQuery.data?.items ?? []).filter((t) => ACTIVE_STATUSES.includes(t.status) && t.assigned_worker_id === user?.id);

  const isOnline = profile?.is_online ?? false;

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Namaste, {user?.full_name.split(" ")[0]} 👋</h1>
          <p className="mt-0.5 text-sm text-slate-500">Here's your runner cockpit for today.</p>
        </div>
      </div>

      {/* Online toggle */}
      <Card
        className={cn(
          "flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between",
          isOnline ? "border-emerald-200 bg-emerald-50" : "border-slate-200"
        )}
      >
        <div>
          <p className={cn("text-sm font-semibold", isOnline ? "text-emerald-900" : "text-slate-800")}>
            {isOnline ? "You're ONLINE — receiving offer requests" : "You're offline"}
          </p>
          <p className="mt-1 text-sm text-slate-500">
            {isOnline
              ? "Keep the app open; offers arrive in real time and expire quickly."
              : "Go online to start receiving errand offers matched to your skills, ratings and location."}
          </p>
        </div>
        <Button
          variant={isOnline ? "danger" : "primary"}
          loading={onlineMutation.isPending}
          onClick={() => onlineMutation.mutate(!isOnline)}
          className="shrink-0"
        >
          {isOnline ? <Moon className="mr-1.5 h-4 w-4" aria-hidden /> : <Zap className="mr-1.5 h-4 w-4" aria-hidden />}
          {isOnline ? "Go offline" : "Go online"}
        </Button>
      </Card>

      {/* Tier + scheduled board */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="card flex items-center justify-between gap-3 p-4">
          <div>
            <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
              <Crown className="h-3.5 w-3.5" aria-hidden /> Your tier
            </p>
            <div className="mt-1 flex items-center gap-2">
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-sm font-bold",
                  TIER_STYLES[profile?.tier ?? "SILVER"] ?? ""
                )}
              >
                <span aria-hidden>{TIER_ICONS[profile?.tier ?? "SILVER"] ?? "🏅"}</span>
                {TIER_LABELS[profile?.tier ?? "SILVER"] ?? "Silver"}
              </span>
              <span className="text-xs text-slate-500">
                {profile?.commission_rate != null
                  ? `${(profile.commission_rate * 100).toFixed(profile.commission_rate * 100 % 1 === 0 ? 0 : 1)}% fee`
                  : ""}
              </span>
            </div>
          </div>
          <Link to="/worker/earnings" className="text-xs font-medium text-primary-600 hover:underline">
            Quests & tier →
          </Link>
        </div>
        <Link
          to="/worker/scheduled"
          className="card flex items-center justify-between gap-3 p-4 transition hover:border-primary-300 hover:shadow-md"
        >
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-50 text-amber-600">
              <CalendarClock className="h-5 w-5" aria-hidden />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-900">Scheduled board</p>
              <p className="text-xs text-slate-500">Reserve future errands and lock in slots.</p>
            </div>
          </div>
          <ChevronRight className="h-4 w-4 shrink-0 text-slate-300" aria-hidden />
        </Link>
      </div>

      {justWentOnline && offers.length === 0 && !offersQuery.isLoading && (
        <div className="rounded-xl bg-amber-50 p-4 text-sm text-amber-800">
          You're visible to the matching engine now. When a customer's errand fits your skills and area, an offer card will appear
          under <Link to="/worker/offers" className="font-semibold underline">Offers</Link>.
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="card p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Pending offers</p>
          <p className="mt-1 text-2xl font-bold text-slate-900">{offers.length}</p>
          <Link to="/worker/offers" className="mt-1 inline-block text-xs font-medium text-primary-600 hover:underline">
            View offers →
          </Link>
        </div>
        <div className="card p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Lifetime earnings</p>
          <p className="mt-1 text-2xl font-bold text-slate-900">
            {profile ? formatMoney(profile.total_earnings ?? 0) : "—"}
          </p>
        </div>
        <div className="card p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Rating</p>
          <p className="mt-1 flex items-center gap-1 text-2xl font-bold text-amber-500">
            <Star className="h-5 w-5 fill-amber-400 text-amber-400" aria-hidden />
            {profile ? profile.rating_average.toFixed(1) : "—"}
          </p>
          <p className="text-xs text-slate-400">{profile?.rating_count ?? 0} reviews</p>
        </div>
        <div className="card p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Tasks completed</p>
          <p className="mt-1 text-2xl font-bold text-slate-900">{profile?.completed_tasks_count ?? 0}</p>
        </div>
      </div>

      {/* Active assignments */}
      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Active assignments</h2>
        {tasksQuery.isLoading ? (
          <SkeletonList rows={2} />
        ) : activeTasks.length === 0 ? (
          <EmptyState
            icon="🛵"
            title="No active assignments"
            description="Accepted tasks appear here with your next action, step by step."
          />
        ) : (
          <div className="space-y-3">
            {activeTasks.map((t) => (
              <Link
                key={t.id}
                to={`/worker/tasks/${t.id}`}
                className="card flex items-center gap-4 p-4 transition hover:border-primary-300 hover:shadow-md"
              >
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-xl">
                  {TASK_TYPE_ICONS[t.task_type] ?? "🧭"}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-slate-900">{t.title}</p>
                  <p className="truncate text-xs text-slate-500">
                    {TASK_STATUS_LABELS[t.status]} · {formatMoney(t.budget, t.currency)}
                    {t.area_name ? ` · ${t.area_name}` : ""}
                  </p>
                </div>
                <Badge className={TASK_STATUS_STYLES[t.status]}>
                  {TASK_STATUS_LABELS[t.status]}
                </Badge>
                <ChevronRight className="h-4 w-4 shrink-0 text-slate-300" aria-hidden />
              </Link>
            ))}
          </div>
        )}
      </div>

      {profile?.verification_status === "pending" && (
        <Card className="border-amber-200 bg-amber-50">
          <p className="text-sm font-semibold text-amber-900">Verification pending</p>
          <p className="mt-1 text-sm text-amber-800">
            Upload your ID and address proof from{" "}
            <Link to="/worker/settings" className="font-semibold underline">
              Settings → Documents
            </Link>{" "}
            to earn the verified badge — verified runners get priority in matching.
          </p>
        </Card>
      )}

      <p className="flex items-center gap-1.5 text-xs text-slate-400">
        <Sun className="h-3.5 w-3.5" aria-hidden />
        Tip: runners who respond to offers within the first minute have the highest acceptance success.
      </p>
    </div>
  );
}
