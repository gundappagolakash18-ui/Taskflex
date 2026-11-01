import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { adminApi } from "@/api/admin";
import { Card, PageLoader, Stat } from "@/components/ui";

const DAY_OPTIONS = [7, 14, 30, 60, 90];

const PIE_COLORS = ["#3b6cf6", "#f97f07", "#10b981", "#8b5cf6", "#ef4444", "#0ea5e9", "#f59e0b", "#64748b"];

export default function Reports() {
  const [days, setDays] = useState(30);

  const analytics = useQuery({
    queryKey: ["admin-analytics", days],
    queryFn: () => adminApi.analytics(days),
  });

  if (analytics.isLoading) return <PageLoader />;
  if (analytics.isError || !analytics.data) {
    return <Card className="p-6 text-sm text-red-600">Failed to load analytics. Please refresh.</Card>;
  }
  const a = analytics.data;
  const m = a.metrics;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Reports</h1>
          <p className="text-sm text-slate-500">Marketplace analytics over the last {days} days.</p>
        </div>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium"
          aria-label="Time window"
        >
          {DAY_OPTIONS.map((d) => (
            <option key={d} value={d}>
              Last {d} days
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Total users" value={m.total_users} sub={`${m.total_workers} runners`} />
        <Stat label="Completed tasks" value={m.completed_tasks} sub={`${Math.round(m.completion_rate * 100)}% completion`} />
        <Stat label="Platform commission" value={`₹${m.platform_commission.toLocaleString()}`} sub="Lifetime" />
        <Stat label="Open disputes" value={m.open_disputes} sub="Needs attention" />
      </div>

      <Card className="p-5">
        <h2 className="mb-4 font-semibold text-slate-800">Engagement — daily / monthly actives</h2>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={a.dau.map((d, i) => ({
                date: d.date,
                daily: d.value,
                monthly: a.mau[i]?.value ?? 0,
              }))}
              margin={{ top: 5, right: 10, left: -20, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d: string) => d.slice(5)} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="daily" stroke="#3b6cf6" strokeWidth={2} name="Daily active" dot={false} />
              <Line type="monotone" dataKey="monthly" stroke="#f97f07" strokeWidth={2} name="Monthly active" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <h2 className="mb-4 font-semibold text-slate-800">Tasks created vs completed</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={a.tasks_created.map((c, i) => ({
                  date: c.date,
                  created: c.value,
                  completed: a.tasks_completed[i]?.value ?? 0,
                }))}
                margin={{ top: 5, right: 10, left: -20, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d: string) => d.slice(5)} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="created" fill="#3b6cf6" name="Created" radius={[3, 3, 0, 0]} />
                <Bar dataKey="completed" fill="#10b981" name="Completed" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="p-5">
          <h2 className="mb-4 font-semibold text-slate-800">Errand type mix</h2>
          <div className="h-64">
            {a.task_type_distribution.length === 0 ? (
              <p className="flex h-full items-center justify-center text-sm text-slate-400">No data yet.</p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={a.task_type_distribution}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={55}
                    outerRadius={90}
                    paddingAngle={3}
                  >
                    {a.task_type_distribution.map((entry, i) => (
                      <Cell key={entry.name} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>
      </div>

      <Card className="p-5">
        <h2 className="mb-4 font-semibold text-slate-800">Task status distribution</h2>
        <div className="h-64">
          {a.status_distribution.length === 0 ? (
            <p className="flex h-full items-center justify-center text-sm text-slate-400">No data yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={a.status_distribution} layout="vertical" margin={{ top: 5, right: 20, left: 40, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="value" fill="#3b6cf6" name="Tasks" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </Card>
    </div>
  );
}
