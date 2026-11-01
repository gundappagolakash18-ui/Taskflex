import { api } from "./client";
import type { PublicTrackingSnapshot } from "@/types";

export const publicApi = {
  track: (token: string) =>
    api
      .get<{ tracking: PublicTrackingSnapshot }>(`/public/track/${encodeURIComponent(token)}`)
      .then((r) => r.data.tracking),
};
