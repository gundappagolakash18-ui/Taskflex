import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { adminApi } from "@/api/admin";
import { Avatar, Badge, Button, Card, EmptyState, Input, PageLoader, Select } from "@/components/ui";

export default function Workers() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [verified, setVerified] = useState("");
  const [online, setOnline] = useState("");
  const [page, setPage] = useState(1);

  const workers = useQuery({
    queryKey: ["admin-workers", query, verified, online, page],
    queryFn: () =>
      adminApi.workers({
        search: query || undefined,
        verified: verified === "" ? undefined : verified === "yes",
        online: online === "" ? undefined : online === "yes",
        page,
        page_size: 20,
      }),
  });

  const rows = workers.data?.items ?? [];
  const total = workers.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 20));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Workers</h1>
        <p className="text-sm text-slate-500">{total} runners registered</p>
      </div>

      <Card className="flex flex-wrap items-center gap-3 p-4">
        <form
          className="relative flex-1 min-w-56"
          onSubmit={(e) => {
            e.preventDefault();
            setPage(1);
            setQuery(search);
          }}
        >
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or city…"
            className="pl-9"
          />
        </form>
        <Select
          value={verified}
          onChange={(e) => {
            setVerified(e.target.value);
            setPage(1);
          }}
          className="w-44"
        >
          <option value="">Any verification</option>
          <option value="yes">Verified</option>
          <option value="no">Unverified</option>
        </Select>
        <Select
          value={online}
          onChange={(e) => {
            setOnline(e.target.value);
            setPage(1);
          }}
          className="w-36"
        >
          <option value="">Online: any</option>
          <option value="yes">Online now</option>
          <option value="no">Offline</option>
        </Select>
      </Card>

      {workers.isLoading ? (
        <PageLoader />
      ) : rows.length === 0 ? (
        <EmptyState icon="🛵" title="No workers found" description="Adjust the filters to see more runners." />
      ) : (
        <div className="space-y-3">
          {rows.map((w) => (
            <Card key={w.id} className="flex flex-wrap items-center gap-4 p-4">
              <Avatar name={w.full_name} url={w.avatar_url} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="truncate font-semibold text-slate-800">{w.full_name}</p>
                  {w.is_verified ? (
                    <Badge className="bg-emerald-100 text-emerald-700">verified</Badge>
                  ) : (
                    <Badge className="bg-amber-100 text-amber-700">unverified</Badge>
                  )}
                  {w.is_online && <Badge className="bg-primary-100 text-primary-700">online</Badge>}
                </div>
                <p className="truncate text-xs text-slate-500">
                  {[w.area, w.city].filter(Boolean).join(", ") || "Location not set"} · {w.rating_average.toFixed(1)}★ (
                  {w.rating_count}) · {w.completed_tasks_count} tasks
                  {typeof w.total_earnings === "number" ? ` · ₹${Math.round(w.total_earnings).toLocaleString()} earned` : ""}
                </p>
                {w.skills.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {w.skills.slice(0, 5).map((s) => (
                      <Badge key={s} className="bg-slate-100 text-slate-600">
                        {s.replaceAll("_", " ")}
                      </Badge>
                    ))}
                    {w.skills.length > 5 && <Badge className="bg-slate-100 text-slate-400">+{w.skills.length - 5}</Badge>}
                  </div>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <span className="text-sm text-slate-500">
            Page {page} of {totalPages}
          </span>
          <Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
