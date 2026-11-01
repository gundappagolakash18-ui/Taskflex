import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { BellRing } from "lucide-react";

import { cn, timeAgo } from "@/lib/utils";
import { Button, Card, EmptyState, PageLoader } from "@/components/ui";
import { notificationsApi } from "@/api/notifications";
import { wsService } from "@/services/websocket";
import { useAuthStore } from "@/stores/auth";
import { useNotificationStore } from "@/stores/notifications";
import type { UserRole } from "@/types";

const TASK_LINK_RE = /^\/(?:customer\/)?tasks\/([^/?#]+)$/;

// Stored links are role-agnostic; each role reads a task on a different route.
function resolveNotificationLink(link: string, role: UserRole | undefined): string {
  const match = TASK_LINK_RE.exec(link);
  if (!match) return link;
  if (role === "WORKER") return `/worker/tasks/${match[1]}`;
  if (role === "ADMIN") return "/admin/tasks";
  return `/app/tasks/${match[1]}`;
}

const TYPE_ICONS: Record<string, string> = {
  OFFER_RECEIVED: "📨",
  OFFER_ACCEPTED: "🤝",
  TASK_STATUS: "🔄",
  TASK_COMPLETED: "✅",
  PAYMENT: "💳",
  RATING_RECEIVED: "⭐",
  DISPUTE_CREATED: "⚠️",
  DOCUMENT_DECISION: "📄",
  MESSAGE: "💬",
};

export default function Notifications() {
  const queryClient = useQueryClient();
  const markRead = useNotificationStore((s) => s.markRead);
  const markAllRead = useNotificationStore((s) => s.markAllRead);
  const role = useAuthStore((s) => s.user?.role);

  const query = useQuery({
    queryKey: ["notifications", "page"],
    queryFn: () => notificationsApi.list(false, 1, 100),
  });

  useEffect(() => {
    const off = wsService.on("notification", () => {
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    });
    return off;
  }, [queryClient]);

  const items = query.data?.items ?? [];
  const hasUnread = items.some((n) => !n.is_read);

  const acknowledge = (id: string, isRead: boolean) => {
    if (isRead) return;
    void markRead(id).then(() => queryClient.invalidateQueries({ queryKey: ["notifications"] }));
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Notifications</h1>
          <p className="mt-0.5 text-sm text-slate-500">Everything that happened while you were away.</p>
        </div>
        {hasUnread && (
          <Button
            variant="secondary"
            onClick={() =>
              void markAllRead().then(() => queryClient.invalidateQueries({ queryKey: ["notifications"] }))
            }
          >
            Mark all read
          </Button>
        )}
      </div>

      {query.isLoading ? (
        <PageLoader label="Loading notifications…" />
      ) : items.length === 0 ? (
        <EmptyState
          icon="🔔"
          title="You're all caught up"
          description="Task updates, offers, payments and ratings will land here the moment they happen."
        />
      ) : (
        <div className="space-y-2.5">
          {items.map((n) => {
            const content = (
              <Card
                className={cn(
                  "flex w-full items-start gap-3.5 text-left transition",
                  !n.is_read && "border-primary-200 bg-primary-50/40"
                )}
              >
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-lg">
                  {TYPE_ICONS[n.type] ?? <BellRing className="h-4 w-4 text-slate-500" aria-hidden />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className={cn("truncate text-sm", n.is_read ? "font-medium text-slate-700" : "font-semibold text-slate-900")}>
                      {n.title}
                    </p>
                    <span className="shrink-0 text-[11px] text-slate-400">{timeAgo(n.created_at)}</span>
                  </div>
                  <p className="mt-0.5 text-sm text-slate-500">{n.body}</p>
                </div>
                {!n.is_read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary-500" aria-hidden />}
              </Card>
            );
            return n.link ? (
              <Link
                key={n.id}
                to={resolveNotificationLink(n.link, role)}
                onClick={() => acknowledge(n.id, n.is_read)}
                className="block"
              >
                {content}
              </Link>
            ) : (
              <button key={n.id} type="button" className="block w-full" onClick={() => acknowledge(n.id, n.is_read)}>
                {content}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
