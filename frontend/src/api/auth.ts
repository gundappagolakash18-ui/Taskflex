import { api } from "./client";
import type { AuthResponse, AuthUser, RegisterResponse } from "@/types";

export interface RegisterPayload {
  role: "CUSTOMER" | "WORKER";
  full_name: string;
  email: string;
  phone: string;
  password: string;
  city?: string;
}

export const authApi = {
  register: (payload: RegisterPayload) =>
    api.post<RegisterResponse>("/auth/register", payload).then((r) => r.data),

  login: (identifier: string, password: string) =>
    api.post<AuthResponse>("/auth/login", { identifier, password }).then((r) => r.data),

  refresh: (refresh_token: string) =>
    api.post<AuthResponse["tokens"]>("/auth/refresh", { refresh_token }).then((r) => r.data),

  me: () => api.get<{ user: AuthUser }>("/auth/me").then((r) => r.data.user),

  forgotPassword: (email: string) =>
    api.post<{ sent: boolean; reset_token?: string }>("/auth/forgot-password", { email }).then((r) => r.data),

  resetPassword: (token: string, new_password: string) =>
    api.post<{ reset: boolean }>("/auth/reset-password", { token, new_password }).then((r) => r.data),

  verifyEmail: (identifier: string, code: string) =>
    api.post<AuthResponse>("/auth/verify-email", { identifier, code }).then((r) => r.data),

  resendOtp: (identifier: string) =>
    api.post<{ message: string }>("/auth/resend-otp", { identifier }).then((r) => r.data),

  googleConfig: () =>
    api.get<{ enabled: boolean; client_id: string | null }>("/auth/google/config").then((r) => r.data),

  googleAuth: (credential: string, role?: "CUSTOMER" | "WORKER") =>
    api
      .post<AuthResponse & { created: boolean }>(
        "/auth/google",
        role ? { credential, role } : { credential }
      )
      .then((r) => r.data),
};
