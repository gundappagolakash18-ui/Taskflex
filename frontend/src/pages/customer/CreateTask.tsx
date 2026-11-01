import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlertTriangle, CheckCircle2, IndianRupee, MapPin, RotateCcw, Sparkles, Wand2 } from "lucide-react";
import { tasksApi } from "@/api/tasks";
import { locationApi } from "@/api/location";
import type { GeocodeResult } from "@/api/location";
import type { ParsedTaskDraft, Task } from "@/types";
import { TASK_TYPE_ICONS, TASK_TYPE_LABELS, URGENCY_LABELS } from "@/lib/constants";
import { Button, Card, Field, Input, Select, Textarea } from "@/components/ui";
import { cn, errorMessage, formatMoney, scorePercent } from "@/lib/utils";
import { toast } from "@/stores/toast";

const EXAMPLES = [
  "I need someone to register my mother at KLE hospital tomorrow at 9am and hold her place in the queue. Budget 400 rupees.",
  "Please pick up my parcel from the Bluedart hub near Khanapur road and deliver it home today evening. 200 rupees.",
  "Submit my property tax documents at the Belagavi corporation office on Monday morning. Budget 300.",
  "Buy the grocery list I'll share from More supermarket and deliver to my flat. Around 250 rupees, today 6pm.",
];

type Step = "describe" | "review" | "saved" | "dispatched";

interface EditableDraft {
  title: string;
  description: string;
  task_type: string;
  urgency: string;
  budget: string;
  scheduled_date: string;
  scheduled_time: string;
  estimated_duration_minutes: number;
  address_text: string;
  area_name: string;
  city: string;
  latitude: number | null;
  longitude: number | null;
  required_skills: string[];
  is_round_trip: boolean;
  pickup_address: string;
  pickup_latitude: number | null;
  pickup_longitude: number | null;
}

function toEditable(draft: ParsedTaskDraft): EditableDraft {
  return {
    title: draft.title || "My errand",
    description: draft.description || "",
    task_type: draft.task_type,
    urgency: draft.urgency,
    budget: draft.budget ? String(draft.budget) : "",
    scheduled_date: draft.scheduled_date ?? "",
    scheduled_time: draft.scheduled_time ? draft.scheduled_time.slice(0, 5) : "",
    estimated_duration_minutes: draft.estimated_duration_minutes,
    address_text: draft.location ?? "",
    area_name: "",
    city: "",
    latitude: draft.latitude,
    longitude: draft.longitude,
    required_skills: draft.required_skills,
    is_round_trip: false,
    pickup_address: "",
    pickup_latitude: null,
    pickup_longitude: null,
  };
}

const PARSING_STAGES = [
  "Reading your request…",
  "Identifying the errand type…",
  "Extracting time, place and budget…",
  "Checking what's missing…",
];

export default function CreateTask() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("describe");
  const [text, setText] = useState("");
  const [stage, setStage] = useState(0);
  const [draft, setDraft] = useState<ParsedTaskDraft | null>(null);
  const [editable, setEditable] = useState<EditableDraft | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [geocoding, setGeocoding] = useState(false);
  const [geocodingPickup, setGeocodingPickup] = useState(false);
  const [created, setCreated] = useState<Task | null>(null);
  const [budgetPreview, setBudgetPreview] = useState("");
  const stageTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setBudgetPreview(editable?.budget ?? ""), 500);
    return () => window.clearTimeout(timer);
  }, [editable?.budget]);

  const fareQuery = useQuery({
    queryKey: [
      "fare-estimate",
      editable?.latitude,
      editable?.longitude,
      editable?.pickup_latitude,
      editable?.pickup_longitude,
      editable?.is_round_trip,
      editable?.urgency,
      budgetPreview,
    ],
    queryFn: () =>
      tasksApi.estimateFare({
        origin_latitude: editable?.is_round_trip
          ? editable?.pickup_latitude ?? null
          : editable?.latitude ?? null,
        origin_longitude: editable?.is_round_trip
          ? editable?.pickup_longitude ?? null
          : editable?.longitude ?? null,
        destination_latitude: editable?.is_round_trip ? editable?.latitude ?? null : null,
        destination_longitude: editable?.is_round_trip ? editable?.longitude ?? null : null,
        is_round_trip: editable?.is_round_trip ?? false,
        wait_minutes: 0,
        urgency: editable?.urgency ?? "normal",
        proposed_budget: Number(budgetPreview) > 0 ? Number(budgetPreview) : null,
      }),
    enabled: step === "review" && editable !== null,
    staleTime: 30_000,
    retry: false,
  });

  const parseMutation = useMutation({
    mutationFn: (input: string) => tasksApi.parse(input),
    onMutate: () => {
      setStage(0);
      stageTimer.current = setInterval(() => setStage((s) => Math.min(s + 1, PARSING_STAGES.length - 1)), 550);
    },
    onSuccess: (parsed) => {
      if (stageTimer.current) clearInterval(stageTimer.current);
      setDraft(parsed);
      setEditable(toEditable(parsed));
      setStep("review");
    },
    onError: (error) => {
      if (stageTimer.current) clearInterval(stageTimer.current);
      toast.error(errorMessage(error));
    },
  });

  const createMutation = useMutation({
    mutationFn: (payload: Parameters<typeof tasksApi.create>[0]) => tasksApi.create(payload),
    onSuccess: (task) => {
      setCreated(task);
      setStep("saved");
      toast.success("Task saved — it will only search for workers after you confirm it.");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const confirmMutation = useMutation({
    mutationFn: (taskId: string) => tasksApi.confirm(taskId),
    onSuccess: (task) => {
      setCreated(task);
      setStep("dispatched");
      toast.success("Confirmed! We're notifying the best-matched runners near you.");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  async function geocode() {
    if (!editable?.address_text || editable.address_text.trim().length < 3) {
      toast.error("Type an address or place first.");
      return;
    }
    setGeocoding(true);
    try {
      const result: GeocodeResult | null = await locationApi.geocode(editable.address_text);
      if (result) {
        setEditable((prev) =>
          prev
            ? {
                ...prev,
                latitude: result.latitude,
                longitude: result.longitude,
                address_text: result.display_name,
              }
            : prev
        );
        toast.success("Location pinned.");
      } else {
        toast.info("Couldn't find that place — the address text will still be shared with runners.");
      }
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setGeocoding(false);
    }
  }

  async function geocodePickup() {
    if (!editable?.pickup_address || editable.pickup_address.trim().length < 3) {
      toast.error("Type the pickup point first.");
      return;
    }
    setGeocodingPickup(true);
    try {
      const result: GeocodeResult | null = await locationApi.geocode(editable.pickup_address);
      if (result) {
        setEditable((prev) =>
          prev
            ? {
                ...prev,
                pickup_latitude: result.latitude,
                pickup_longitude: result.longitude,
                pickup_address: result.display_name,
              }
            : prev
        );
        toast.success("Pickup point pinned.");
      } else {
        toast.info("Couldn't find that pickup point — try a more specific address.");
      }
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setGeocodingPickup(false);
    }
  }

  function submitDraft() {
    if (!draft || !editable) return;
    setFormError(null);
    const budget = parseFloat(editable.budget);
    if (!budget || budget <= 0) {
      setFormError("Please set a budget greater than zero.");
      return;
    }
    if (editable.title.trim().length < 4) {
      setFormError("Give the task a clear title.");
      return;
    }
    if (editable.description.trim().length < 10) {
      setFormError("Add a short description (at least 10 characters).");
      return;
    }
    if (editable.is_round_trip) {
      if (editable.pickup_latitude == null || editable.pickup_longitude == null) {
        setFormError("Round trips need a pinned pickup point — pin it before saving.");
        return;
      }
      if (editable.latitude == null || editable.longitude == null) {
        setFormError("Round trips need a pinned errand destination — pin it before saving.");
        return;
      }
    }
    createMutation.mutate({
      title: editable.title.trim(),
      description: editable.description.trim(),
      task_type: editable.task_type,
      urgency: editable.urgency,
      budget,
      scheduled_date: editable.scheduled_date || null,
      scheduled_time: editable.scheduled_time || null,
      estimated_duration_minutes: editable.estimated_duration_minutes,
      latitude: editable.latitude,
      longitude: editable.longitude,
      address_text: editable.address_text || null,
      area_name: editable.area_name || null,
      city: editable.city || null,
      required_skills: editable.required_skills,
      parsed_by_ai: true,
      ai_confidence: draft.confidence,
      is_round_trip: editable.is_round_trip,
      pickup_latitude: editable.is_round_trip ? editable.pickup_latitude : null,
      pickup_longitude: editable.is_round_trip ? editable.pickup_longitude : null,
      pickup_address: editable.is_round_trip ? editable.pickup_address || null : null,
    });
  }

  function update<K extends keyof EditableDraft>(key: K, value: EditableDraft[K]) {
    setEditable((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  if (step === "describe") {
    return (
      <div className="mx-auto max-w-2xl px-4 py-6">
        <h1 className="text-2xl font-bold text-slate-900">What do you need done?</h1>
        <p className="mt-1 text-sm text-slate-500">
          Describe it like you'd tell a friend. Our AI turns it into a proper task — you review everything before it
          goes anywhere.
        </p>

        <Card className="mt-5">
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={5}
            maxLength={2000}
            placeholder="e.g. I need someone to submit my documents at the government office tomorrow morning. My budget is 300 rupees."
            aria-label="Describe your errand"
          />
          <div className="mt-3 flex items-center justify-between">
            <p className="text-xs text-slate-400">{text.trim().length}/2000 characters (min 10)</p>
            <Button
              onClick={() => parseMutation.mutate(text)}
              loading={parseMutation.isPending}
              disabled={text.trim().length < 10}
            >
              <Wand2 className="h-4 w-4" /> Interpret with AI
            </Button>
          </div>
        </Card>

        <div className="mt-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Try an example</p>
          <div className="mt-2 space-y-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => setText(ex)}
                className="block w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-left text-sm text-slate-600 hover:border-primary-300 hover:bg-primary-50/40"
              >
                “{ex}”
              </button>
            ))}
          </div>
        </div>

        {parseMutation.isPending && (
          <Card className="mt-5 border-primary-100">
            <div className="flex items-center gap-3">
              <Sparkles className="h-5 w-5 animate-pulse text-primary-600" />
              <div className="flex-1">
                <p className="text-sm font-medium text-slate-800">{PARSING_STAGES[stage]}</p>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-primary-500 transition-all duration-500"
                    style={{ width: `${((stage + 1) / PARSING_STAGES.length) * 100}%` }}
                  />
                </div>
              </div>
            </div>
          </Card>
        )}
      </div>
    );
  }

  if (step === "review" && draft && editable) {
    const confidencePct = scorePercent(draft.confidence);
    const fare = fareQuery.data;
    return (
      <div className="mx-auto max-w-2xl px-4 py-6">
        <button onClick={() => setStep("describe")} className="mb-3 text-sm font-medium text-slate-500 hover:text-slate-700">
          ← Edit your description
        </button>
        <h1 className="text-2xl font-bold text-slate-900">Did we read you right?</h1>
        <p className="mt-1 text-sm text-slate-500">
          Nothing is dispatched yet. Fix anything below, then save the task.
        </p>

        <Card className="mt-4 border-primary-100 bg-primary-50/50">
          <div className="flex items-center justify-between">
            <p className="flex items-center gap-2 text-sm font-semibold text-slate-800">
              <Sparkles className="h-4 w-4 text-primary-600" /> AI interpretation
              <span className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-slate-500">
                via {draft.provider}
              </span>
            </p>
            <div className="text-right">
              <p className={cn("text-lg font-bold", confidencePct >= 70 ? "text-emerald-600" : confidencePct >= 45 ? "text-amber-600" : "text-red-500")}>
                {confidencePct}%
              </p>
              <p className="text-[10px] uppercase tracking-wide text-slate-400">confidence</p>
            </div>
          </div>
          {draft.clarification_questions.length > 0 && (
            <div className="mt-3 rounded-lg bg-white p-3">
              <p className="text-xs font-semibold text-slate-500">To make this clearer, consider:</p>
              <ul className="mt-1.5 space-y-1">
                {draft.clarification_questions.map((q) => (
                  <li key={q} className="text-xs text-slate-600">
                    • {q}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {draft.missing_fields.length > 0 && (
            <p className="mt-2 text-xs text-amber-700">
              Missing details: {draft.missing_fields.join(", ")} — add them below before confirming.
            </p>
          )}
        </Card>

        <Card className="mt-4 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Errand type">
              <div className="input flex items-center gap-2 bg-slate-50">
                <span>{TASK_TYPE_ICONS[editable.task_type as keyof typeof TASK_TYPE_ICONS] ?? "🧭"}</span>
                {TASK_TYPE_LABELS[editable.task_type as keyof typeof TASK_TYPE_LABELS] ?? editable.task_type}
              </div>
            </Field>
            <Field label="Urgency" htmlFor="urgency">
              <Select id="urgency" value={editable.urgency} onChange={(e) => update("urgency", e.target.value)}>
                {Object.entries(URGENCY_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <Field label="Title" htmlFor="title">
            <Input id="title" value={editable.title} onChange={(e) => update("title", e.target.value)} maxLength={160} />
          </Field>

          <Field label="Description" htmlFor="description">
            <Textarea id="description" value={editable.description} onChange={(e) => update("description", e.target.value)} maxLength={4000} />
          </Field>

          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Budget (₹)" htmlFor="budget">
              <Input id="budget" type="number" min={1} step="1" value={editable.budget} onChange={(e) => update("budget", e.target.value)} />
            </Field>
            <Field label="Date" htmlFor="date">
              <Input id="date" type="date" value={editable.scheduled_date} onChange={(e) => update("scheduled_date", e.target.value)} />
            </Field>
            <Field label="Time" htmlFor="time">
              <Input id="time" type="time" value={editable.scheduled_time} onChange={(e) => update("scheduled_time", e.target.value)} />
            </Field>
          </div>

          <div>
            <p className="label">Trip type</p>
            <div className="mt-1 grid gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => update("is_round_trip", false)}
                className={cn(
                  "rounded-xl border px-3 py-2.5 text-left text-sm transition",
                  !editable.is_round_trip
                    ? "border-primary-500 bg-primary-50 text-primary-800"
                    : "border-slate-200 bg-white text-slate-600 hover:border-primary-300"
                )}
              >
                <span className="font-semibold">One way</span>
                <span className="mt-0.5 block text-xs text-slate-500">The errand ends at the destination.</span>
              </button>
              <button
                type="button"
                onClick={() => update("is_round_trip", true)}
                className={cn(
                  "rounded-xl border px-3 py-2.5 text-left text-sm transition",
                  editable.is_round_trip
                    ? "border-teal-500 bg-teal-50 text-teal-900"
                    : "border-slate-200 bg-white text-slate-600 hover:border-teal-300"
                )}
              >
                <span className="flex items-center gap-1.5 font-semibold">
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Round trip
                </span>
                <span className="mt-0.5 block text-xs text-slate-500">
                  Runner returns to the pickup point; the handback code releases payment.
                </span>
              </button>
            </div>
          </div>

          {editable.is_round_trip && (
            <div className="space-y-3 rounded-xl border border-teal-200 bg-teal-50/50 p-4">
              <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-teal-700">
                <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Pickup point (return origin)
              </p>
              <div className="flex gap-2">
                <Input
                  value={editable.pickup_address}
                  onChange={(e) => update("pickup_address", e.target.value)}
                  placeholder="Where should the runner collect and return the goods?"
                />
                <Button variant="secondary" onClick={() => void geocodePickup()} loading={geocodingPickup} className="shrink-0">
                  <MapPin className="h-4 w-4" /> Pin
                </Button>
              </div>
              {editable.pickup_latitude != null && editable.pickup_longitude != null ? (
                <p className="flex items-center gap-1.5 text-xs font-medium text-teal-700">
                  <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Pickup pinned at{" "}
                  {editable.pickup_latitude.toFixed(5)}, {editable.pickup_longitude.toFixed(5)}
                </p>
              ) : (
                <p className="text-xs text-teal-700">
                  Pin the pickup point so the runner gets a route to collect the goods before heading to the destination.
                </p>
              )}
              <p className="text-[11px] text-teal-700">
                The return leg is billed at 0.5× the per-km rate. The customer's 4-digit return code is required before
                completion and payout.
              </p>
            </div>
          )}

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <IndianRupee className="h-3.5 w-3.5" aria-hidden /> Dynamic fare floor
              </p>
              {editable.latitude == null || editable.longitude == null ? (
                <span className="text-[11px] text-slate-400">Pin a location for a priced estimate</span>
              ) : null}
            </div>

            {editable.latitude == null || editable.longitude == null ? (
              <p className="mt-2 text-sm text-slate-500">
                Pin the task location below to see the minimum fare for this distance and urgency. Your budget must be
                at or above the floor when you confirm the task.
              </p>
            ) : fareQuery.isLoading ? (
              <p className="mt-2 text-sm text-slate-400">Calculating the road-distance floor…</p>
            ) : fare ? (
              <div className="mt-2 space-y-2">
                <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                  <div>
                    <p className="text-[11px] text-slate-400">Minimum fare</p>
                    <p className="font-bold text-slate-900">
                      {formatMoney(fare.estimate.minimum_fare, fare.estimate.currency)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] text-slate-400">Recommended</p>
                    <p className="font-bold text-emerald-700">
                      {formatMoney(fare.estimate.recommended_fare, fare.estimate.currency)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] text-slate-400">Base + distance + wait</p>
                    <p className="font-medium text-slate-700">
                      {formatMoney(fare.estimate.breakdown.base_fare, fare.estimate.currency)} +{" "}
                      {formatMoney(fare.estimate.breakdown.distance_charge, fare.estimate.currency)} +{" "}
                      {formatMoney(fare.estimate.breakdown.wait_charge, fare.estimate.currency)}
                    </p>
                  </div>
                  {editable.is_round_trip && (
                    <div>
                      <p className="text-[11px] text-slate-400">Return leg (0.5×)</p>
                      <p className="font-medium text-slate-700">
                        {formatMoney(fare.estimate.breakdown.return_charge ?? 0, fare.estimate.currency)}
                      </p>
                    </div>
                  )}
                </div>

                {fare.warning ? (
                  <div
                    className={cn(
                      "flex items-start gap-2 rounded-lg px-3 py-2 text-xs",
                      fare.warning.code === "BELOW_MINIMUM_FLOOR"
                        ? "bg-red-100 text-red-800"
                        : "bg-amber-100 text-amber-800"
                    )}
                  >
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                    <div>
                      <p>{fare.warning.message}</p>
                      {fare.warning.code === "BELOW_MINIMUM_FLOOR" && (
                        <button
                          type="button"
                          className="mt-1 font-semibold underline"
                          onClick={() => update("budget", String(Math.ceil(fare.estimate.minimum_fare)))}
                        >
                          Use the minimum fare
                        </button>
                      )}
                    </div>
                  </div>
                ) : (
                  <p className="flex items-center gap-1.5 text-xs text-emerald-700">
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Your budget meets the recommended fare —
                    runners are more likely to accept quickly.
                  </p>
                )}
                <p className="text-[11px] text-slate-400">
                  The floor is enforced at confirmation. Urgency multiplier is{" "}
                  {fare.estimate.breakdown.urgency_multiplier.toFixed(1)}× for{" "}
                  {URGENCY_LABELS[editable.urgency as keyof typeof URGENCY_LABELS] ?? editable.urgency}.
                </p>
              </div>
            ) : (
              <p className="mt-2 text-sm text-slate-400">
                Couldn't load a fare estimate right now — you can still save the task.
              </p>
            )}
          </div>

          <Field
            label={editable.is_round_trip ? "Errand destination" : "Where"}
            htmlFor="address"
            hint={
              editable.is_round_trip
                ? "Where the errand happens. The runner returns to the pinned pickup point afterwards."
                : "Pin the location so we can match nearby runners."
            }
          >
            <div className="flex gap-2">
              <Input id="address" value={editable.address_text} onChange={(e) => update("address_text", e.target.value)} placeholder="Address or place name" />
              <Button variant="secondary" onClick={geocode} loading={geocoding} className="shrink-0">
                <MapPin className="h-4 w-4" /> Pin
              </Button>
            </div>
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Area / locality">
              <Input value={editable.area_name} onChange={(e) => update("area_name", e.target.value)} placeholder="e.g. Sadashivnagar" />
            </Field>
            <Field label="City">
              <Input value={editable.city} onChange={(e) => update("city", e.target.value)} placeholder="e.g. Belagavi" />
            </Field>
          </div>

          {editable.required_skills.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {editable.required_skills.map((skill) => (
                <span key={skill} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
                  {skill.replaceAll("_", " ")}
                </span>
              ))}
            </div>
          )}

          {formError && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{formError}</p>}

          <Button onClick={submitDraft} loading={createMutation.isPending} className="w-full">
            Save task — review before dispatch
          </Button>
        </Card>
      </div>
    );
  }

  if (step === "saved" && created) {
    return (
      <div className="mx-auto max-w-xl px-4 py-10">
        <Card className="border-amber-200 p-6 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-amber-100 text-2xl">⏸️</div>
          <h1 className="mt-4 text-xl font-bold text-slate-900">Task saved — waiting on you</h1>
          <p className="mx-auto mt-2 max-w-sm text-sm text-slate-500">
            Per TaskFlex policy, no runner sees your errand until you explicitly confirm it. Review the summary, then
            dispatch when ready.
          </p>
          <div className="mt-5 rounded-xl bg-slate-50 p-4 text-left">
            <p className="font-semibold text-slate-900">{created.title}</p>
            <p className="mt-1 text-sm text-slate-600">
              {TASK_TYPE_LABELS[created.task_type] ?? created.task_type} · {formatMoney(created.budget, created.currency)}
              {created.scheduled_date ? ` · ${created.scheduled_date}` : ""}
            </p>
          </div>
          <div className="mt-5 flex flex-col gap-2 sm:flex-row">
            <Button onClick={() => confirmMutation.mutate(created.id)} loading={confirmMutation.isPending} className="flex-1">
              <CheckCircle2 className="h-4 w-4" /> Confirm & find runners
            </Button>
            <Link to={`/app/tasks/${created.id}`} className="btn-secondary flex-1">
              View task page
            </Link>
          </div>
        </Card>
      </div>
    );
  }

  if (step === "dispatched" && created) {
    return (
      <div className="mx-auto max-w-xl px-4 py-10">
        <Card className="border-emerald-200 p-6 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100">
            <CheckCircle2 className="h-7 w-7 text-emerald-600" />
          </div>
          <h1 className="mt-4 text-xl font-bold text-slate-900">Searching for runners</h1>
          <p className="mx-auto mt-2 max-w-sm text-sm text-slate-500">
            We ranked verified runners by distance, skills, ratings and reliability. Offers go out to the best
            matches — you'll get a notification the moment someone accepts.
          </p>
          <div className="mt-5 flex flex-col gap-2 sm:flex-row">
            <Link to={`/app/tasks/${created.id}`} className="btn-primary flex-1">
              Track this task
            </Link>
            <Link to="/app" className="btn-secondary flex-1">
              Back to dashboard
            </Link>
          </div>
        </Card>
      </div>
    );
  }

  void navigate;
  return null;
}
