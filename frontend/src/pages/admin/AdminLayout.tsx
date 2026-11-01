import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  BadgeCheck,
  BarChart3,
  ClipboardList,
  CreditCard,
  FileCheck2,
  LayoutDashboard,
  LogOut,
  RouteOff,
  ScrollText,
  Settings as SettingsIcon,
  Scale,
  ShieldAlert,
  Siren,
  Users as UsersIcon,
  X,
} from "lucide-react";
import { useAuthStore } from "@/stores/auth";
import { Avatar } from "@/components/ui";
import { cn } from "@/lib/utils";
import { SOS_RESOLVED_EVENT, WS_EVENTS } from "@/lib/constants";
import { wsService } from "@/services/websocket";
import { toast } from "@/stores/toast";

const NAV = [
  { to: "/admin", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/admin/users", label: "Users", icon: UsersIcon },
  { to: "/admin/workers", label: "Workers", icon: BadgeCheck },
  { to: "/admin/verifications", label: "Verifications", icon: FileCheck2 },
  { to: "/admin/tasks", label: "Tasks", icon: ClipboardList },
  { to: "/admin/sos", label: "SOS alerts", icon: Siren },
  { to: "/admin/ridecheck", label: "RideCheck", icon: RouteOff },
  { to: "/admin/payments", label: "Payments", icon: CreditCard },
  { to: "/admin/disputes", label: "Disputes", icon: Scale },
  { to: "/admin/reports", label: "Reports", icon: BarChart3 },
  { to: "/admin/settings", label: "Settings", icon: SettingsIcon },
  { to: "/admin/audit-logs", label: "Audit logs", icon: ScrollText },
];

export default function AdminLayout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [emergency, setEmergency] = useState<{ taskId: string | null; message: string | null } | null>(null);

  const currentSection =
    NAV.find((item) => (item.end ? pathname === item.to : pathname.startsWith(`${item.to}/`) || pathname === item.to))
      ?.to ?? "/admin";

  useEffect(() => {
    const off = wsService.on(WS_EVENTS.EMERGENCY_ALERT, (frame) => {
      const data = frame.data as { task_id?: string; message?: string | null };
      setEmergency({ taskId: data.task_id ?? null, message: data.message ?? null });
      toast.error("Emergency SOS raised — open the SOS desk now.");
    });
    return off;
  }, []);

  useEffect(() => {
    const clear = () => setEmergency(null);
    window.addEventListener(SOS_RESOLVED_EVENT, clear);
    return () => window.removeEventListener(SOS_RESOLVED_EVENT, clear);
  }, []);

  return (
    <div className="min-h-screen bg-slate-100">
      <div className="mx-auto flex max-w-7xl">
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-slate-800 bg-slate-900 px-4 py-6 lg:flex">
          <div className="px-2">
            <span className="text-lg font-extrabold tracking-tight text-white">
              Task<span className="text-primary-400">Flex</span>
            </span>
            <p className="mt-0.5 text-xs font-medium uppercase tracking-wider text-slate-500">Admin console</p>
          </div>
          <nav className="mt-8 min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-slate-800 text-white"
                      : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-100"
                  )
                }
              >
                <item.icon className="h-[18px] w-[18px]" />
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="shrink-0 border-t border-slate-800 pt-4">
            <div className="flex items-center gap-2.5 rounded-lg px-2 py-2">
              <Avatar name={user?.full_name} url={user?.avatar_url} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-slate-100">{user?.full_name}</p>
                <p className="truncate text-xs text-slate-500">{user?.email}</p>
              </div>
            </div>
            <button
              onClick={() => {
                logout();
                navigate("/login");
              }}
              className="mt-2 w-full rounded-lg px-3 py-2 text-left text-sm font-medium text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            >
              Sign out
            </button>
          </div>
        </aside>

        <main className="min-h-screen flex-1">
          <header className="flex items-center justify-between border-b border-slate-200 bg-white px-5 py-3">
            <div className="flex items-center gap-2 lg:hidden">
              <span className="text-lg font-extrabold text-slate-900">
                Task<span className="text-primary-600">Flex</span>
              </span>
              <span className="rounded bg-slate-900 px-1.5 py-0.5 text-[10px] font-bold uppercase text-white">
                admin
              </span>
            </div>
            <div className="hidden items-center gap-2 lg:flex">
              <ShieldAlert className="h-4 w-4 text-slate-400" />
              <span className="text-sm text-slate-500">Signed in as administrator</span>
            </div>
            <div className="flex items-center gap-2">
              <select
                value={currentSection}
                onChange={(e) => navigate(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm lg:hidden"
                aria-label="Admin section"
              >
                {NAV.map((n) => (
                  <option key={n.to} value={n.to}>
                    {n.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => {
                  logout();
                  navigate("/login");
                }}
                className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
              >
                <LogOut className="h-4 w-4" aria-hidden />
                <span className="hidden sm:inline">Sign out</span>
              </button>
            </div>
          </header>
          {emergency && (
            <div className="flex items-start gap-3 bg-red-600 px-5 py-3 text-white">
              <Siren className="mt-0.5 h-5 w-5 shrink-0 animate-pulse" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-bold">Emergency SOS — a task just flipped to EMERGENCY_ALERT</p>
                <p className="mt-0.5 text-xs text-red-100">
                  {emergency.message ?? "Open the SOS desk to review the frozen GPS trail and respond."}
                </p>
                <Link to="/admin/sos" className="mt-1 inline-block text-xs font-semibold underline">
                  Open SOS desk
                </Link>
              </div>
              <button
                type="button"
                onClick={() => setEmergency(null)}
                className="rounded p-1 text-red-100 hover:bg-red-700"
                aria-label="Dismiss emergency banner"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>
          )}
          <div className="px-5 py-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
