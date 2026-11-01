import { api } from "./client";
import type { BidWithTask, Task, TaskBid } from "@/types";

export interface BidCreatePayload {
  proposed_amount: number;
  note?: string | null;
  estimated_arrival_minutes?: number;
}

export const bidsApi = {
  place: (taskId: string, payload: BidCreatePayload) =>
    api.post<{ bid: TaskBid }>(`/tasks/${taskId}/bids`, payload).then((r) => r.data.bid),

  forTask: (taskId: string) =>
    api
      .get<{ items: TaskBid[]; total: number }>(`/tasks/${taskId}/bids`)
      .then((r) => r.data),

  myBid: (taskId: string) =>
    api.get<{ bid: TaskBid | null }>(`/tasks/${taskId}/my-bid`).then((r) => r.data.bid),

  myBids: () =>
    api.get<{ items: BidWithTask[]; total: number }>("/workers/me/bids").then((r) => r.data),

  accept: (bidId: string) =>
    api.post<{ task: Task }>(`/bids/${bidId}/accept`).then((r) => r.data.task),

  decline: (bidId: string) =>
    api
      .post<{ bid_id: string; status: string }>(`/bids/${bidId}/decline`)
      .then((r) => r.data),
};
