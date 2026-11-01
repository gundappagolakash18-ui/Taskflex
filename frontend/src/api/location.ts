import { api } from "./client";

export interface GeocodeResult {
  display_name: string;
  latitude: number;
  longitude: number;
  provider: string;
  map_embed_url: string;
}

export const locationApi = {
  geocode: (query: string) =>
    api.post<{ result: GeocodeResult | null }>("/location/geocode", { query }).then((r) => r.data.result),

  mapUrl: (latitude: number, longitude: number, zoom = 15) =>
    api
      .get<{ url: string }>("/location/map-url", { params: { latitude, longitude, zoom } })
      .then((r) => r.data.url),
};

export function documentDownloadUrl(documentId: string): string {
  return `/api/v1/uploads/documents/${documentId}`;
}
