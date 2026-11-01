import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Ban, Heart, Star } from "lucide-react";

import { DAY_NAMES } from "@/lib/constants";
import { cn, errorMessage, initials, timeAgo } from "@/lib/utils";
import { Badge, Button, Card, EmptyState, PageLoader } from "@/components/ui";
import { ratingsApi } from "@/api";
import { usersApi } from "@/api/users";
import { workersApi } from "@/api/workers";
import { toast } from "@/stores/toast";

type AffinityAction = "prefer" | "unprefer" | "blacklist" | "unblacklist";

export default function WorkerProfile() {
  const { workerId = "" } = useParams();
  const queryClient = useQueryClient();

  const workerQuery = useQuery({
    queryKey: ["worker", workerId],
    queryFn: () => workersApi.get(workerId),
    enabled: !!workerId,
  });

  const affinityQuery = useQuery({
    queryKey: ["worker-affinities"],
    queryFn: () => usersApi.affinities(),
    enabled: !!workerId,
  });

  const affinityMutation = useMutation({
    mutationFn: (action: AffinityAction): Promise<unknown> => {
      switch (action) {
        case "prefer":
          return usersApi.preferWorker(workerId);
        case "unprefer":
          return usersApi.removePreferredWorker(workerId);
        case "blacklist":
          return usersApi.blacklistWorker(workerId);
        case "unblacklist":
          return usersApi.unblacklistWorker(workerId);
      }
    },
    onSuccess: (_data, action) => {
      const message =
        action === "prefer"
          ? "Added to your preferred runners — they'll be offered your tasks first."
          : action === "unprefer"
            ? "Removed from your preferred runners."
            : action === "blacklist"
              ? "Runner blocked — they won't be offered your tasks again."
              : "Runner unblocked.";
      toast.success(message);
      void queryClient.invalidateQueries({ queryKey: ["worker-affinities"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const reviewsQuery = useQuery({
    queryKey: ["worker-reviews", workerId],
    queryFn: () => ratingsApi.workerReviews(workerId, 1, 20),
    enabled: !!workerId,
  });

  if (workerQuery.isLoading) return <PageLoader label="Loading profile…" />;
  if (workerQuery.isError || !workerQuery.data) {
    return (
      <EmptyState
        icon="🔍"
        title="Runner not found"
        description="This profile may have been removed."
        action={
          <Link to="/app/runners">
            <Button>Back to runners</Button>
          </Link>
        }
      />
    );
  }

  const w = workerQuery.data;
  const isPreferred = affinityQuery.data?.preferred.some((a) => a.worker_id === workerId) ?? false;
  const isBlacklisted = affinityQuery.data?.blacklisted.some((a) => a.worker_id === workerId) ?? false;

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
          {w.avatar_url ? (
            <img src={w.avatar_url} alt={w.full_name} className="h-20 w-20 rounded-2xl object-cover" />
          ) : (
            <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-primary-100 text-2xl font-bold text-primary-700">
              {initials(w.full_name)}
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-bold text-slate-900">{w.full_name}</h1>
              {w.is_verified && <Badge className="bg-emerald-100 text-emerald-700">✓ Identity verified</Badge>}
              {w.is_online && <Badge className="bg-primary-50 text-primary-700">● Online now</Badge>}
            </div>
            <p className="mt-1 text-sm text-slate-500">
              {[w.area, w.city].filter(Boolean).join(", ") || "City not set"}
              {w.experience_years > 0 ? ` · ${w.experience_years} years of experience` : ""}
            </p>
            <div className="mt-3 flex flex-wrap gap-6">
              <div>
                <p className="flex items-center gap-1 text-lg font-bold text-amber-600">
                  <Star className="h-5 w-5 fill-amber-400 text-amber-400" aria-hidden />
                  {w.rating_average.toFixed(1)}
                </p>
                <p className="text-xs text-slate-400">{w.rating_count} reviews</p>
              </div>
              <div>
                <p className="text-lg font-bold text-slate-900">{w.completed_tasks_count}</p>
                <p className="text-xs text-slate-400">tasks completed</p>
              </div>
              {typeof w.cancelled_tasks_count === "number" && (
                <div>
                  <p className="text-lg font-bold text-slate-900">
                    {w.completed_tasks_count + w.cancelled_tasks_count > 0
                      ? `${Math.round((w.completed_tasks_count / (w.completed_tasks_count + w.cancelled_tasks_count)) * 100)}%`
                      : "—"}
                  </p>
                  <p className="text-xs text-slate-400">completion rate</p>
                </div>
              )}
            </div>
          </div>
          <Link to="/app/tasks/new" className="shrink-0">
            <Button>Hire for an errand</Button>
          </Link>
        </div>
      </Card>

      <Card className={cn(isBlacklisted && "border-red-200 bg-red-50/50")}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Your relationship</h2>
            <p className="mt-1.5 text-sm text-slate-600">
              {isBlacklisted
                ? "This runner is blocked — they won't be offered or matched to any of your future errands."
                : isPreferred
                  ? "Preferred runner — your repeat requests prioritize them and carry a ⭐ Repeat Customer Request badge."
                  : "Mark runners you trust as preferred so your errands reach them first, or block runners you don't want matched again."}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Button
              variant={isPreferred ? "secondary" : "ghost"}
              loading={affinityMutation.isPending && affinityMutation.variables === (isPreferred ? "unprefer" : "prefer")}
              disabled={affinityMutation.isPending}
              onClick={() => affinityMutation.mutate(isPreferred ? "unprefer" : "prefer")}
              className={cn(isPreferred && "border-rose-200 text-rose-600 hover:bg-rose-50")}
            >
              <Heart className={cn("mr-1.5 h-4 w-4", isPreferred && "fill-rose-500 text-rose-500")} aria-hidden />
              {isPreferred ? "Preferred" : "Mark preferred"}
            </Button>
            <Button
              variant={isBlacklisted ? "secondary" : "ghost"}
              loading={affinityMutation.isPending && affinityMutation.variables === (isBlacklisted ? "unblacklist" : "blacklist")}
              disabled={affinityMutation.isPending}
              onClick={() => affinityMutation.mutate(isBlacklisted ? "unblacklist" : "blacklist")}
              className={cn(isBlacklisted && "border-red-300 text-red-700 hover:bg-red-100")}
            >
              <Ban className="mr-1.5 h-4 w-4" aria-hidden />
              {isBlacklisted ? "Blocked" : "Block runner"}
            </Button>
          </div>
        </div>
      </Card>

      {w.bio && (
        <Card>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">About</h2>
          <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-slate-700">{w.bio}</p>
          {w.languages && <p className="mt-3 text-xs text-slate-500">Speaks: {w.languages}</p>}
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {w.skills.length > 0 && (
          <Card>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Skills</h2>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {w.skills.map((s) => (
                <Badge key={s} className="bg-primary-50 text-primary-700">
                  {s.replaceAll("_", " ")}
                </Badge>
              ))}
            </div>
          </Card>
        )}

        {w.availability && w.availability.length > 0 && (
          <Card>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Weekly availability</h2>
            <ul className="mt-3 space-y-1.5">
              {w.availability.map((a) => (
                <li key={a.day_of_week} className="flex items-center justify-between text-sm">
                  <span className="text-slate-700">{DAY_NAMES[a.day_of_week] ?? `Day ${a.day_of_week}`}</span>
                  <span className={cn("text-xs font-medium", a.is_available ? "text-emerald-600" : "text-slate-400")}>
                    {a.is_available ? `${a.start_time} – ${a.end_time}` : "Unavailable"}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>

      <Card>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Reviews from customers</h2>
        {reviewsQuery.isLoading ? (
          <p className="mt-3 text-sm text-slate-400">Loading reviews…</p>
        ) : (reviewsQuery.data?.items.length ?? 0) === 0 ? (
          <p className="mt-3 text-sm text-slate-500">No reviews yet — be the first to hire this runner.</p>
        ) : (
          <ul className="mt-4 space-y-4">
            {reviewsQuery.data!.items.map((r) => (
              <li key={r.id} className="border-b border-slate-100 pb-4 last:border-0 last:pb-0">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <Star key={i} className={cn("h-3.5 w-3.5", i < r.rating_score ? "fill-amber-400 text-amber-400" : "text-slate-300")} aria-hidden />
                    ))}
                  </div>
                  <span className="text-xs text-slate-400">{timeAgo(r.created_at)}</span>
                </div>
                {r.body && <p className="mt-1.5 text-sm text-slate-600">“{r.body}”</p>}
                <p className="mt-1 text-xs text-slate-400">{r.author_name ?? "Customer"}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
