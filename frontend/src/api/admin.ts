import { api } from "./client";
import type {
  AdminUserRow,
  AuditLog,
  DashboardMetrics,
  Paginated,
  RideCheckEvent,
  SosAlert,
  Task,
  Worker,
} from "@/types";

export interface AnalyticsPayload {
  dau: { date: string; value: number }[];
  mau: { date: string; value: number }[];
  tasks_created: { date: string; value: number }[];
  tasks_completed: { date: string; value: number }[];
  task_type_distribution: { name: string; value: number }[];
  status_distribution: { name: string; value: number }[];
  metrics: DashboardMetrics;
}

export interface PendingDocument {
  id: string;
  document_type: string;
  file_name: string;
  mime_type: string;
  file_size: number;
  status: string;
  created_at: string;
  worker_user_id: string | null;
  worker_name: string | null;
}

export interface SettingRow {
  key: string;
  value: string | number | boolean;
  value_type: string;
  description: string | null;
}

export const adminApi = {
  dashboard: () => api.get<{ metrics: DashboardMetrics }>("/admin/dashboard").then((r) => r.data.metrics),

  analytics: (days = 30) =>
    api.get<AnalyticsPayload>("/admin/analytics", { params: { days } }).then((r) => r.data),

  users: (params: { role?: string; search?: string; is_active?: boolean; page?: number; page_size?: number } = {}) =>
    api.get<Paginated<AdminUserRow>>("/admin/users", { params }).then((r) => r.data),

  setUserActive: (userId: string, isActive: boolean) =>
    api
      .patch<{ user: AdminUserRow }>(`/admin/users/${userId}/status`, null, { params: { is_active: isActive } })
      .then((r) => r.data.user),

  pendingVerifications: (page = 1, pageSize = 20) =>
    api
      .get<{ items: PendingDocument[]; total: number }>("/admin/verifications/pending", {
        params: { page, page_size: pageSize },
      })
      .then((r) => r.data),

  decideVerification: (documentId: string, approve: boolean, reason?: string) =>
    api
      .post(`/admin/verifications/${documentId}/decision`, null, {
        params: { approve, reason },
      })
      .then((r) => r.data),

  workers: (params: { search?: string; verified?: boolean; online?: boolean; page?: number; page_size?: number } = {}) =>
    api.get<Paginated<Worker>>("/admin/workers", { params }).then((r) => r.data),

  tasks: (params: { status?: string; task_type?: string; search?: string; page?: number; page_size?: number } = {}) =>
    api.get<Paginated<Task>>("/admin/tasks", { params }).then((r) => r.data),

  cancelTask: (taskId: string, reason: string) =>
    api.post<{ task: Task }>(`/admin/tasks/${taskId}/cancel`, null, { params: { reason } }).then((r) => r.data.task),

  payments: (params: { status?: string; page?: number; page_size?: number } = {}) =>
    api.get<Paginated<import("@/types").Payment>>("/admin/payments", { params }).then((r) => r.data),

  transactions: (params: { search?: string; page?: number; page_size?: number } = {}) =>
    api.get<Paginated<import("@/types").Transaction>>("/admin/transactions", { params }).then((r) => r.data),

  settings: () => api.get<{ items: SettingRow[] }>("/admin/settings").then((r) => r.data.items),

  updateSettings: (settings: Record<string, string>) =>
    api.put<{ updated: number }>("/admin/settings", { settings }).then((r) => r.data),

  auditLogs: (params: { action?: string; page?: number; page_size?: number } = {}) =>
    api.get<Paginated<AuditLog>>("/admin/audit-logs", { params }).then((r) => r.data),

  sosAlerts: (params: { status?: string; page?: number; page_size?: number } = {}) =>
    api.get<Paginated<SosAlert>>("/admin/sos-alerts", { params }).then((r) => r.data),

  resolveSosAlert: (alertId: string, note: string) =>
    api
      .post<{ alert: SosAlert }>(`/admin/sos-alerts/${alertId}/resolve`, { note: note.trim() || null })
      .then((r) => r.data.alert),

  ridecheckEvents: (page = 1, pageSize = 20) =>
    api
      .get<Paginated<RideCheckEvent>>("/admin/ridecheck", {
        params: { page, page_size: pageSize },
      })
      .then((r) => r.data),

  resolveRidecheck: (eventId: string, note: string) =>
    api
      .post<{ event: RideCheckEvent }>(`/admin/ridecheck/${eventId}/resolve`, null, {
        params: { note: note.trim() || null },
      })
      .then((r) => r.data.event),
};
