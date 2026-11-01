import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  Ban,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  IndianRupee,
  KeyRound,
  Lock,
  MapPin,
  MessageCircle,
  Navigation,
  RefreshCw,
  RotateCcw,
  Sparkles,
  Star,
  User as UserIcon,
} from "lucide-react";

import { cn, errorMessage, formatDateTime, formatMoney, timeAgo } from "@/lib/utils";
import {
  SOS_STATUSES,
  TASK_STATUS_LABELS,
  TASK_TYPE_ICONS,
  TASK_TYPE_LABELS,
  TRACKABLE_STATUSES,
  URGENCY_LABELS,
  WS_EVENTS,
} from "@/lib/constants";
import { Avatar, Badge, Button, Card, EmptyState, Field, Modal, PageLoader, Textarea } from "@/components/ui";
import { StatusBadge } from "@/components/StatusBadge";
import { disputesApi, paymentsApi, ratingsApi, conversationsApi } from "@/api";
import { tasksApi } from "@/api/tasks";
import { openRazorpayCheckout } from "@/lib/razorpay";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";
import { wsService } from "@/services/websocket";
import LiveTrackingMap from "@/components/tracking/LiveTrackingMap";
import { useTaskTracking } from "@/hooks/useTaskTracking";
import { useWorkerLocationTracker } from "@/hooks/useWorkerLocationTracker";
import { OtpEntryModal } from "@/components/task/OtpEntryModal";
import { ProofOfExecutionCard } from "@/components/task/ProofOfExecutionCard";
import { ExpenseLedgerCard } from "@/components/task/ExpenseLedgerCard";
import { ShareTrackingCard } from "@/components/task/ShareTrackingCard";
import { SosButton } from "@/components/task/SosButton";
import RideCheckBanner from "@/components/marketplace/RideCheckBanner";
import CustomerBidStack from "@/components/marketplace/CustomerBidStack";
import TipCard from "@/components/marketplace/TipCard";
import ReturnHandbackCard from "@/components/marketplace/ReturnHandbackCard";
import type { Payment, Rating, Task, TaskStatus, TrackingSnapshot } from "@/types";

const PAYMENT_STATUS_LABELS: Record<string, string> = {
  INITIATED: "Awaiting payment",
  AUTHORIZED: "Authorised — held in escrow",
  CAPTURED: "Captured — paid out",
  FAILED: "Payment failed",
  REFUNDED: "Refunded",
  CANCELLED: "Cancelled",
};

const DISPUTE_REASONS = [
  { value: "worker_no_show", label: "Worker did not show up" },
  { value: "work_not_done", label: "Work was not completed properly" },
  { value: "behaviour", label: "Unacceptable behaviour" },
  { value: "payment_issue", label: "Payment problem" },
  { value: "safety_concern", label: "Safety concern" },
  { value: "other", label: "Something else" },
];

const DISPUTABLE: TaskStatus[] = [
  "ACCEPTED",
  "WORKER_ON_THE_WAY",
  "ARRIVED_AT_LOCATION",
  "IN_PROGRESS",
  "COMPLETION_REQUESTED",
  "COMPLETED",
];

const START_HANDSHAKE_STATUSES: TaskStatus[] = ["ACCEPTED", "WORKER_ON_THE_WAY", "ARRIVED_AT_LOCATION"];

function bearingDeg(a: [number, number], b: [number, number]): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const [lat1, lng1] = a;
  const [lat2, lng2] = b;
  const y = Math.sin(toRad(lng2 - lng1)) * Math.cos(toRad(lat2));
  const x =
    Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) -
    Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(toRad(lng2 - lng1));
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function HandshakeCodeCard({
  title,
  description,
  code,
  locked,
}: {
  title: string;
  description: string;
  code: string;
  locked: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.info(`Code: ${code}`);
    }
  };

  return (
    <Card className="border-primary-200 bg-primary-50">
      <p className="flex items-center gap-2 text-sm font-semibold text-primary-900">
        <KeyRound className="h-4 w-4" aria-hidden /> {title}
      </p>
      <div className="mt-3 flex items-center justify-between gap-3 rounded-xl bg-white px-4 py-3">
        <span className="text-3xl font-bold tracking-[0.45em] text-slate-900" aria-label="Handshake code">
          {code}
        </span>
        <Button variant="secondary" onClick={() => void copy()}>
          {copied ? <Check className="mr-1.5 h-4 w-4" aria-hidden /> : <Copy className="mr-1.5 h-4 w-4" aria-hidden />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <p className="mt-2 text-sm text-primary-800">{description}</p>
      {locked && (
        <p className="mt-2 flex items-start gap-1.5 rounded-lg bg-red-100 px-3 py-2 text-xs font-medium text-red-800">
          <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          Too many wrong attempts — the handshake is locked for now. It unlocks automatically, and this same code can be
          retried once the lock window ends.
        </p>
      )}
    </Card>
  );
}

const SIM_STEP_MS = 1500;

export default function TaskDetails() {
  const { taskId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);

  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [disputeOpen, setDisputeOpen] = useState(false);
  const [disputeReason, setDisputeReason] = useState("worker_no_show");
  const [disputeText, setDisputeText] = useState("");
  const [ratingScore, setRatingScore] = useState(0);
  const [ratingComment, setRatingComment] = useState("");
  const [ratingPrefer, setRatingPrefer] = useState(false);
  const [ratingTip, setRatingTip] = useState(0);
  const [sharingLocation, setSharingLocation] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [startOtpOpen, setStartOtpOpen] = useState(false);
  const [completionOtpOpen, setCompletionOtpOpen] = useState(false);

  const isCustomer = user?.role === "CUSTOMER";
  const isWorker = user?.role === "WORKER";

  const taskQuery = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => tasksApi.get(taskId),
    enabled: !!taskId,
  });

  const ratingsQuery = useQuery({
    queryKey: ["task-ratings", taskId],
    queryFn: () => ratingsApi.forTask(taskId),
    enabled: !!taskId,
  });

  const paymentQuery = useQuery({
    queryKey: ["task-payment", taskId],
    queryFn: async () => {
      try {
        return await paymentsApi.forTask(taskId);
      } catch {
        return null as Payment | null;
      }
    },
    enabled: !!taskId,
  });

  useEffect(() => {
    const off = wsService.on(WS_EVENTS.TASK_STATUS, (frame) => {
      const data = frame.data as { task_id?: string };
      if (data.task_id !== taskId) return;
      void queryClient.invalidateQueries({ queryKey: ["task", taskId] });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    });
    return off;
  }, [taskId, queryClient]);

  const task: Task | undefined = taskQuery.data?.task;
  const history = task?.status_history ?? [];
  const ratings: Rating[] = ratingsQuery.data ?? [];
  const payment = paymentQuery.data ?? null;

  const isAssignedWorker = Boolean(task && isWorker && task.assigned_worker_id === user?.id);
  const trackingEnabled = Boolean(
    task && TRACKABLE_STATUSES.includes(task.status) && (isCustomer || isAssignedWorker)
  );
  const tracking = useTaskTracking(taskId, trackingEnabled);
  const workerTracker = useWorkerLocationTracker(taskId, sharingLocation || simulating);

  const simTimerRef = useRef<number | null>(null);
  const simIdxRef = useRef(0);
  const snapshotRef = useRef<TrackingSnapshot | null>(null);
  snapshotRef.current = tracking.snapshot;

  const stopSimulator = useCallback(() => {
    if (simTimerRef.current != null) {
      window.clearInterval(simTimerRef.current);
      simTimerRef.current = null;
    }
    setSimulating(false);
  }, []);

  const toggleSimulator = useCallback(() => {
    if (simTimerRef.current != null) {
      stopSimulator();
      return;
    }
    const coords = snapshotRef.current?.route?.coordinates ?? null;
    if (!coords || coords.length < 2) {
      toast.error("No route available yet — give matching a moment, then retry.");
      return;
    }
    simIdxRef.current = 0;
    setSimulating(true);
    simTimerRef.current = window.setInterval(() => {
      const routeCoords = snapshotRef.current?.route?.coordinates ?? null;
      if (!routeCoords || simIdxRef.current >= routeCoords.length - 1) {
        stopSimulator();
        toast.info("Simulator finished — the full route was covered.");
        return;
      }
      const [lat, lng] = routeCoords[simIdxRef.current];
      const [nextLat, nextLng] = routeCoords[simIdxRef.current + 1];
      workerTracker.emit(lat, lng, bearingDeg([lat, lng], [nextLat, nextLng]), 24);
      simIdxRef.current += 1;
    }, SIM_STEP_MS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stopSimulator]);

  useEffect(() => {
    if (trackingEnabled) return;
    setSharingLocation(false);
    stopSimulator();
  }, [trackingEnabled, stopSimulator]);

  useEffect(() => stopSimulator, [stopSimulator]);

  const myRating = useMemo(
    () => ratings.find((r) => r.rater_id === user?.id) ?? null,
    [ratings, user?.id]
  );

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["task", taskId] });
    void queryClient.invalidateQueries({ queryKey: ["task-ratings", taskId] });
    void queryClient.invalidateQueries({ queryKey: ["task-payment", taskId] });
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    void queryClient.invalidateQueries({ queryKey: ["wallet"] });
  };

  const confirmMutation = useMutation({
    mutationFn: () => tasksApi.confirm(taskId),
    onSuccess: (t) => {
      toast.success(`Task confirmed — searching for runners near ${t.area_name ?? t.city ?? "you"}.`);
      invalidate();
      checkoutMutation.mutate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const checkoutMutation = useMutation({
    mutationFn: async () => {
      const details = await paymentsApi.checkout(taskId);
      if (!details.required) {
        invalidate();
        return;
      }
      if (!details.key_id || !details.order_id) {
        throw new Error("Checkout details are incomplete. Please retry in a moment.");
      }
      await openRazorpayCheckout({
        key_id: details.key_id,
        order_id: details.order_id,
        amount: details.amount ?? 0,
        currency: details.currency ?? "INR",
        name: details.name,
        description: details.description,
        prefill: details.prefill,
        onSuccess: async (payload) => {
          try {
            await paymentsApi.verify(payload);
            toast.success("Payment secured — the amount is held until you confirm completion.");
            invalidate();
          } catch (e) {
            toast.error(errorMessage(e));
          }
        },
        onDismiss: () => toast.info("Payment not completed — you can pay from this page anytime."),
        onFailure: (message) => toast.error(message),
      });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const cancelMutation = useMutation({
    mutationFn: () => tasksApi.cancel(taskId, cancelReason.trim()),
    onSuccess: () => {
      toast.info("Task cancelled.");
      setCancelOpen(false);
      setCancelReason("");
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const retryMutation = useMutation({
    mutationFn: () => tasksApi.retryMatching(taskId),
    onSuccess: () => {
      toast.success("Matching retried — new offers have gone out to nearby runners.");
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const claimReservationMutation = useMutation({
    mutationFn: () => tasksApi.claimReservation(taskId),
    onSuccess: () => {
      toast.success("Slot reserved — confirm your readiness 45 minutes before the start time.");
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const readinessMutation = useMutation({
    mutationFn: () => tasksApi.confirmReadiness(taskId),
    onSuccess: () => {
      toast.success("Readiness confirmed. We'll remind you again 45 minutes before the slot.");
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const workerStatusMutation = useMutation({
    mutationFn: (next: TaskStatus) => tasksApi.workerStatus(taskId, next),
    onSuccess: (_t, next) => {
      if (next === "WORKER_ON_THE_WAY") {
        toast.success("Customer notified — head to the task location.");
      } else if (next === "ARRIVED_AT_LOCATION") {
        toast.success("Arrival confirmed — ask the customer for the 4-digit start code.");
      } else {
        toast.success(`Status updated to ${TASK_STATUS_LABELS[next]}.`);
      }
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const startOtpMutation = useMutation({
    mutationFn: (otp: string) => tasksApi.verifyStartOtp(taskId, otp),
    onSuccess: () => {
      toast.success("Start code verified — the task is now in progress.");
      setStartOtpOpen(false);
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const completionOtpMutation = useMutation({
    mutationFn: (otp: string) => tasksApi.complete(taskId, otp),
    onSuccess: () => {
      toast.success("Completion code verified — payment released to your wallet.");
      setCompletionOtpOpen(false);
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const ratingMutation = useMutation({
    mutationFn: () =>
      ratingsApi.submit({
        task_id: taskId,
        score: ratingScore,
        comment: ratingComment.trim() || undefined,
        prefer_worker: isCustomer && ratingScore === 5 ? ratingPrefer : undefined,
        tip_amount: isCustomer && ratingTip > 0 ? ratingTip : undefined,
      }),
    onSuccess: async (result) => {
      const checkout = result.payment;
      if (checkout?.required && checkout.key_id && checkout.order_id) {
        try {
          await openRazorpayCheckout({
            key_id: checkout.key_id,
            order_id: checkout.order_id,
            amount: checkout.amount ?? ratingTip * 100,
            currency: checkout.currency ?? task?.currency ?? "INR",
            name: checkout.name,
            description: checkout.description,
            prefill: checkout.prefill,
            onSuccess: async (payload) => {
              try {
                await paymentsApi.verify(payload);
                toast.success("Rating saved, and your tip reached the runner in full.");
                invalidate();
              } catch (error) {
                toast.error(errorMessage(error));
              }
            },
            onDismiss: () => toast.info("Rating saved. The tip payment was not completed — you can send it from the tip card."),
            onFailure: (message) => toast.error(message),
          });
        } catch (error) {
          toast.error(errorMessage(error));
        }
      } else if (ratingTip > 0) {
        toast.success("Rating saved — your tip went to the runner in full, with no commission.");
      } else {
        toast.success("Thanks — your rating has been recorded.");
      }
      if (isCustomer && ratingScore === 5 && ratingPrefer) {
        toast.success("Runner added to your preferred list for future tasks.");
      }
      setRatingScore(0);
      setRatingComment("");
      setRatingPrefer(false);
      setRatingTip(0);
      invalidate();
      void queryClient.invalidateQueries({ queryKey: ["my-affinities"] });
      void queryClient.invalidateQueries({ queryKey: ["worker-affinities"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const disputeMutation = useMutation({
    mutationFn: () => disputesApi.create({ task_id: taskId, reason: disputeReason, description: disputeText.trim() }),
    onSuccess: () => {
      toast.info("Dispute filed. Our admin team will review it shortly.");
      setDisputeOpen(false);
      setDisputeText("");
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const openChat = async () => {
    try {
      const conversation = await conversationsApi.open(taskId);
      const base = isWorker ? "/worker" : "/app";
      navigate(`${base}/messages?c=${conversation.id}`);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  if (taskQuery.isLoading) return <PageLoader label="Loading task…" />;
  if (taskQuery.isError || !task) {
    return (
      <EmptyState
        icon="🔍"
        title="Task not found"
        description={errorMessage(taskQuery.error) || "This task may have been removed or you don't have access to it."}
        action={
          <Link to={isWorker ? "/worker" : "/app/tasks"} className="btn-primary">
            Back to tasks
          </Link>
        }
      />
    );
  }

  const status = task.status;
  const customerConfirmed = Boolean(task.customer_confirmed_at);
  const isParticipant = isCustomer || isAssignedWorker;
  const canDispute = DISPUTABLE.includes(status) && isParticipant;
  const etaMin = tracking.update?.eta_minutes ?? tracking.snapshot?.eta_minutes ?? null;
  const remainingKm = tracking.update?.remaining_km ?? tracking.snapshot?.remaining_km ?? null;
  const showSos = isParticipant && (SOS_STATUSES.includes(status) || status === "EMERGENCY_ALERT");
  const showStartCode =
    isCustomer && START_HANDSHAKE_STATUSES.includes(status) && Boolean(task.start_otp_display);
  const showCompletionCode =
    isCustomer && status === "COMPLETION_REQUESTED" && Boolean(task.completion_otp_display);
  const showBidStack = isCustomer && (status === "SEARCHING_WORKER" || status === "OFFERED");
  const showRideCheck =
    isParticipant && (status === "WORKER_ON_THE_WAY" || status === "IN_PROGRESS" || status === "EMERGENCY_ALERT");
  const showTip = isCustomer && Boolean(task.assigned_worker_id) && !["CANCELLED", "EMERGENCY_ALERT", "DRAFT", "PENDING_CONFIRMATION", "CONFIRMED", "SEARCHING_WORKER", "OFFERED"].includes(status);
  const showReturnHandback = Boolean(task.is_round_trip) && isParticipant && status !== "CANCELLED";
  const scheduledFor = task.scheduled_for ? formatDateTime(task.scheduled_for) : null;
  const canClaimReservation = isWorker && status === "SCHEDULED_OPEN";
  const awaitingReadiness =
    isAssignedWorker && status === "SCHEDULED_ASSIGNED" && Boolean(task.is_scheduled) && !task.worker_confirmed_readiness;

  const workerNextStep = isAssignedWorker ? status : null;

  return (
    <div className="space-y-5">
      {/* Header */}
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-2xl">
              {TASK_TYPE_ICONS[task.task_type] ?? "🧭"}
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-lg font-bold text-slate-900">{task.title}</h1>
                <StatusBadge status={status} />
                {task.is_round_trip && (
                  <Badge className="bg-teal-100 text-teal-800">
                    <RotateCcw className="h-3 w-3" aria-hidden /> Round trip
                  </Badge>
                )}
                {task.is_scheduled && (
                  <Badge className="bg-amber-100 text-amber-800">
                    <Clock className="h-3 w-3" aria-hidden /> Scheduled
                  </Badge>
                )}
              </div>
              <p className="mt-1 text-sm text-slate-500">
                {TASK_TYPE_LABELS[task.task_type] ?? task.task_type} · {URGENCY_LABELS[task.urgency]} priority · created {timeAgo(task.created_at)}
              </p>
            </div>
          </div>
          <div className="text-right">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Budget</p>
            <p className="text-2xl font-bold text-slate-900">{formatMoney(task.budget, task.currency)}</p>
            {status === "COMPLETED" && customerConfirmed && (
              <p className="mt-0.5 text-xs font-medium text-emerald-600">Paid · runner received {formatMoney(task.worker_payout_amount)}</p>
            )}
          </div>
        </div>

        {task.parsed_by_ai && (
          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg bg-indigo-50 px-3 py-2 text-xs text-indigo-800">
            <span aria-hidden>🤖</span>
            <span>
              This request was interpreted by TaskFlex AI
              {task.ai_confidence > 0 && <> with {Math.round(task.ai_confidence * 100)}% confidence</>}.
            </span>
          </div>
        )}
      </Card>

      {showRideCheck && (
        <RideCheckBanner taskId={task.id} role={isWorker ? "WORKER" : "CUSTOMER"} enabled={showRideCheck} />
      )}

      {/* Scheduled / reserved slot */}
      {task.is_scheduled && ["SCHEDULED_OPEN", "SCHEDULED_ASSIGNED"].includes(status) && (
        <Card className="border-amber-200 bg-amber-50">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="flex items-center gap-2 text-sm font-semibold text-amber-900">
                <Clock className="h-4 w-4" aria-hidden /> Scheduled slot
              </p>
              <p className="mt-1 text-sm text-amber-800">
                {scheduledFor ? `Starts ${scheduledFor}` : "Start time to be confirmed"} · the worker must confirm readiness
                45 minutes ahead, otherwise the slot is released for live dispatch.
              </p>
              {status === "SCHEDULED_OPEN" && (
                <p className="mt-1 text-sm text-amber-800">
                  {isCustomer
                    ? "This slot is open on the scheduled board — verified runners can reserve it."
                    : "No runner has reserved this slot yet."}
                </p>
              )}
              {status === "SCHEDULED_ASSIGNED" && (
                <p className="mt-1 text-sm text-amber-800">
                  {task.worker_confirmed_readiness
                    ? "Your runner confirmed they'll be ready for this slot."
                    : "Your runner has reserved the slot but hasn't confirmed readiness yet."}
                </p>
              )}
            </div>
            {canClaimReservation && (
              <Button loading={claimReservationMutation.isPending} onClick={() => claimReservationMutation.mutate()}>
                <Check className="mr-1.5 h-4 w-4" aria-hidden /> Reserve this slot
              </Button>
            )}
            {awaitingReadiness && (
              <Button loading={readinessMutation.isPending} onClick={() => readinessMutation.mutate()}>
                <CheckCircle2 className="mr-1.5 h-4 w-4" aria-hidden /> Confirm readiness
              </Button>
            )}
            {isAssignedWorker && status === "SCHEDULED_ASSIGNED" && task.worker_confirmed_readiness && (
              <Badge className="bg-emerald-100 text-emerald-800">
                <CheckCircle2 className="h-3 w-3" aria-hidden /> Ready
              </Badge>
            )}
          </div>
        </Card>
      )}

      {/* Back-to-back chaining */}
      {status === "QUEUED_NEXT" && (
        <Card className="border-blue-200 bg-blue-50">
          <p className="flex items-center gap-2 text-sm font-semibold text-blue-900">
            <Sparkles className="h-4 w-4" aria-hidden /> Queued back-to-back job
          </p>
          <p className="mt-1 text-sm text-blue-800">
            {isAssignedWorker
              ? "You accepted this job while wrapping up your current task. It starts automatically the moment you complete that one, with a fresh route to this pickup."
              : "Your runner accepted this job while finishing another errand nearby. It begins automatically and you'll see live tracking as soon as they're on the way."}
          </p>
        </Card>
      )}

      {/* Customer: pending confirmation gate */}
      {isCustomer && status === "PENDING_CONFIRMATION" && (
        <Card className="border-amber-200 bg-amber-50">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="flex items-center gap-2 text-sm font-semibold text-amber-900">
                <AlertTriangle className="h-4 w-4" aria-hidden /> Awaiting your confirmation
              </p>
              <p className="mt-1 text-sm text-amber-800">
                No runner can see this errand yet. Confirm to authorise dispatch and secure the {formatMoney(task.budget)} payment.
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button variant="secondary" onClick={() => setCancelOpen(true)}>
                Discard
              </Button>
              <Button loading={confirmMutation.isPending} onClick={() => confirmMutation.mutate()}>
                <CheckCircle2 className="mr-1.5 h-4 w-4" aria-hidden /> Confirm & find runners
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Customer: retry matching */}
      {isCustomer && (status === "SEARCHING_WORKER" || status === "CONFIRMED") && (
        <Card className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-800">Looking for runners…</p>
            <p className="mt-0.5 text-sm text-slate-500">
              We're contacting the best-matched runners in your area. This usually takes a few minutes.
            </p>
          </div>
          {status === "SEARCHING_WORKER" && (
            <Button variant="secondary" loading={retryMutation.isPending} onClick={() => retryMutation.mutate()}>
              <RotateCcw className="mr-1.5 h-4 w-4" aria-hidden /> Retry matching
            </Button>
          )}
        </Card>
      )}

      <CustomerBidStack task={task} enabled={showBidStack} />

      <div className="grid gap-5 lg:grid-cols-5">
        {/* Left: details */}
        <div className="space-y-5 lg:col-span-3">
          {/* Live tracking */}
          {trackingEnabled && tracking.snapshot && (
            <Card>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Live tracking</h2>
                <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" aria-hidden />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" aria-hidden />
                  </span>
                  Live
                </span>
              </div>
              <LiveTrackingMap
                className="mt-3"
                destination={tracking.snapshot.destination}
                route={tracking.snapshot.route?.coordinates ?? null}
                update={tracking.update}
              />
              <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
                <div>
                  <p className="text-xs text-slate-400">Runner</p>
                  <p className="font-medium text-slate-800">{tracking.snapshot.worker.full_name ?? "—"}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">ETA</p>
                  <p className="font-medium text-slate-800">{etaMin != null ? `${Math.round(etaMin)} min` : "—"}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">Remaining</p>
                  <p className="font-medium text-slate-800">{remainingKm != null ? `${remainingKm.toFixed(1)} km` : "—"}</p>
                </div>
              </div>
              {workerTracker.error && <p className="mt-2 text-xs text-red-600">{workerTracker.error}</p>}
              {isAssignedWorker && (
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button variant={sharingLocation ? "danger" : "secondary"} onClick={() => setSharingLocation((v) => !v)}>
                    <Navigation className="mr-1.5 h-4 w-4" aria-hidden />
                    {sharingLocation ? "Stop sharing location" : "Share live location"}
                  </Button>
                  {import.meta.env.DEV && (
                    <Button variant="secondary" onClick={toggleSimulator}>
                      {simulating ? "Stop route simulator" : "Simulate route (dev)"}
                    </Button>
                  )}
                </div>
              )}
            </Card>
          )}

          <Card>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">What needs doing</h2>
            <p className="mt-3 whitespace-pre-line text-sm leading-relaxed text-slate-700">{task.description}</p>
            {task.special_requirements && (
              <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
                <span className="font-medium text-slate-700">Special requirements: </span>
                {task.special_requirements}
              </div>
            )}
            {task.requirements.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-1.5">
                {task.requirements.map((req) => (
                  <Badge key={req.skill_name} className={req.is_required ? "bg-primary-50 text-primary-700" : "bg-slate-100 text-slate-600"}>
                    {req.is_required ? "★" : "○"} {req.skill_name}
                  </Badge>
                ))}
              </div>
            )}
          </Card>

          {/* Proof of execution */}
          {isParticipant && (
            <ProofOfExecutionCard task={task} isWorker={isAssignedWorker} isCustomer={isCustomer} />
          )}

          {/* Incidental expenses */}
          {isParticipant && (
            <ExpenseLedgerCard task={task} isWorker={isAssignedWorker} isCustomer={isCustomer} />
          )}

          {/* Round-trip return handback */}
          {showReturnHandback && (
            <ReturnHandbackCard task={task} isWorker={isAssignedWorker} isCustomer={isCustomer} />
          )}

          {/* Tips (100% to the runner) */}
          {showTip && <TipCard task={task} />}

          <Card>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Schedule & location</h2>
            <dl className="mt-3 grid gap-4 sm:grid-cols-2">
              <div className="flex items-start gap-2.5">
                <Clock className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden />
                <div>
                  <dt className="text-xs text-slate-400">Scheduled</dt>
                  <dd className="text-sm font-medium text-slate-800">
                    {task.scheduled_date
                      ? `${task.scheduled_date}${task.scheduled_time ? ` at ${task.scheduled_time}` : ""}`
                      : "Flexible"}
                  </dd>
                  <dd className="text-xs text-slate-400">~{task.estimated_duration_minutes} min estimated</dd>
                </div>
              </div>
              <div className="flex items-start gap-2.5">
                <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden />
                <div>
                  <dt className="text-xs text-slate-400">Location</dt>
                  <dd className="text-sm font-medium text-slate-800">{task.address_text ?? task.area_name ?? "—"}</dd>
                  <dd className="text-xs text-slate-400">{[task.area_name, task.city].filter(Boolean).join(", ")}</dd>
                </div>
              </div>
              <div className="flex items-start gap-2.5">
                <RotateCcw className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden />
                <div>
                  <dt className="text-xs text-slate-400">Trip type</dt>
                  <dd className="text-sm font-medium text-slate-800">
                    {task.is_round_trip ? "Round trip — return handback required" : "One way"}
                  </dd>
                  {task.is_round_trip && (
                    <dd className="text-xs text-slate-400">
                      Return leg billed at 0.5× the per-km rate · handback code releases payout
                    </dd>
                  )}
                </div>
              </div>
              <div className="flex items-start gap-2.5">
                <IndianRupee className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden />
                <div>
                  <dt className="text-xs text-slate-400">Payment</dt>
                  <dd className="text-sm font-medium text-slate-800">
                    {payment
                      ? `${formatMoney(payment.amount, payment.currency)} · ${PAYMENT_STATUS_LABELS[payment.status] ?? payment.status}`
                      : task.payment_status
                        ? PAYMENT_STATUS_LABELS[task.payment_status] ?? task.payment_status
                        : "No payment recorded yet"}
                  </dd>
                  {payment && (
                    <dd className="text-xs text-slate-400">
                      Platform fee {formatMoney(payment.commission_amount, payment.currency)} · runner payout {formatMoney(payment.worker_payout_amount, payment.currency)}
                    </dd>
                  )}
                </div>
              </div>
            </dl>
          </Card>

          {/* People */}
          <Card>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">People</h2>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <div className="flex items-center gap-3">
                <Avatar name={task.customer?.full_name} url={task.customer?.avatar_url} />
                <div className="min-w-0">
                  <p className="text-xs text-slate-400">Customer</p>
                  <p className="truncate text-sm font-semibold text-slate-800">{task.customer?.full_name ?? "—"}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                {task.worker ? (
                  <>
                    <Avatar name={task.worker.full_name} url={task.worker.avatar_url} />
                    <div className="min-w-0">
                      <p className="text-xs text-slate-400">Runner</p>
                      <p className="truncate text-sm font-semibold text-slate-800">{task.worker.full_name}</p>
                      {typeof task.worker.rating_average === "number" && (
                        <p className="flex items-center gap-1 text-xs text-amber-600">
                          <Star className="h-3 w-3 fill-amber-400 text-amber-400" aria-hidden />
                          {task.worker.rating_average.toFixed(1)} ({task.worker.rating_count})
                        </p>
                      )}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-400">
                      <UserIcon className="h-5 w-5" aria-hidden />
                    </div>
                    <div>
                      <p className="text-xs text-slate-400">Runner</p>
                      <p className="text-sm font-medium text-slate-500">Not assigned yet</p>
                    </div>
                  </>
                )}
              </div>
            </div>
            {task.assigned_worker_id && isParticipant && status !== "CANCELLED" && (
              <Button variant="secondary" className="mt-4 w-full sm:w-auto" onClick={openChat}>
                <MessageCircle className="mr-1.5 h-4 w-4" aria-hidden /> Open chat
              </Button>
            )}
          </Card>

          {/* Rating (post-completion) */}
          {status === "COMPLETED" && customerConfirmed && task.assigned_worker_id && (
            <Card>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Rating</h2>
              {myRating ? (
                <div className="mt-3">
                  <div className="flex items-center gap-1">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <Star key={i} className={cn("h-5 w-5", i < myRating.score ? "fill-amber-400 text-amber-400" : "text-slate-300")} aria-hidden />
                    ))}
                  </div>
                  {myRating.comment && <p className="mt-2 text-sm text-slate-600">“{myRating.comment}”</p>}
                  <p className="mt-1 text-xs text-slate-400">You rated this task {timeAgo(myRating.created_at)}.</p>
                </div>
              ) : isParticipant ? (
                <div className="mt-3">
                  <p className="text-sm text-slate-600">How did it go? Your rating helps keep TaskFlex trustworthy.</p>
                  <div className="mt-3 flex gap-1.5">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <button
                        key={n}
                        type="button"
                        onClick={() => setRatingScore(n)}
                        aria-label={`${n} star${n > 1 ? "s" : ""}`}
                        className="rounded-lg p-1 transition hover:scale-110"
                      >
                        <Star className={cn("h-8 w-8", n <= ratingScore ? "fill-amber-400 text-amber-400" : "text-slate-300")} aria-hidden />
                      </button>
                    ))}
                  </div>
                  <Textarea
                    className="mt-3"
                    rows={3}
                    placeholder="Optional comment — what stood out?"
                    value={ratingComment}
                    maxLength={1000}
                    onChange={(e) => setRatingComment(e.target.value)}
                  />

                  {isCustomer && ratingScore === 5 && (
                    <button
                      type="button"
                      aria-pressed={ratingPrefer}
                      onClick={() => setRatingPrefer((value) => !value)}
                      className={cn(
                        "mt-3 flex w-full items-start gap-2.5 rounded-xl border p-3 text-left transition",
                        ratingPrefer
                          ? "border-amber-400 bg-amber-50"
                          : "border-slate-200 bg-white hover:border-amber-300"
                      )}
                    >
                      <span
                        className={cn(
                          "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border",
                          ratingPrefer ? "border-amber-500 bg-amber-500 text-white" : "border-slate-300 bg-white text-transparent"
                        )}
                        aria-hidden
                      >
                        <Check className="h-3.5 w-3.5" />
                      </span>
                      <span>
                        <span className="block text-sm font-semibold text-slate-800">
                          ⭐ Add to my preferred runners
                        </span>
                        <span className="block text-xs text-slate-500">
                          Preferred runners get priority matching and a repeat-customer badge on future jobs for you.
                        </span>
                      </span>
                    </button>
                  )}

                  {isCustomer && (
                    <div className="mt-3">
                      <p className="text-sm font-medium text-slate-700">Add a tip</p>
                      <p className="text-xs text-slate-500">
                        100% goes to your runner — TaskFlex takes no commission on tips.
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {[0, 20, 50, 100].map((preset) => (
                          <button
                            key={preset}
                            type="button"
                            onClick={() => setRatingTip(preset)}
                            className={cn(
                              "rounded-full border px-3.5 py-1.5 text-sm font-semibold transition",
                              ratingTip === preset
                                ? "border-rose-400 bg-rose-50 text-rose-700"
                                : "border-slate-200 bg-white text-slate-600 hover:border-rose-300"
                            )}
                          >
                            {preset === 0 ? "No tip" : `+₹${preset}`}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  <Button
                    className="mt-3"
                    disabled={ratingScore === 0}
                    loading={ratingMutation.isPending}
                    onClick={() => ratingMutation.mutate()}
                  >
                    Submit rating{ratingTip > 0 ? ` & ₹${ratingTip} tip` : ""}
                  </Button>
                </div>
              ) : null}
            </Card>
          )}
        </div>

        {/* Right: timeline + actions */}
        <div className="space-y-5 lg:col-span-2">
          {/* Customer: outstanding payment */}
          {isCustomer && payment && ["INITIATED", "FAILED"].includes(payment.status) && status !== "CANCELLED" && (
            <Card className="border-amber-200 bg-amber-50">
              <p className="flex items-center gap-2 text-sm font-semibold text-amber-900">
                <AlertTriangle className="h-4 w-4" aria-hidden /> Payment pending
              </p>
              <p className="mt-1 text-sm text-amber-800">
                The {formatMoney(payment.amount, payment.currency)} budget isn't secured yet. Complete the payment so your runner gets paid reliably.
              </p>
              <Button className="mt-3 w-full" loading={checkoutMutation.isPending} onClick={() => checkoutMutation.mutate()}>
                <IndianRupee className="mr-1.5 h-4 w-4" aria-hidden /> Pay {formatMoney(payment.amount, payment.currency)}
              </Button>
            </Card>
          )}

          {/* Customer: start handshake code */}
          {showStartCode && (
            <HandshakeCodeCard
              title="Start handshake code"
              description={
                status === "ARRIVED_AT_LOCATION"
                  ? "Your runner has arrived. Read this code to them — entering it starts the task and begins their tracked work."
                  : "Keep this code private until your runner arrives. They enter it at the location to start the task."
              }
              code={task.start_otp_display ?? ""}
              locked={Boolean(task.start_otp_locked)}
            />
          )}

          {/* Customer: completion handshake code */}
          {showCompletionCode && (
            <HandshakeCodeCard
              title="Completion handshake code"
              description="Review the proof photos and decide any incidental expenses first. When you're satisfied, read this code to your runner — verifying it releases the payment."
              code={task.completion_otp_display ?? ""}
              locked={Boolean(task.completion_otp_locked)}
            />
          )}

          {/* Worker next step */}
          {isAssignedWorker && workerNextStep && (
            <>
              {workerNextStep === "ACCEPTED" && (
                <Card className="border-primary-200 bg-primary-50">
                  <p className="text-sm font-semibold text-primary-900">Your next step</p>
                  <p className="mt-1 text-sm text-primary-800">
                    Head to the task location and share live location so the customer can follow your progress.
                  </p>
                  <Button
                    className="mt-3 w-full"
                    loading={workerStatusMutation.isPending}
                    onClick={() => workerStatusMutation.mutate("WORKER_ON_THE_WAY")}
                  >
                    I'm on my way
                  </Button>
                </Card>
              )}

              {workerNextStep === "WORKER_ON_THE_WAY" && (
                <Card className="border-primary-200 bg-primary-50">
                  <p className="text-sm font-semibold text-primary-900">Your next step</p>
                  <p className="mt-1 text-sm text-primary-800">
                    At the location? Confirm your arrival. You'll then enter the customer's 4-digit start code.
                  </p>
                  <Button
                    className="mt-3 w-full"
                    loading={workerStatusMutation.isPending}
                    onClick={() => workerStatusMutation.mutate("ARRIVED_AT_LOCATION")}
                  >
                    I've arrived
                  </Button>
                </Card>
              )}

              {workerNextStep === "ARRIVED_AT_LOCATION" && (
                <Card className="border-primary-200 bg-primary-50">
                  <p className="flex items-center gap-2 text-sm font-semibold text-primary-900">
                    <KeyRound className="h-4 w-4" aria-hidden /> Start the task
                  </p>
                  <p className="mt-1 text-sm text-primary-800">
                    Ask the customer to read out the 4-digit start code. Entering it moves the task to in progress.
                  </p>
                  <Button
                    className="mt-3 w-full"
                    onClick={() => {
                      startOtpMutation.reset();
                      setStartOtpOpen(true);
                    }}
                  >
                    Enter start code
                  </Button>
                </Card>
              )}

              {workerNextStep === "IN_PROGRESS" && (
                <Card className="border-primary-200 bg-primary-50">
                  <p className="text-sm font-semibold text-primary-900">Your next step</p>
                  <p className="mt-1 text-sm text-primary-800">
                    When the work is done, upload at least one location-tagged proof photo above, then request completion.
                    The customer will give you a 4-digit completion code.
                  </p>
                </Card>
              )}

              {workerNextStep === "COMPLETION_REQUESTED" && (
                <Card className="border-violet-200 bg-violet-50">
                  <p className="flex items-center gap-2 text-sm font-semibold text-violet-900">
                    <KeyRound className="h-4 w-4" aria-hidden /> Finish & get paid
                  </p>
                  <p className="mt-1 text-sm text-violet-800">
                    Ask the customer to review your proof photos and read out the 4-digit completion code. Verifying it
                    completes the task and releases the payment to your wallet.
                  </p>
                  <Button
                    className="mt-3 w-full"
                    onClick={() => {
                      completionOtpMutation.reset();
                      setCompletionOtpOpen(true);
                    }}
                  >
                    Enter completion code
                  </Button>
                </Card>
              )}
            </>
          )}

          {/* Customer: share live tracking */}
          {isCustomer && <ShareTrackingCard task={task} />}

          {/* Safety */}
          {showSos && <SosButton taskId={task.id} status={status} />}

          {/* Danger zone */}
          {isParticipant && status !== "CANCELLED" && !customerConfirmed && (
            <Card>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Having trouble?</h2>
              <p className="mt-1 text-sm text-slate-500">
                Raise a dispute and our team will step in, or cancel the task if it's no longer needed.
              </p>
              <div className="mt-3 flex flex-col gap-2">
                {canDispute && (
                  <Button variant="secondary" onClick={() => setDisputeOpen(true)}>
                    <AlertTriangle className="mr-1.5 h-4 w-4 text-orange-500" aria-hidden /> Report a problem
                  </Button>
                )}
                {isCustomer && !["COMPLETED", "CANCELLED", "DISPUTED", "EMERGENCY_ALERT"].includes(status) && (
                  <Button variant="danger" onClick={() => setCancelOpen(true)}>
                    <Ban className="mr-1.5 h-4 w-4" aria-hidden /> Cancel task
                  </Button>
                )}
              </div>
              {task.cancellation_reason && (
                <p className="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-700">
                  <span className="font-semibold">Cancellation reason: </span>
                  {task.cancellation_reason}
                </p>
              )}
            </Card>
          )}

          {/* Timeline */}
          <Card>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Activity</h2>
            {history.length === 0 ? (
              <p className="mt-3 text-sm text-slate-500">No activity recorded yet.</p>
            ) : (
              <ol className="mt-4 space-y-0">
                {[...history].reverse().map((entry, idx, arr) => (
                  <li key={`${entry.to_status}-${entry.created_at ?? idx}`} className="relative flex gap-3 pb-5 last:pb-0">
                    {idx < arr.length - 1 && <span className="absolute left-[7px] top-4 h-full w-px bg-slate-200" aria-hidden />}
                    <span
                      className={cn(
                        "relative mt-1 h-[15px] w-[15px] shrink-0 rounded-full border-2",
                        idx === arr.length - 1 ? "border-primary-600 bg-primary-600" : "border-slate-300 bg-white"
                      )}
                      aria-hidden
                    />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-800">
                        {entry.from_status ? `${TASK_STATUS_LABELS[entry.from_status as TaskStatus] ?? entry.from_status} → ` : ""}
                        {TASK_STATUS_LABELS[entry.to_status as TaskStatus] ?? entry.to_status}
                      </p>
                      {entry.note && <p className="mt-0.5 text-xs text-slate-500">{entry.note}</p>}
                      <p className="mt-0.5 text-xs text-slate-400">
                        {entry.changed_by_role ? `${entry.changed_by_role.toLowerCase()} · ` : ""}
                        {formatDateTime(entry.created_at)}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>
      </div>

      {/* Start OTP modal */}
      <OtpEntryModal
        open={startOtpOpen}
        title="Enter start code"
        description="Ask the customer for the 4-digit start code shown on their TaskFlex screen. Repeated wrong attempts will temporarily lock the handshake."
        confirmLabel="Verify & start"
        loading={startOtpMutation.isPending}
        error={startOtpMutation.error ? errorMessage(startOtpMutation.error) : null}
        onClose={() => setStartOtpOpen(false)}
        onSubmit={(otp) => startOtpMutation.mutate(otp)}
      />

      {/* Completion OTP modal */}
      <OtpEntryModal
        open={completionOtpOpen}
        title="Enter completion code"
        description="The customer reads this 4-digit code out after reviewing your proof photos. Verifying it completes the task and releases the payment."
        confirmLabel="Verify & complete"
        loading={completionOtpMutation.isPending}
        error={completionOtpMutation.error ? errorMessage(completionOtpMutation.error) : null}
        onClose={() => setCompletionOtpOpen(false)}
        onSubmit={(otp) => completionOtpMutation.mutate(otp)}
      />

      {/* Cancel modal */}
      <Modal open={cancelOpen} onClose={() => setCancelOpen(false)} title="Cancel this task?">
        <p className="text-sm text-slate-600">
          The assigned runner (if any) will be notified. Cancel policies may affect your reliability score.
        </p>
        <div className="mt-4">
          <Field label="Reason for cancelling" htmlFor="cancel-reason">
            <Textarea
              id="cancel-reason"
              rows={3}
              placeholder="e.g. Plans changed, no longer needed."
              value={cancelReason}
              error={cancelReason.trim().length > 0 && cancelReason.trim().length < 3 ? "Reason must be at least 3 characters." : undefined}
              onChange={(e) => setCancelReason(e.target.value)}
            />
          </Field>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setCancelOpen(false)}>
            Keep task
          </Button>
          <Button
            variant="danger"
            loading={cancelMutation.isPending}
            disabled={cancelReason.trim().length < 3}
            onClick={() => cancelMutation.mutate()}
          >
            Cancel task
          </Button>
        </div>
      </Modal>

      {/* Dispute modal */}
      <Modal open={disputeOpen} onClose={() => setDisputeOpen(false)} title="Report a problem">
        <div className="space-y-4">
          <Field label="What went wrong?" htmlFor="dispute-reason">
            <select
              id="dispute-reason"
              className="input appearance-none pr-8"
              value={disputeReason}
              onChange={(e) => setDisputeReason(e.target.value)}
            >
              {DISPUTE_REASONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Describe what happened" htmlFor="dispute-text" hint="Minimum 10 characters. Our admin team reviews every dispute.">
            <Textarea
              id="dispute-text"
              rows={4}
              placeholder="Tell us exactly what happened, in your own words…"
              value={disputeText}
              onChange={(e) => setDisputeText(e.target.value)}
            />
          </Field>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setDisputeOpen(false)}>
            Close
          </Button>
          <Button
            loading={disputeMutation.isPending}
            disabled={disputeText.trim().length < 10}
            onClick={() => disputeMutation.mutate()}
          >
            <RefreshCw className="mr-1.5 h-4 w-4" aria-hidden /> Submit dispute
          </Button>
        </div>
      </Modal>
    </div>
  );
}
