import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import {
  AlertTriangle,
  Clock,
  MapPin,
  Navigation,
  RefreshCw,
  ShieldCheck,
  Star,
  Siren,
} from "lucide-react";

import { publicApi } from "@/api/public";
import { ApiError } from "@/api/client";
import { Avatar, Button, Card, PageLoader } from "@/components/ui";
import { StatusBadge } from "@/components/StatusBadge";
import LiveTrackingMap from "@/components/tracking/LiveTrackingMap";
import { cn, formatDateTime, timeAgo } from "@/lib/utils";

export default function PublicTrack() {
  const { token = "" } = useParams();

  const query = useQuery({
    queryKey: ["public-track", token],
    queryFn: () => publicApi.track(token),
    enabled: token.length > 0,
    refetchInterval: 8_000,
    staleTime: 0,
    retry: false,
  });

  const error = query.error;
  const expired = error instanceof ApiError && (error.status === 410 || error.code === "SHARE_LINK_EXPIRED");
  const invalid = error instanceof ApiError && error.status === 404;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-600 text-sm font-black text-white">
              TF
            </span>
            <div>
              <p className="text-sm font-bold text-slate-900">TaskFlex</p>
              <p className="text-[11px] text-slate-400">Live errand tracking</p>
            </div>
          </div>
          <span className="flex items-center gap-1 text-[11px] text-slate-400">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> Read-only link
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-4 px-4 py-6">
        {query.isLoading ? (
          <PageLoader label="Loading live tracking…" />
        ) : expired ? (
          <Card className="p-6 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-amber-100">
              <Clock className="h-7 w-7 text-amber-600" aria-hidden />
            </div>
            <h1 className="mt-4 text-xl font-bold text-slate-900">This tracking link expired</h1>
            <p className="mx-auto mt-2 max-w-sm text-sm text-slate-500">
              Share links are intentionally short-lived. Ask the person who sent it to create a fresh link from their
              task page.
            </p>
          </Card>
        ) : invalid || (!query.data && !query.isLoading) ? (
          <Card className="p-6 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-red-100">
              <AlertTriangle className="h-7 w-7 text-red-600" aria-hidden />
            </div>
            <h1 className="mt-4 text-xl font-bold text-slate-900">This link isn't valid</h1>
            <p className="mx-auto mt-2 max-w-sm text-sm text-slate-500">
              The tracking link is unknown or has been revoked. Check the link you were sent, or ask for a new one.
            </p>
          </Card>
        ) : query.data ? (
          (() => {
            const tracking = query.data;
            const destination =
              tracking.destination.latitude != null && tracking.destination.longitude != null
                ? {
                    latitude: tracking.destination.latitude,
                    longitude: tracking.destination.longitude,
                  }
                : null;
            const emergency = tracking.status === "EMERGENCY_ALERT";

            return (
              <>
                <Card className={cn(emergency && "border-red-300 bg-red-50")}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Errand status</p>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <StatusBadge status={tracking.status} />
                        {tracking.tracking_active ? (
                          <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700">
                            <span className="relative flex h-2 w-2">
                              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" aria-hidden />
                              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" aria-hidden />
                            </span>
                            Live
                          </span>
                        ) : (
                          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-500">
                            Tracking ended
                          </span>
                        )}
                      </div>
                      {(tracking.destination.area_name || tracking.destination.city) && (
                        <p className="mt-2 flex items-center gap-1.5 text-sm text-slate-600">
                          <MapPin className="h-4 w-4 text-slate-400" aria-hidden />
                          {[tracking.destination.area_name, tracking.destination.city].filter(Boolean).join(", ")}
                        </p>
                      )}
                    </div>
                    <Button variant="ghost" onClick={() => void query.refetch()} loading={query.isFetching} aria-label="Refresh">
                      <RefreshCw className="h-4 w-4" aria-hidden />
                    </Button>
                  </div>

                  {emergency && (
                    <p className="mt-3 flex items-start gap-2 rounded-lg bg-red-100 px-3 py-2 text-sm font-medium text-red-800">
                      <Siren className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                      An emergency alert was raised on this errand. TaskFlex support has been paged. If anyone is in
                      immediate danger, contact local emergency services.
                    </p>
                  )}

                  <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
                    <div className="rounded-xl bg-slate-50 p-3">
                      <p className="flex items-center gap-1 text-[11px] text-slate-400">
                        <Clock className="h-3 w-3" aria-hidden /> ETA
                      </p>
                      <p className="mt-0.5 text-lg font-bold text-slate-900">
                        {tracking.eta_minutes != null ? `${Math.round(tracking.eta_minutes)} min` : "—"}
                      </p>
                    </div>
                    <div className="rounded-xl bg-slate-50 p-3">
                      <p className="flex items-center gap-1 text-[11px] text-slate-400">
                        <Navigation className="h-3 w-3" aria-hidden /> Remaining
                      </p>
                      <p className="mt-0.5 text-lg font-bold text-slate-900">
                        {tracking.remaining_km != null ? `${tracking.remaining_km.toFixed(1)} km` : "—"}
                      </p>
                    </div>
                    <div className="col-span-2 rounded-xl bg-slate-50 p-3 sm:col-span-1">
                      <p className="text-[11px] text-slate-400">Last position</p>
                      <p className="mt-0.5 text-sm font-medium text-slate-800">
                        {tracking.latest ? timeAgo(tracking.latest.recorded_at) : "Waiting for a fix…"}
                      </p>
                    </div>
                  </div>
                </Card>

                <Card className="p-0">
                  {destination ? (
                    <LiveTrackingMap
                      className="h-[420px] w-full rounded-t-xl"
                      destination={destination}
                      route={tracking.route?.coordinates ?? null}
                      update={tracking.latest}
                    />
                  ) : (
                    <div className="p-6 text-center text-sm text-slate-500">
                      The destination for this errand isn't pinned to a map, so live positions can't be drawn.
                    </div>
                  )}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-4 py-2 text-[11px] text-slate-400">
                    <span>Updates automatically every few seconds.</span>
                    {tracking.shared_until && <span>Link valid until {formatDateTime(tracking.shared_until)}</span>}
                  </div>
                </Card>

                <Card>
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Your runner</h2>
                  {tracking.worker ? (
                    <div className="mt-3 flex items-center gap-3">
                      <Avatar name={tracking.worker.full_name} url={tracking.worker.avatar_url} />
                      <div className="min-w-0">
                        <p className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
                          {tracking.worker.full_name ?? "TaskFlex runner"}
                          {tracking.worker.is_verified && (
                            <ShieldCheck className="h-4 w-4 text-emerald-600" aria-label="Verified runner" />
                          )}
                        </p>
                        <p className="flex items-center gap-1 text-xs text-amber-600">
                          <Star className="h-3 w-3 fill-amber-400 text-amber-400" aria-hidden />
                          {tracking.worker.rating_average.toFixed(1)}
                          <span className="text-slate-400">({tracking.worker.rating_count})</span>
                        </p>
                      </div>
                    </div>
                  ) : (
                    <p className="mt-2 text-sm text-slate-500">A runner hasn't been assigned yet.</p>
                  )}
                  <p className="mt-4 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
                    For everyone's privacy this link never shows the customer's name, phone number, address text or the
                    task id. The person who shared it can revoke it at any time.
                  </p>
                </Card>
              </>
            );
          })()
        ) : null}
      </main>

      <footer className="mx-auto max-w-3xl px-4 pb-8 text-center text-[11px] text-slate-400">
        Powered by TaskFlex · Live positions are approximate and may lag a few seconds.
      </footer>
    </div>
  );
}
