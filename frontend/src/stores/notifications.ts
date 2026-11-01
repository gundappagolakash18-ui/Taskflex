import { create } from "zustand";
import { useEffect } from "react";
import { notificationsApi } from "@/api/notifications";
import { wsService } from "@/services/websocket";
import { toast } from "@/stores/toast";
import type { Notification } from "@/types";
import { useAuthStore } from "@/stores/auth";

interface NotificationState {
  items: Notification[];
  unread: number;
  setAll: (items: Notification[], unread: number) => void;
  setUnread: (count: number) => void;
  refresh: () => Promise<void>;
  markRead: (id: string) => Promise<void>;
  markAllRead: () => Promise<void>;
  bindSocket: () => () => void;
}

export const useNotificationStore = create<NotificationState>((set, get) => ({
  items: [],
  unread: 0,
  setAll: (items, unread) => set({ items, unread }),
  setUnread: (unread) => set({ unread }),

  refresh: async () => {
    try {
      const data = await notificationsApi.list(false, 1, 20);
      get().setAll(data.items, data.unread);
    } catch {
      // non-critical
    }
  },

  markRead: async (id) => {
    set((state) => ({
      items: state.items.map((n) => (n.id === id ? { ...n, is_read: true } : n)),
      unread: Math.max(0, state.unread - 1),
    }));
    try {
      await notificationsApi.markRead(id);
    } catch {
      // optimistic update stands
    }
  },

  markAllRead: async () => {
    set((state) => ({ unread: 0, items: state.items.map((n) => ({ ...n, is_read: true })) }));
    try {
      await notificationsApi.markAllRead();
    } catch {
      // optimistic update stands
    }
  },

  bindSocket: () => {
    const unsubscribe = wsService.on("notification", (event) => {
      const payload = event.data as unknown as {
        notification?: Notification;
        title?: string;
        body?: string;
        link?: string;
      };
      const incoming: Notification =
        payload.notification ??
        ({
          id: crypto.randomUUID(),
          type: "SYSTEM",
          title: payload.title ?? "Update",
          body: payload.body ?? "",
          data: event.data,
          link: payload.link ?? null,
          is_read: false,
          created_at: new Date().toISOString(),
        } as Notification);
      set((state) => ({
        items: [incoming, ...state.items].slice(0, 20),
        unread: state.unread + 1,
      }));
      toast.info(incoming.title || "New update");
    });
    return unsubscribe;
  },
}));

export function useNotificationsReady(): void {
  const userId = useAuthStore((s) => s.user?.id ?? null);
  const refresh = useNotificationStore((s) => s.refresh);
  const bindSocket = useNotificationStore((s) => s.bindSocket);

  useEffect(() => {
    if (!userId) return;
    void refresh();
    const unsubscribe = bindSocket();
    return unsubscribe;
  }, [userId, refresh, bindSocket]);
}
