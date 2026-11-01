import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuthStore } from "@/stores/auth";
import type { UserRole } from "@/types";
import { PageLoader } from "@/components/ui";

export function RequireRole({ roles }: { roles: UserRole[] }) {
  const user = useAuthStore((s) => s.user);
  const location = useLocation();

  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  if (!roles.includes(user.role)) {
    const home = user.role === "ADMIN" ? "/admin" : user.role === "WORKER" ? "/worker" : "/app";
    return <Navigate to={home} replace />;
  }
  return <Outlet />;
}

export function HomeRedirect() {
  const user = useAuthStore((s) => s.user);
  if (!user) return <Navigate to="/" replace />;
  if (user.role === "ADMIN") return <Navigate to="/admin" replace />;
  if (user.role === "WORKER") return <Navigate to="/worker" replace />;
  return <Navigate to="/app" replace />;
}

export function GuestOnly() {
  const user = useAuthStore((s) => s.user);
  if (user) return <HomeRedirect />;
  return <Outlet />;
}

export function AppSuspenseFallback() {
  return <PageLoader />;
}
