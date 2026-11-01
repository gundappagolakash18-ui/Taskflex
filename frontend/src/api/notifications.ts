import { api } from "./client";
import type { Notification, Paginated } from "@/types";

export const notificationsApi = {
  list: (unreadOnly = false, page = 1, pageSize = 20) =>
    api
      .get<Paginated<Notification> & { unread: number }>("/notifications", {
        params: { unread_only: unreadOnly, page, page_size: pageSize },
      })
      .then((r) => r.data),

  unreadCount: () => api.get<{ count: number }>("/notifications/unread-count").then((r) => r.data.count),

  markRead: (notificationId: string) =>
    api.post(`/notifications/${notificationId}/read`).then((r) => r.data),

  markAllRead: () => api.post<{ marked: number }>("/notifications/read-all").then((r) => r.data),
};
