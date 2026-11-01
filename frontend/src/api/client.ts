import axios, { AxiosError, AxiosRequestConfig } from "axios";

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

export const STORAGE_KEYS = {
  access: "taskflex.access_token",
  refresh: "taskflex.refresh_token",
} as const;

export function getAccessToken(): string | null {
  return localStorage.getItem(STORAGE_KEYS.access);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(STORAGE_KEYS.refresh);
}

export function setTokens(access: string, refresh: string): void {
  localStorage.setItem(STORAGE_KEYS.access, access);
  localStorage.setItem(STORAGE_KEYS.refresh, refresh);
}

export function clearTokens(): void {
  localStorage.removeItem(STORAGE_KEYS.access);
  localStorage.removeItem(STORAGE_KEYS.refresh);
}

export const api = axios.create({
  baseURL: "/api/v1",
  timeout: 20000,
});

api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

type Envelope = { success: boolean; data?: unknown; message?: string; error?: { code: string; message: string } };

let refreshPromise: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  const refresh = getRefreshToken();
  if (!refresh) throw new ApiError("Session expired.", "UNAUTHORIZED", 401);
  const { data } = await axios.post<Envelope>(
    "/api/v1/auth/refresh",
    { refresh_token: refresh },
    { timeout: 15000 }
  );
  const tokens = data.data as { access_token: string; refresh_token: string };
  setTokens(tokens.access_token, tokens.refresh_token);
  return tokens.access_token;
}

api.interceptors.response.use(
  (response) => {
    const body = response.data as Envelope | undefined;
    if (body && typeof body === "object" && "success" in body) {
      if (body.success) {
        response.data = body.data;
        (response as unknown as { message?: string }).message = body.message;
      } else {
        const err = body.error ?? { code: "INTERNAL_ERROR", message: "Something went wrong." };
        return Promise.reject(new ApiError(err.message, err.code, response.status));
      }
    }
    return response;
  },
  async (error: AxiosError<Envelope>) => {
    const original = error.config as (AxiosRequestConfig & { _retried?: boolean }) | undefined;
    const status = error.response?.status;
    const url = original?.url ?? "";

    if (status === 401 && original && !original._retried && !url.includes("/auth/login") && !url.includes("/auth/refresh")) {
      original._retried = true;
      try {
        refreshPromise = refreshPromise ?? refreshAccessToken();
        const token = await refreshPromise;
        refreshPromise = null;
        original.headers = { ...(original.headers ?? {}), Authorization: `Bearer ${token}` };
        return api.request(original);
      } catch (refreshError) {
        refreshPromise = null;
        clearTokens();
        window.dispatchEvent(new CustomEvent("taskflex:session-expired"));
        return Promise.reject(
          new ApiError("Your session has expired. Please sign in again.", "UNAUTHORIZED", 401)
        );
      }
    }

    const body = error.response?.data;
    if (body && typeof body === "object" && "error" in body && body.error) {
      return Promise.reject(new ApiError(body.error.message, body.error.code, status ?? 500));
    }
    if (status === 422) {
      const detail = (error.response?.data as { detail?: unknown })?.detail;
      const message =
        Array.isArray(detail) && detail.length > 0
          ? `${(detail[0] as { msg?: string }).msg ?? "Validation failed."}`
          : "Please check the form for errors.";
      return Promise.reject(new ApiError(message, "VALIDATION_ERROR", 422));
    }
    return Promise.reject(new ApiError(error.message || "Network error.", "NETWORK_ERROR", status ?? 0));
  }
);

export function apiMessage(response: unknown): string | undefined {
  return (response as { message?: string } | undefined)?.message;
}

export async function uploadFile(url: string, file: File, fields: Record<string, string> = {}): Promise<unknown> {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) form.append(key, value);
  form.append("file", file);
  const response = await api.post(url, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
}
