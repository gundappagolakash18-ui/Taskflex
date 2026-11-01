import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Bell, Briefcase, CalendarClock, Home, IndianRupee, MessageSquare, Settings, Star } from "lucide-react";
import { useAuthStore } from "@/stores/auth";
import { useNotificationStore } from "@/stores/notifications";
import { Avatar } from "@/components/ui";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/worker", label: "Home", icon: Home, end: true },
  { to: "/worker/offers", label: "Offers", icon: Briefcase },
  { to: "/worker/scheduled", label: "Scheduled", icon: CalendarClock },
  { to: "/worker/earnings", label: "Earnings", icon: IndianRupee },
  { to: "/worker/reviews", label: "Reviews", icon: Star },
  { to: "/worker/messages", label: "Messages", icon: MessageSquare },
  { to: "/worker/settings", label: "Settings", icon: Settings },
];

const MOBILE_NAV = [
  { to: "/worker", label: "Home", icon: Home, end: true },
  { to: "/worker/offers", label: "Offers", icon: Briefcase },
  { to: "/worker/scheduled", label: "Scheduled", icon: CalendarClock },
  { to: "/worker/earnings", label: "Earnings", icon: IndianRupee },
  { to: "/worker/messages", label: "Chats", icon: MessageSquare },
  { to: "/worker/settings", label: "Settings", icon: Settings },
];

export default function WorkerLayout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const unread = useNotificationStore((s) => s.unread);
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="mx-auto flex max-w-6xl">
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white px-3 py-5 md:flex">
          <div className="px-2">
            <span className="text-lg font-extrabold tracking-tight text-slate-900">
              Task<span className="text-primary-600">Flex</span>
            </span>
            <span className="ml-1.5 rounded bg-accent-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-accent-700">
              Runner
            </span>
          </div>
          <nav className="mt-6 flex-1 space-y-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                    isActive ? "bg-primary-50 text-primary-700" : "text-slate-600 hover:bg-slate-100"
                  )
                }
              >
                <item.icon className="h-[18px] w-[18px]" />
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="border-t border-slate-100 pt-3">
            <button
              onClick={() => navigate("/worker/notifications")}
              className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
            >
              <span className="flex items-center gap-3">
                <Bell className="h-[18px] w-[18px]" /> Notifications
              </span>
              {unread > 0 && (
                <span className="rounded-full bg-red-500 px-1.5 py-0.5 text-[10px] font-bold text-white">{unread}</span>
              )}
            </button>
            <div className="mt-2 flex items-center gap-2.5 rounded-lg px-3 py-2">
              <Avatar name={user?.full_name} url={user?.avatar_url} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-slate-800">{user?.full_name}</p>
                <p className="truncate text-xs text-slate-400">{user?.email}</p>
              </div>
            </div>
            <button
              onClick={() => {
                logout();
                navigate("/login");
              }}
              className="mt-1 w-full rounded-lg px-3 py-2 text-left text-sm font-medium text-slate-500 hover:bg-slate-100"
            >
              Sign out
            </button>
          </div>
        </aside>

        <main className="min-h-screen flex-1 pb-20 md:pb-6">
          <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur md:hidden">
            <span className="text-lg font-extrabold text-slate-900">
              Task<span className="text-primary-600">Flex</span>
            </span>
            <button
              onClick={() => navigate("/worker/notifications")}
              className="relative rounded-lg p-2 text-slate-600 hover:bg-slate-100"
              aria-label="Notifications"
            >
              <Bell className="h-5 w-5" />
              {unread > 0 && (
                <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                  {unread > 9 ? "9+" : unread}
                </span>
              )}
            </button>
          </header>
          <Outlet />
        </main>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-6 border-t border-slate-200 bg-white pb-[env(safe-area-inset-bottom)] md:hidden">
        {MOBILE_NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "flex flex-col items-center gap-0.5 py-2.5 text-[10px] font-medium",
                isActive ? "text-primary-600" : "text-slate-500"
              )
            }
          >
            <item.icon className="h-5 w-5" />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
