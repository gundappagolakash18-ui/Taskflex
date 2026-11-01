import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { CalendarClock, Clock, MapPin, RotateCcw } from "lucide-react";

import { tasksApi } from "@/api/tasks";
import { workersApi } from "@/api/workers";
import { Badge, Button, Card, EmptyState, PageLoader } from "@/components/ui";
import { TASK_TYPE_ICONS, TASK_TYPE_LABELS } from "@/lib/constants";
import { errorMessage, formatDateTime, formatMoney } from "@/lib/utils";
import { toast } from "@/stores/toast";

export default function WorkerScheduledBoard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["scheduled-board"],
    queryFn: () => workersApi.scheduledBoard(),
    refetchInterval: 30_000,
  });

  const claimMutation = useMutation({
    mutationFn: (taskId: string) => tasksApi.claimReservation(taskId),
    onSuccess: (task) => {
      toast.success("Slot reserved — confirm readiness 45 minutes before the start time.");
      void queryClient.invalidateQueries({ queryKey: ["scheduled-board"] });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      navigate(`/worker/tasks/${task.id}`);
    },
    onError: (error) => {
      toast.error(errorMessage(error));
      void queryClient.invalidateQueries({ queryKey: ["scheduled-board"] });
    },
  });

  if (query.isLoading) return <PageLoader label="Checking the scheduled board…" />;

  const slots = query.data?.items ?? [];

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-bold text-slate-900">
          <CalendarClock className="h-5 w-5 text-primary-600" aria-hidden /> Scheduled board
        </h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Reserve future errands at a fixed time. You must confirm readiness 45 minutes before the start, otherwise the
          slot is released back to live dispatch.
        </p>
      </div>

      {query.isError ? (
        <EmptyState icon="⚠️" title="Couldn't load the board" description={errorMessage(query.error)} />
      ) : slots.length === 0 ? (
        <EmptyState
          icon="🗓️"
          title="No open scheduled slots"
          description="Customers' future-dated tasks appear here once they're more than 60 minutes away. Check back soon."
          action={
            <Link to="/worker">
              <Button variant="secondary">Back to home</Button>
            </Link>
          }
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {slots.map((slot) => (
            <Card key={slot.task_id}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-amber-50 text-2xl">
                    {TASK_TYPE_ICONS[slot.task_type] ?? "🧭"}
                  </div>
                  <div className="min-w-0">
                    <Link
                      to={`/worker/tasks/${slot.task_id}`}
                      className="truncate text-sm font-bold text-slate-900 hover:text-primary-700"
                    >
                      {slot.title}
                    </Link>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {TASK_TYPE_LABELS[slot.task_type] ?? slot.task_type}
                      {slot.area_name ? ` · ${slot.area_name}` : ""}
                      {slot.city ? `, ${slot.city}` : ""}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-lg font-bold text-slate-900">{formatMoney(slot.budget, slot.currency)}</p>
                  <p className="text-xs text-slate-400">~{slot.estimated_duration_minutes} min</p>
                </div>
              </div>

              <p className="mt-3 line-clamp-2 text-sm text-slate-600">{slot.description}</p>

              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <Badge className="bg-amber-100 text-amber-800">
                  <Clock className="h-3 w-3" aria-hidden />
                  {slot.scheduled_for ? formatDateTime(slot.scheduled_for) : "Time to be confirmed"}
                </Badge>
                {slot.distance_km != null && (
                  <Badge className="bg-slate-100 text-slate-600">
                    <MapPin className="h-3 w-3" aria-hidden /> {slot.distance_km.toFixed(1)} km away
                  </Badge>
                )}
                {slot.is_round_trip && (
                  <Badge className="bg-teal-100 text-teal-800">
                    <RotateCcw className="h-3 w-3" aria-hidden /> Round trip
                  </Badge>
                )}
              </div>

              {slot.address_text && <p className="mt-2 text-xs text-slate-400">{slot.address_text}</p>}

              <div className="mt-4 flex gap-2">
                <Button
                  className="flex-1"
                  loading={claimMutation.isPending && claimMutation.variables === slot.task_id}
                  onClick={() => claimMutation.mutate(slot.task_id)}
                >
                  Reserve this slot
                </Button>
                <Link to={`/worker/tasks/${slot.task_id}`} className="flex-1">
                  <Button variant="secondary" className="w-full">
                    View details
                  </Button>
                </Link>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
