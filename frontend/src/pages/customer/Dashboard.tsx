import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Clock, MapPin, PlusCircle } from "lucide-react";
import { tasksApi } from "@/api/tasks";
import { usersApi } from "@/api/users";
import { useAuthStore } from "@/stores/auth";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, PageLoader, Stat } from "@/components/ui";
import { TASK_TYPE_ICONS, TASK_TYPE_LABELS, WS_EVENTS } from "@/lib/constants";
import { wsService } from "@/services/websocket";
import { formatDateTime, formatMoney, timeAgo } from "@/lib/utils";
import type { TaskStatus } from "@/types";

const ACTIVE: TaskStatus[] = [
  "PENDING_CONFIRMATION",
  "CONFIRMED",
  "SEARCHING_WORKER",
  "OFFERED",
  "ACCEPTED",
  "WORKER_ON_THE_WAY",
  "ARRIVED_AT_LOCATION",
  "IN_PROGRESS",
  "COMPLETION_REQUESTED",
  "DISPUTED",
  "EMERGENCY_ALERT",
];

export default function CustomerDashboard() {
  const user = useAuthStore((s) => s.user);
  const queryClient = useQueryClient();

  const tasksQuery = useQuery({
    queryKey: ["tasks", "page", 1],
    queryFn: () => tasksApi.list({ page: 1, page_size: 50 }),
    refetchInterval: 30_000,
  });

  const walletQuery = useQuery({
    queryKey: ["wallet"],
    queryFn: () => usersApi.wallet(),
  });

  useEffect(() => {
    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["wallet"] });
    };
    const offStatus = wsService.on(WS_EVENTS.TASK_STATUS, refresh);
    const offNotification = wsService.on("notification", refresh);
    return () => {
      offStatus();
      offNotification();
    };
  }, [queryClient]);

  const tasks = tasksQuery.data?.items ?? [];
  const active = tasks.filter((t) => ACTIVE.includes(t.status));
  const completed = tasks.filter((t) => t.status === "COMPLETED");
  const awaiting = tasks.filter((t) => t.status === "PENDING_CONFIRMATION");

  if (tasksQuery.isLoading) return <PageLoader />;

  return (
    <div className="mx-auto max-w-4xl px-4 py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Hi {user?.full_name.split(" ")[0]} 👋</h1>
          <p className="mt-0.5 text-sm text-slate-500">What errand can we take off your plate today?</p>
        </div>
        <Link to="/app/new" className="btn-primary">
          <PlusCircle className="h-4 w-4" /> New errand
        </Link>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="Active tasks" value={active.length} icon={<Clock className="h-5 w-5" />} />
        <Stat label="Completed" value={completed.length} icon={<MapPin className="h-5 w-5" />} />
        <Stat label="Wallet balance" value={formatMoney(walletQuery.data?.balance ?? 0)} sub={`${walletQuery.data?.currency ?? "INR"}`} />
      </div>

      {awaiting.length > 0 && (
        <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm font-semibold text-amber-900">
            {awaiting.length} errand{awaiting.length > 1 ? "s" : ""} awaiting your confirmation
          </p>
          <p className="mt-0.5 text-xs text-amber-700">Nothing gets sent to runners until you review and confirm.</p>
          <div className="mt-3 space-y-2">
            {awaiting.map((task) => (
              <Link
                key={task.id}
                to={`/app/tasks/${task.id}`}
                className="flex items-center justify-between gap-3 rounded-lg bg-white px-3.5 py-2.5 text-sm shadow-sm hover:bg-amber-50/60"
              >
                <span className="min-w-0 truncate font-medium text-slate-800">{task.title}</span>
                <span className="shrink-0 font-semibold text-slate-900">{formatMoney(task.budget, task.currency)}</span>
              </Link>
            ))}
          </div>
        </div>
      )}

      <section className="mt-7">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-900">Active errands</h2>
          <Link to="/app/tasks" className="text-sm font-medium text-primary-600 hover:underline">
            View all
          </Link>
        </div>
        <div className="mt-3 space-y-3">
          {active.length === 0 ? (
            <EmptyState
              icon="🧭"
              title="No active errands"
              description="Describe your next errand in plain words and let TaskFlex handle the rest."
              action={
                <Link to="/app/new" className="btn-primary">
                  Post an errand
                </Link>
              }
            />
          ) : (
            active.map((task) => (
              <Link key={task.id} to={`/app/tasks/${task.id}`} className="card block p-4 transition-shadow hover:shadow-md">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span>{TASK_TYPE_ICONS[task.task_type] ?? "🧭"}</span>
                      <p className="truncate font-semibold text-slate-900">{task.title}</p>
                    </div>
                    <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                      <span>{TASK_TYPE_LABELS[task.task_type] ?? task.task_type}</span>
                      {task.scheduled_date && <span>🕐 {formatDateTime(`${task.scheduled_date}T${task.scheduled_time ?? "09:00"}`)}</span>}
                      {task.city && <span>📍 {task.city}</span>}
                      <span>{timeAgo(task.created_at)}</span>
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="font-bold text-slate-900">{formatMoney(task.budget, task.currency)}</p>
                    <StatusBadge status={task.status} className="mt-1" />
                  </div>
                </div>
              </Link>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
