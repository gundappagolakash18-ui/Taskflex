import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ArrowRight, ShieldAlert } from "lucide-react";
import { adminApi } from "@/api/admin";
import { Card, PageLoader, Stat } from "@/components/ui";

export default function AdminDashboard() {
  const metrics = useQuery({ queryKey: ["admin-dashboard"], queryFn: () => adminApi.dashboard() });
  const analytics = useQuery({ queryKey: ["admin-analytics", 30], queryFn: () => adminApi.analytics(30) });

  if (metrics.isLoading) return <PageLoader />;
  if (metrics.isError || !metrics.data) {
    return (
      <Card className="p-6 text-sm text-red-600">Failed to load dashboard metrics. Please refresh.</Card>
    );
  }
  const m = metrics.data;

  const activity = (analytics.data?.tasks_created ?? []).map((c, i) => ({
    date: c.date,
    created: c.value,
    completed: analytics.data?.tasks_completed[i]?.value ?? 0,
  }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Platform overview</h1>
        <p className="text-sm text-slate-500">Live health of the TaskFlex marketplace.</p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Total users" value={m.total_users} sub={`${m.total_customers} customers · ${m.total_workers} workers`} />
        <Stat label="Tasks completed" value={m.completed_tasks} sub={`${m.total_tasks} lifetime`} />
        <Stat
          label="Completion rate"
          value={`${Math.round(m.completion_rate * 100)}%`}
          sub={`${Math.round(m.cancellation_rate * 100)}% cancellation`}
        />
        <Stat label="Platform commission" value={`₹${m.platform_commission.toLocaleString()}`} sub={`Revenue ₹${m.total_revenue.toLocaleString()}`} />
        <Stat label="Active tasks" value={m.active_tasks} sub="In-flight right now" />
        <Stat label="Active workers" value={m.active_workers} sub={`${m.verified_workers} verified`} />
        <Stat label="Avg task value" value={`₹${Math.round(m.average_task_value).toLocaleString()}`} sub={`Avg rating ${m.average_rating.toFixed(1)}`} />
        <Stat label="Open disputes" value={m.open_disputes} sub={`${m.disputed_tasks} lifetime`} />
      </div>

      {m.open_disputes > 0 && (
        <Link to="/admin/disputes">
          <Card className="flex items-center gap-3 border-amber-300 bg-amber-50 p-4 transition-colors hover:bg-amber-100">
            <ShieldAlert className="h-5 w-5 shrink-0 text-amber-600" />
            <p className="flex-1 text-sm font-medium text-amber-800">
              {m.open_disputes} open dispute{m.open_disputes === 1 ? "" : "s"} awaiting review
            </p>
            <ArrowRight className="h-4 w-4 text-amber-600" />
          </Card>
        </Link>
      )}

      <Card className="p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold text-slate-800">Task activity — last 30 days</h2>
          <Link to="/admin/reports" className="flex items-center gap-1 text-sm font-medium text-primary-600 hover:underline">
            Full report <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
        <div className="h-64">
          {activity.length === 0 ? (
            <p className="flex h-full items-center justify-center text-sm text-slate-400">
              No task activity recorded yet.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={activity} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="gCreated" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3b6cf6" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#3b6cf6" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gCompleted" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d: string) => d.slice(5)} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Area type="monotone" dataKey="created" stroke="#3b6cf6" fill="url(#gCreated)" strokeWidth={2} name="Created" />
                <Area type="monotone" dataKey="completed" stroke="#10b981" fill="url(#gCompleted)" strokeWidth={2} name="Completed" />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </Card>
    </div>
  );
}
