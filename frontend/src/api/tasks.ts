import { api } from "./client";
import type {
  ExpenseCategory,
  ExpenseTotals,
  FareEstimate,
  FareWarning,
  MatchResult,
  Paginated,
  ParsedTaskDraft,
  RideCheckEvent,
  RideCheckPayload,
  ShareLink,
  SosAlert,
  Task,
  TaskExecutionProof,
  TaskExpense,
  TipResult,
  TrackingSnapshot,
} from "@/types";

export interface TaskListParams {
  status?: string;
  page?: number;
  page_size?: number;
}

export interface TaskCreatePayload {
  title: string;
  description: string;
  task_type: string;
  urgency: string;
  scheduled_date?: string | null;
  scheduled_time?: string | null;
  estimated_duration_minutes?: number;
  latitude?: number | null;
  longitude?: number | null;
  address_text?: string | null;
  area_name?: string | null;
  city?: string | null;
  budget: number;
  special_requirements?: string | null;
  required_skills?: string[];
  parsed_by_ai?: boolean;
  ai_confidence?: number;
  is_round_trip?: boolean;
  pickup_latitude?: number | null;
  pickup_longitude?: number | null;
  pickup_address?: string | null;
}

export interface TaskUpdatePayload {
  title?: string;
  description?: string;
  task_type?: string;
  urgency?: string;
  scheduled_date?: string | null;
  scheduled_time?: string | null;
  estimated_duration_minutes?: number;
  latitude?: number | null;
  longitude?: number | null;
  address_text?: string | null;
  area_name?: string | null;
  city?: string | null;
  budget?: number;
  special_requirements?: string | null;
}

export interface FareEstimateRequest {
  origin_latitude?: number | null;
  origin_longitude?: number | null;
  destination_latitude?: number | null;
  destination_longitude?: number | null;
  wait_minutes?: number;
  urgency?: string;
  proposed_budget?: number | null;
  is_round_trip?: boolean;
}

export interface ExpenseDecisionPayload {
  note?: string;
}

export const tasksApi = {
  parse: (text: string) =>
    api.post<{ draft: ParsedTaskDraft }>("/tasks/parse", { text }).then((r) => r.data.draft),

  create: (payload: TaskCreatePayload) =>
    api.post<{ task: Task }>("/tasks", payload).then((r) => r.data.task),

  list: (params: TaskListParams = {}) =>
    api.get<Paginated<Task>>("/tasks", { params }).then((r) => r.data),

  get: (taskId: string) =>
    api.get<{ task: Task }>(`/tasks/${taskId}`).then((r) => r.data),

  matches: (taskId: string) =>
    api.get<{ task: Task; matches: MatchResult[]; eligible_count: number }>(`/tasks/${taskId}/matches`).then(
      (r) => r.data
    ),

  update: (taskId: string, payload: TaskUpdatePayload) =>
    api.patch<{ task: Task }>(`/tasks/${taskId}`, payload).then((r) => r.data.task),

  confirm: (taskId: string) =>
    api.post<{ task: Task }>(`/tasks/${taskId}/confirm`).then((r) => r.data.task),

  estimateFare: (payload: FareEstimateRequest) =>
    api
      .post<{ estimate: FareEstimate; warning: FareWarning | null }>("/tasks/estimate-fare", payload)
      .then((r) => r.data),

  workerStatus: (taskId: string, status: string, note?: string) =>
    api.post<{ task: Task }>(`/tasks/${taskId}/status`, { status, note }).then((r) => r.data.task),

  verifyStartOtp: (taskId: string, otp: string) =>
    api.post<{ task: Task }>(`/tasks/${taskId}/verify-start-otp`, { otp }).then((r) => r.data.task),

  requestCompletion: (taskId: string) =>
    api.post<{ task: Task }>(`/tasks/${taskId}/request-completion`).then((r) => r.data.task),

  complete: (taskId: string, otp: string) =>
    api.post<{ task: Task }>(`/tasks/${taskId}/complete`, { otp }).then((r) => r.data.task),

  verifyReturnOtp: (taskId: string, otp: string) =>
    api.post<{ task: Task }>(`/tasks/${taskId}/verify-return-otp`, { otp }).then((r) => r.data.task),

  tip: (taskId: string, amount: number) =>
    api.post<TipResult>(`/tasks/${taskId}/tip`, { amount }).then((r) => r.data),

  ridecheck: (taskId: string) =>
    api.get<RideCheckPayload>(`/tasks/${taskId}/ridecheck`).then((r) => r.data),

  acknowledgeRidecheck: (eventId: string, action: "SAFE" | "HELP", reason?: string) =>
    api
      .post<{ event: RideCheckEvent }>(`/tasks/ridecheck/${eventId}/acknowledge`, {
        action,
        reason: reason ?? null,
      })
      .then((r) => r.data.event),

  claimReservation: (taskId: string) =>
    api.post<{ task: Task }>(`/tasks/${taskId}/claim-reservation`).then((r) => r.data.task),

  confirmReadiness: (taskId: string) =>
    api.post<{ task: Task }>(`/tasks/${taskId}/confirm-readiness`, {}).then((r) => r.data.task),

  cancel: (taskId: string, reason: string) =>
    api.post<{ task: Task }>(`/tasks/${taskId}/cancel`, { reason }).then((r) => r.data.task),

  retryMatching: (taskId: string) =>
    api.post<{ task: Task }>(`/tasks/${taskId}/retry-matching`).then((r) => r.data.task),

  tracking: (taskId: string) =>
    api.get<{ tracking: TrackingSnapshot }>(`/tasks/${taskId}/tracking`).then((r) => r.data.tracking),

  // ----- proof of execution -----

  uploadProof: (taskId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api
      .post<{ proof: TaskExecutionProof }>(`/tasks/${taskId}/proof-of-execution`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data.proof);
  },

  listProofs: (taskId: string) =>
    api.get<{ items: TaskExecutionProof[] }>(`/tasks/${taskId}/proofs`).then((r) => r.data.items),

  proofFile: (taskId: string, proofId: string) =>
    api
      .get<Blob>(`/tasks/${taskId}/proofs/${proofId}/file`, { responseType: "blob" })
      .then((r) => r.data),

  // ----- incidental expenses -----

  listExpenses: (taskId: string) =>
    api
      .get<{ items: TaskExpense[]; totals: ExpenseTotals }>(`/tasks/${taskId}/expenses`)
      .then((r) => r.data),

  addExpense: (
    taskId: string,
    payload: { amount: number; category: ExpenseCategory; description: string; receipt?: File | null }
  ) => {
    const form = new FormData();
    form.append("amount", String(payload.amount));
    form.append("category", payload.category);
    form.append("description", payload.description);
    if (payload.receipt) form.append("receipt", payload.receipt);
    return api
      .post<{ expense: TaskExpense }>(`/tasks/${taskId}/expenses`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data.expense);
  },

  approveExpense: (taskId: string, expenseId: string, payload: ExpenseDecisionPayload = {}) =>
    api
      .post<{ expense: TaskExpense; totals: ExpenseTotals }>(
        `/tasks/${taskId}/expenses/${expenseId}/approve`,
        payload
      )
      .then((r) => r.data),

  rejectExpense: (taskId: string, expenseId: string, payload: ExpenseDecisionPayload = {}) =>
    api
      .post<{ expense: TaskExpense; totals: ExpenseTotals }>(
        `/tasks/${taskId}/expenses/${expenseId}/reject`,
        payload
      )
      .then((r) => r.data),

  receiptFile: (taskId: string, expenseId: string) =>
    api
      .get<Blob>(`/tasks/${taskId}/expenses/${expenseId}/receipt`, { responseType: "blob" })
      .then((r) => r.data),

  // ----- public live-tracking share link (owner only) -----

  getShareLink: (taskId: string) =>
    api.get<{ share: ShareLink | null }>(`/tasks/${taskId}/share`).then((r) => r.data.share),

  createShareLink: (taskId: string, payload: { expires_in_hours?: number; rotate?: boolean } = {}) =>
    api.post<{ share: ShareLink }>(`/tasks/${taskId}/share`, payload).then((r) => r.data.share),

  revokeShareLink: (taskId: string) =>
    api.delete<{ revoked: boolean }>(`/tasks/${taskId}/share`).then((r) => r.data.revoked),

  // ----- safety -----

  triggerSos: (
    taskId: string,
    payload: { latitude?: number | null; longitude?: number | null; message?: string | null } = {}
  ) =>
    api
      .post<{ alert: SosAlert; task: Task }>(`/tasks/${taskId}/sos`, payload)
      .then((r) => r.data),
};
