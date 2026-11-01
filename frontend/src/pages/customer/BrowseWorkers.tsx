import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ChevronRight, Search, Star } from "lucide-react";

import { cn } from "@/lib/utils";
import { Input, SkeletonList, EmptyState, Badge } from "@/components/ui";
import { workersApi, type WorkerFilters } from "@/api/workers";
import type { Worker } from "@/types";

const SKILLS = [
  { value: "", label: "All skills" },
  { value: "document_submission", label: "Document submission" },
  { value: "document_collection", label: "Document collection" },
  { value: "queue_standing", label: "Queue standing" },
  { value: "government_office", label: "Government offices" },
  { value: "courier_pickup", label: "Courier & parcel pickup" },
  { value: "grocery_pickup", label: "Grocery pickup" },
  { value: "bank_assistance", label: "Bank assistance" },
  { value: "hospital_assistance", label: "Hospital assistance" },
  { value: "form_filling", label: "Form filling" },
  { value: "local_errand", label: "Local errands" },
];

export function WorkerCard({ worker, onClick }: { worker: Worker; onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="card flex w-full items-center gap-4 p-4 text-left transition hover:border-primary-300 hover:shadow-md"
    >
      {worker.avatar_url ? (
        <img src={worker.avatar_url} alt={worker.full_name} className="h-12 w-12 rounded-full object-cover" />
      ) : (
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary-100 text-sm font-semibold text-primary-700">
          {worker.full_name
            .split(" ")
            .slice(0, 2)
            .map((p) => p[0]?.toUpperCase())
            .join("")}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-semibold text-slate-900">{worker.full_name}</p>
          {worker.is_verified && <Badge className="bg-emerald-100 text-emerald-700">✓ Verified</Badge>}
          {worker.is_online && <Badge className="bg-primary-50 text-primary-700">Online</Badge>}
        </div>
        <p className="mt-0.5 truncate text-xs text-slate-500">
          {[worker.area, worker.city].filter(Boolean).join(", ") || "Location not set"}
          {worker.experience_years > 0 ? ` · ${worker.experience_years} yr experience` : ""}
        </p>
        {worker.skills.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {worker.skills.slice(0, 3).map((s) => (
              <span key={s} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
                {s.replaceAll("_", " ")}
              </span>
            ))}
            {worker.skills.length > 3 && <span className="text-[11px] text-slate-400">+{worker.skills.length - 3} more</span>}
          </div>
        )}
      </div>
      <div className="shrink-0 text-right">
        <p className="flex items-center justify-end gap-1 text-sm font-bold text-amber-600">
          <Star className="h-4 w-4 fill-amber-400 text-amber-400" aria-hidden />
          {worker.rating_average.toFixed(1)}
        </p>
        <p className="text-[11px] text-slate-400">
          {worker.rating_count} reviews · {worker.completed_tasks_count} tasks
        </p>
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-slate-300" aria-hidden />
    </button>
  );
}

export default function BrowseWorkers() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [skill, setSkill] = useState("");
  const [onlineOnly, setOnlineOnly] = useState(false);

  const filters: WorkerFilters = {
    search: search.trim() || undefined,
    skill: skill || undefined,
    online_only: onlineOnly || undefined,
    page_size: 30,
  };

  const query = useQuery({
    queryKey: ["workers", "browse", filters],
    queryFn: () => workersApi.list(filters),
  });

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Browse runners</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Real, verified people in your city. Ratings come from customers like you.
        </p>
      </div>

      <div className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden />
          <Input
            className="pl-9"
            placeholder="Search by name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search runners"
          />
        </div>
        <select
          className="input appearance-none pr-8 sm:w-56"
          value={skill}
          onChange={(e) => setSkill(e.target.value)}
          aria-label="Filter by skill"
        >
          {SKILLS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => setOnlineOnly((v) => !v)}
          className={cn(
            "shrink-0 rounded-lg px-3.5 py-2 text-sm font-medium transition",
            onlineOnly ? "bg-primary-600 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
          )}
        >
          Online now
        </button>
      </div>

      {query.isLoading ? (
        <SkeletonList rows={5} />
      ) : query.isError ? (
        <EmptyState icon="⚠️" title="Couldn't load runners" description="Please try again in a moment." />
      ) : (query.data?.items.length ?? 0) === 0 ? (
        <EmptyState
          icon="🏃"
          title="No runners match"
          description="Try clearing filters — or create your errand anyway and our matching engine will find the best person when one comes online."
        />
      ) : (
        <>
          <p className="text-xs text-slate-400">
            {query.data?.total} runner{(query.data?.total ?? 0) === 1 ? "" : "s"} found
          </p>
          <div className="space-y-3">
            {query.data!.items.map((w) => (
              <WorkerCard key={w.id} worker={w} onClick={() => navigate(`/app/runners/${w.id}`)} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
