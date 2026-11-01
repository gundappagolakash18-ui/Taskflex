import { api } from "./client";
import type {
  Conversation,
  ConversationOpen,
  Dispute,
  Message,
  Paginated,
  Payment,
  Rating,
  Review,
} from "@/types";

export const conversationsApi = {
  list: () =>
    api.get<{ items: Conversation[]; total: number }>("/conversations").then((r) => r.data.items),

  open: (taskId: string) =>
    api
      .post<{ conversation: ConversationOpen }>(
        `/conversations?task_id=${encodeURIComponent(taskId)}`
      )
      .then((r) => r.data.conversation),

  messages: (conversationId: string, page = 1, pageSize = 50) =>
    api
      .get<Paginated<Message>>(`/conversations/${conversationId}/messages`, {
        params: { page, page_size: pageSize },
      })
      .then((r) => r.data),

  send: (conversationId: string, body: string) =>
    api
      .post<{ message: Message }>(`/conversations/${conversationId}/messages`, { body })
      .then((r) => r.data.message),
};

export interface RatingSubmitPayload {
  task_id: string;
  score: number;
  comment?: string;
  prefer_worker?: boolean;
  tip_amount?: number;
}

export interface RatingSubmitResult {
  rating: Rating;
  payment?: CheckoutDetails | null;
}

export const ratingsApi = {
  submit: (payload: RatingSubmitPayload) =>
    api.post<RatingSubmitResult>("/ratings", payload).then((r) => r.data),

  forTask: (taskId: string) =>
    api.get<{ items: Rating[] }>(`/tasks/${taskId}/ratings`).then((r) => r.data.items),

  workerReviews: (workerUserId: string, page = 1, pageSize = 10) =>
    api
      .get<Paginated<Review>>(`/workers/${workerUserId}/reviews`, {
        params: { page, page_size: pageSize },
      })
      .then((r) => r.data),

  workerSummary: (workerUserId: string) =>
    api
      .get<{
        summary: { average: number; count: number; distribution: Record<string, number> };
      }>(`/workers/${workerUserId}/rating-summary`)
      .then((r) => r.data.summary),
};

export const disputesApi = {
  create: (payload: { task_id: string; reason: string; description: string }) =>
    api.post<{ dispute: Dispute }>("/disputes", payload).then((r) => r.data.dispute),

  list: (status?: string, page = 1, pageSize = 20) =>
    api.get<Paginated<Dispute>>("/disputes", { params: { status, page, page_size: pageSize } }).then((r) => r.data),

  get: (disputeId: string) =>
    api.get<{ dispute: Dispute }>(`/disputes/${disputeId}`).then((r) => r.data.dispute),

  resolve: (disputeId: string, payload: { status?: string; resolution_note: string }) =>
    api.post<{ dispute: Dispute }>(`/disputes/${disputeId}/resolve`, payload).then((r) => r.data.dispute),
};

export interface CheckoutDetails {
  required: boolean;
  provider: string;
  status?: string;
  key_id?: string;
  order_id?: string;
  amount?: number; // smallest currency unit (paise)
  currency?: string;
  name?: string;
  description?: string;
  prefill?: { name?: string; email?: string };
}

export const paymentsApi = {
  myPayments: (page = 1, pageSize = 20) =>
    api.get<Paginated<Payment>>("/payments", { params: { page, page_size: pageSize } }).then((r) => r.data),

  forTask: (taskId: string) =>
    api.get<{ payment: Payment }>(`/payments/for-task/${taskId}`).then((r) => r.data.payment),

  checkout: (taskId: string) =>
    api.get<CheckoutDetails>(`/payments/checkout/${taskId}`).then((r) => r.data),

  verify: (payload: { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }) =>
    api.post<{ payment: Payment }>("/payments/verify", payload).then((r) => r.data.payment),
};
