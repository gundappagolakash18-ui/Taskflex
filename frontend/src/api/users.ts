import { api } from "./client";
import type {
  AffinityList,
  AuthUser,
  Paginated,
  SavedLocation,
  Transaction,
  Wallet,
} from "@/types";

export const usersApi = {
  me: () => api.get<{ user: AuthUser }>("/users/me").then((r) => r.data.user),

  updateMe: (payload: { full_name?: string; phone?: string; avatar_url?: string; city?: string }) =>
    api.patch<{ user: AuthUser }>("/users/me", payload).then((r) => r.data.user),

  wallet: () => api.get<{ wallet: Wallet }>("/users/me/wallet").then((r) => r.data.wallet),

  transactions: (page = 1, pageSize = 20) =>
    api
      .get<Paginated<Transaction>>("/users/me/transactions", { params: { page, page_size: pageSize } })
      .then((r) => r.data),

  locations: () => api.get<{ items: SavedLocation[] }>("/users/me/locations").then((r) => r.data.items),

  createLocation: (payload: {
    label: string;
    address: string;
    area?: string | null;
    city?: string | null;
    latitude: number;
    longitude: number;
    is_default?: boolean;
  }) =>
    api
      .post<{ location: SavedLocation }>("/users/me/locations", payload)
      .then((r) => r.data.location),

  deleteLocation: (locationId: string) =>
    api.delete(`/users/me/locations/${locationId}`).then((r) => r.data),

  affinities: () =>
    api.get<AffinityList>("/users/me/worker-affinities").then((r) => r.data),

  preferWorker: (workerId: string) =>
    api
      .post<{ worker_id: string; affinity_type: string }>(`/users/workers/${workerId}/prefer`)
      .then((r) => r.data),

  removePreferredWorker: (workerId: string) =>
    api.delete<{ removed: boolean }>(`/users/workers/${workerId}/prefer`).then((r) => r.data),

  blacklistWorker: (workerId: string) =>
    api
      .post<{ worker_id: string; affinity_type: string }>(`/users/workers/${workerId}/blacklist`)
      .then((r) => r.data),

  unblacklistWorker: (workerId: string) =>
    api.delete<{ removed: boolean }>(`/users/workers/${workerId}/blacklist`).then((r) => r.data),
};
