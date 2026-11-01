import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AuthUser } from "@/types";
import { clearTokens, setTokens } from "@/api/client";

interface AuthState {
  user: AuthUser | null;
  setAuth: (user: AuthUser, accessToken: string, refreshToken: string) => void;
  setUser: (user: AuthUser) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      setAuth: (user, accessToken, refreshToken) => {
        setTokens(accessToken, refreshToken);
        set({ user });
      },
      setUser: (user) => set({ user }),
      logout: () => {
        clearTokens();
        set({ user: null });
      },
    }),
    {
      name: "taskflex.auth",
      partialize: (state) => ({ user: state.user }),
    }
  )
);
