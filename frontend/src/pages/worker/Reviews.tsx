import { useQuery } from "@tanstack/react-query";
import { Star } from "lucide-react";

import { cn, timeAgo } from "@/lib/utils";
import { Avatar, Card, EmptyState, PageLoader } from "@/components/ui";
import { ratingsApi } from "@/api/social";
import { workersApi } from "@/api/workers";

export default function WorkerReviews() {
  const profileQuery = useQuery({ queryKey: ["worker-profile"], queryFn: () => workersApi.myProfile() });
  const reviewsQuery = useQuery({
    queryKey: ["worker-reviews", "me"],
    queryFn: async () => {
      const profile = await workersApi.myProfile();
      return ratingsApi.workerReviews(profile.id, 1, 50);
    },
  });

  if (profileQuery.isLoading) return <PageLoader label="Loading reviews…" />;

  const profile = profileQuery.data;
  const reviews = reviewsQuery.data?.items ?? [];

  const distribution = [5, 4, 3, 2, 1].map((star) => ({
    star,
    count: reviews.filter((r) => r.rating_score === star).length,
  }));
  const total = reviews.length;

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Reviews</h1>
        <p className="mt-0.5 text-sm text-slate-500">What customers say after working with you.</p>
      </div>

      {profile && (
        <Card className="flex flex-col items-center gap-6 sm:flex-row">
          <div className="text-center">
            <p className="text-5xl font-bold text-amber-500">{profile.rating_average.toFixed(1)}</p>
            <div className="mt-1 flex justify-center gap-0.5">
              {Array.from({ length: 5 }).map((_, i) => (
                <Star
                  key={i}
                  className={cn("h-4 w-4", i < Math.round(profile.rating_average) ? "fill-amber-400 text-amber-400" : "text-slate-300")}
                  aria-hidden
                />
              ))}
            </div>
            <p className="mt-1 text-xs text-slate-400">{profile.rating_count} ratings · {profile.completed_tasks_count} tasks</p>
          </div>
          <div className="w-full flex-1 space-y-1.5">
            {distribution.map(({ star, count }) => (
              <div key={star} className="flex items-center gap-2 text-xs">
                <span className="w-8 text-right text-slate-500">{star} ★</span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-amber-400"
                    style={{ width: total > 0 ? `${(count / total) * 100}%` : "0%" }}
                  />
                </div>
                <span className="w-6 text-slate-400">{count}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {reviews.length === 0 ? (
        <EmptyState
          icon="⭐"
          title="No reviews yet"
          description="Complete tasks with a smile — happy customers leave ratings that boost your match score."
        />
      ) : (
        <div className="space-y-3">
          {reviews.map((r) => (
            <Card key={r.id}>
              <div className="flex items-start gap-3">
                <Avatar name={r.author_name ?? undefined} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-slate-800">{r.author_name ?? "Customer"}</p>
                    <div className="flex items-center gap-1">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <Star
                          key={i}
                          className={cn("h-3.5 w-3.5", i < r.rating_score ? "fill-amber-400 text-amber-400" : "text-slate-300")}
                          aria-hidden
                        />
                      ))}
                    </div>
                  </div>
                  <p className="text-xs text-slate-400">{timeAgo(r.created_at)}</p>
                  {r.body && <p className="mt-2 text-sm text-slate-600">“{r.body}”</p>}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
