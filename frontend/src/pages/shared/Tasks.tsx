import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { ChevronRight, Plus } from "lucide-react";

import { TASK_STATUS_LABELS, TASK_STATUS_STYLES, TASK_TYPE_ICONS, TASK_TYPE_LABELS, WS_EVENTS } from "@/lib/constants";
import { cn, formatMoney, timeAgo } from "@/lib/utils";
import { Badge, Button, EmptyState, SkeletonList } from "@/components/ui";
import { tasksApi } from "@/api/tasks";
import { wsService } from "@/services/websocket";
import { useAuthStore } from "@/stores/auth";
import type { Task } from "@/types";

type Tab = "all" | "active" | "PENDING_CONFIRMATION" | "COMPLETED" | "CANCELLED" | "DISPUTED";

const ACTIVE_STATUSES = [
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

const TABS: { key: Tab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "PENDING_CONFIRMATION", label: "Awaiting confirmation" },
  { key: "COMPLETED", label: "Completed" },
  { key: "CANCELLED", label: "Cancelled" },
];

function TaskRow({ task, basePath }: { task: Task; basePath: string }) {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => navigate(`${basePath}/tasks/${task.id}`)}
      className="card flex w-full items-center gap-4 p-4 text-left transition hover:border-primary-300 hover:shadow-md"
    >
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-xl">
        {TASK_TYPE_ICONS[task.task_type] ?? "🧭"}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-semibold text-slate-900">{task.title}</p>
          {task.my_offer_status && (
            <Badge className={task.my_offer_status === "PENDING" ? "bg-indigo-100 text-indigo-700" : task.my_offer_status === "ACCEPTED" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}>
              Offer: {task.my_offer_status.toLowerCase()}
            </Badge>
          )}
        </div>
        <p className="mt-0.5 truncate text-xs text-slate-500">
          {TASK_TYPE_LABELS[task.task_type] ?? task.task_type} · {timeAgo(task.created_at)}
          {task.area_name ? ` · ${task.area_name}` : ""}
        </p>
      </div>
      <div className="hidden shrink-0 text-right sm:block">
        <p className="text-sm font-bold text-slate-900">{formatMoney(task.budget, task.currency)}</p>
        <span className={cn("mt-1 inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium", TASK_STATUS_STYLES[task.status])}>
          {TASK_STATUS_LABELS[task.status]}
        </span>
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-slate-300" aria-hidden />
    </button>
  );
}

export default function Tasks() {
  const user = useAuthStore((s) => s.user);
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("all");

  const basePath = user?.role === "WORKER" ? "/worker" : "/app";
  const isCustomer = user?.role === "CUSTOMER";

  const listQuery = useQuery({
    queryKey: ["tasks", "list", tab],
    queryFn: () =>
      tab === "all" || tab === "active"
        ? tasksApi.list({ page_size: 50 })
        : tasksApi.list({ status: tab, page_size: 50 }),
    refetchInterval: 30_000,
  });

  useEffect(() => {
    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    };
    const offStatus = wsService.on(WS_EVENTS.TASK_STATUS, refresh);
    const offNotification = wsService.on("notification", refresh);
    return () => {
      offStatus();
      offNotification();
    };
  }, [queryClient]);

  const items = (listQuery.data?.items ?? []).filter((t) => {
    if (tab === "active") return ACTIVE_STATUSES.includes(t.status) || t.status === "PENDING_CONFIRMATION";
    if (tab === "PENDING_CONFIRMATION") return t.status === "PENDING_CONFIRMATION";
    return true;
  });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">{isCustomer ? "Your errands" : "Your assignments"}</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            {isCustomer ? "Track every request from description to completion." : "Tasks you have accepted or been offered."}
          </p>
        </div>
        {isCustomer && (
          <Link to="/app/tasks/new">
            <Button>
              <Plus className="mr-1.5 h-4 w-4" aria-hidden /> New errand
            </Button>
          </Link>
        )}
      </div>

      <div className="flex gap-2 overflow-x-auto pb-1">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={cn(
              "shrink-0 rounded-full px-3.5 py-1.5 text-sm font-medium transition",
              tab === t.key ? "bg-primary-600 text-white shadow-sm" : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {listQuery.isLoading ? (
        <SkeletonList rows={4} />
      ) : listQuery.isError ? (
        <EmptyState icon="⚠️" title="Couldn't load tasks" description="Please try again in a moment." />
      ) : items.length === 0 ? (
        <EmptyState
          icon="🗂️"
          title={tab === "all" ? (isCustomer ? "No errands yet" : "No assignments yet") : "Nothing here"}
          description={
            isCustomer
              ? "Describe what you need in plain English and let AI + our runner network take it from there."
              : "Go online to start receiving offers matched to your skills and location."
          }
          action={
            isCustomer ? (
              <Link to="/app/tasks/new">
                <Button>Create your first errand</Button>
              </Link>
            ) : undefined
          }
        />
      ) : (
        <div className="space-y-3">
          {items.map((task) => (
            <TaskRow key={task.id} task={task} basePath={basePath} />
          ))}
        </div>
      )}
    </div>
  );
}
