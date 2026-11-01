import { api } from "./client";
import { uploadFile } from "./client";
import type {
  AvailabilityEntry,
  EarningsSummary,
  OfferWithTask,
  Paginated,
  ScheduledSlot,
  Worker,
  WorkerTierOverview,
} from "@/types";

export interface WorkerFilters {
  search?: string;
  city?: string;
  skill?: string;
  online_only?: boolean;
  page?: number;
  page_size?: number;
}

export interface WorkerProfileUpdatePayload {
  bio?: string;
  address?: string;
  area?: string;
  city?: string;
  latitude?: number;
  longitude?: number;
  experience_years?: number;
  languages?: string;
  working_radius_km?: number;
  max_concurrent_tasks?: number;
  skill_slugs?: string[];
  availability?: AvailabilityEntry[];
}

export const workersApi = {
  list: (params: WorkerFilters = {}) =>
    api.get<Paginated<Worker>>("/workers", { params }).then((r) => r.data),

  get: (workerUserId: string) =>
    api.get<{ worker: Worker }>(`/workers/${workerUserId}`).then((r) => r.data.worker),

  myProfile: () =>
    api.get<{ worker: Worker }>("/workers/me/profile").then((r) => r.data.worker),

  updateProfile: (payload: WorkerProfileUpdatePayload) =>
    api.patch<{ worker: Worker }>("/workers/me/profile", payload).then((r) => r.data.worker),

  setAvailability: (entries: AvailabilityEntry[]) =>
    api.put<{ worker: Worker }>("/workers/me/availability", entries).then((r) => r.data.worker),

  setOnline: (is_online: boolean) =>
    api.post<{ worker: Worker }>("/workers/me/online", { is_online }).then((r) => r.data.worker),

  myOffers: () =>
    api.get<{ items: OfferWithTask[]; total: number }>("/workers/me/offers").then((r) => r.data),

  acceptOffer: (offerId: string) =>
    api.post<{ task: import("@/types").Task }>(`/workers/offers/${offerId}/accept`).then((r) => r.data.task),

  rejectOffer: (offerId: string) =>
    api.post<{ rejected: boolean }>(`/workers/offers/${offerId}/reject`).then((r) => r.data),

  myEarnings: () =>
    api.get<{ earnings: EarningsSummary }>("/workers/me/earnings").then((r) => r.data.earnings),

  myTier: () =>
    api.get<WorkerTierOverview>("/workers/me/tier").then((r) => r.data),

  scheduledBoard: () =>
    api
      .get<{ items: ScheduledSlot[]; total: number }>("/workers/scheduled-board")
      .then((r) => r.data),

  myDocuments: () =>
    api.get<{ items: import("@/types").WorkerDocument[] }>("/workers/me/documents").then((r) => r.data.items),

  uploadDocument: (file: File, documentType: string) =>
    uploadFile("/workers/me/documents", file, { document_type: documentType }),

  deleteDocument: (documentId: string) =>
    api.delete(`/workers/me/documents/${documentId}`).then((r) => r.data),
};
