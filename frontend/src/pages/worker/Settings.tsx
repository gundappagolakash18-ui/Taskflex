import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Clock, FileUp, Trash2 } from "lucide-react";

import { DAY_NAMES } from "@/lib/constants";
import { cn, errorMessage, formatDateTime } from "@/lib/utils";
import { Badge, Button, Card, Field, Input, PageLoader, Textarea } from "@/components/ui";
import { locationApi } from "@/api/location";
import { workersApi } from "@/api/workers";
import { toast } from "@/stores/toast";
import type { AvailabilityEntry } from "@/types";

const SKILL_OPTIONS = [
  { slug: "document_submission", label: "Document submission" },
  { slug: "queue_standing", label: "Queue standing" },
  { slug: "government_office", label: "Government office work" },
  { slug: "document_collection", label: "Document collection" },
  { slug: "courier_pickup", label: "Courier & parcel pickup" },
  { slug: "grocery_pickup", label: "Grocery pickup" },
  { slug: "bank_assistance", label: "Bank assistance" },
  { slug: "hospital_assistance", label: "Hospital assistance" },
  { slug: "form_filling", label: "Form filling" },
  { slug: "local_errand", label: "Local errands" },
];

const DOC_TYPES = [
  { value: "id_card", label: "Government ID card" },
  { value: "address_proof", label: "Address proof" },
  { value: "police_clearance", label: "Police clearance" },
  { value: "other", label: "Other supporting document" },
];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const DOC_STATUS_STYLES: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  approved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-red-100 text-red-600",
};

function defaultAvailability(existing?: AvailabilityEntry[]): AvailabilityEntry[] {
  return DAY_NAMES.map((_day, idx) => {
    const found = existing?.find((e) => e.day_of_week === idx);
    return found ?? { day_of_week: idx, start_time: "08:00", end_time: "20:00", is_available: idx < 6 };
  });
}

function ProfileSection() {
  const queryClient = useQueryClient();
  const profileQuery = useQuery({ queryKey: ["worker-profile"], queryFn: () => workersApi.myProfile() });

  const [form, setForm] = useState<{
    bio: string;
    address: string;
    area: string;
    city: string;
    experience_years: number;
    languages: string;
    working_radius_km: number;
    max_concurrent_tasks: number;
    skills: string[];
  } | null>(null);

  const profile = profileQuery.data;
  const value = form ?? (profile ? {
    bio: profile.bio ?? "",
    address: "",
    area: profile.area ?? "",
    city: profile.city ?? "",
    experience_years: profile.experience_years,
    languages: profile.languages ?? "",
    working_radius_km: profile.working_radius_km ?? 10,
    max_concurrent_tasks: profile.max_concurrent_tasks ?? 2,
    skills: profile.skills,
  } : null);

  const updateMutation = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {
        bio: value!.bio || undefined,
        area: value!.area || undefined,
        city: value!.city || undefined,
        experience_years: value!.experience_years,
        languages: value!.languages || undefined,
        working_radius_km: value!.working_radius_km,
        max_concurrent_tasks: value!.max_concurrent_tasks,
        skill_slugs: value!.skills,
      };
      if (value!.address.trim()) payload.address = value!.address.trim();
      return workersApi.updateProfile(payload);
    },
    onSuccess: () => {
      toast.success("Profile updated.");
      setForm(null);
      void queryClient.invalidateQueries({ queryKey: ["worker-profile"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const pinMutation = useMutation({
    mutationFn: () => locationApi.geocode(`${value!.address}, ${value!.area}, ${value!.city}`),
    onSuccess: (result) => {
      if (!result) {
        toast.error("Couldn't locate that address — try adding more detail.");
        return;
      }
      updateMutation.mutate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (profileQuery.isLoading || !profile || !value) return <PageLoader />;

  const toggleSkill = (slug: string) =>
    setForm({
      ...value,
      skills: value.skills.includes(slug) ? value.skills.filter((s) => s !== slug) : [...value.skills, slug],
    });

  return (
    <Card>
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Runner profile</h2>
        {profile.is_verified && (
          <Badge className="bg-emerald-100 text-emerald-700">
            <BadgeCheck className="h-3.5 w-3.5" aria-hidden /> Verified
          </Badge>
        )}
      </div>

      <div className="mt-4 space-y-4">
        <Field label="About you" htmlFor="bio" hint="Customers read this before hiring. Mention your strengths.">
          <Textarea id="bio" rows={3} maxLength={1000} value={value.bio} onChange={(e) => setForm({ ...value, bio: e.target.value })} />
        </Field>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="City" htmlFor="city">
            <Input id="city" value={value.city} onChange={(e) => setForm({ ...value, city: e.target.value })} />
          </Field>
          <Field label="Area / locality" htmlFor="area">
            <Input id="area" value={value.area} onChange={(e) => setForm({ ...value, area: e.target.value })} />
          </Field>
        </div>

        <Field label="Update home address (optional)" htmlFor="address" hint="Pins your location for distance-based matching. Never shown to customers.">
          <Input id="address" placeholder="Street, landmark…" value={value.address} onChange={(e) => setForm({ ...value, address: e.target.value })} />
        </Field>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Experience (years)" htmlFor="exp">
            <Input
              id="exp"
              type="number"
              min={0}
              max={60}
              value={value.experience_years}
              onChange={(e) => setForm({ ...value, experience_years: Number(e.target.value) })}
            />
          </Field>
          <Field label="Languages" htmlFor="langs" hint="Comma separated">
            <Input id="langs" placeholder="English, Hindi, Kannada" value={value.languages} onChange={(e) => setForm({ ...value, languages: e.target.value })} />
          </Field>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={`Working radius — ${value.working_radius_km} km`} htmlFor="radius">
            <input
              id="radius"
              type="range"
              min={1}
              max={50}
              value={value.working_radius_km}
              onChange={(e) => setForm({ ...value, working_radius_km: Number(e.target.value) })}
              className="w-full accent-primary-600"
            />
          </Field>
          <Field label="Max concurrent tasks" htmlFor="maxtasks">
            <Input
              id="maxtasks"
              type="number"
              min={1}
              max={10}
              value={value.max_concurrent_tasks}
              onChange={(e) => setForm({ ...value, max_concurrent_tasks: Number(e.target.value) })}
            />
          </Field>
        </div>

        <div>
          <p className="label">Skills</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {SKILL_OPTIONS.map((s) => {
              const active = value.skills.includes(s.slug);
              return (
                <button
                  key={s.slug}
                  type="button"
                  onClick={() => toggleSkill(s.slug)}
                  className={cn(
                    "rounded-full px-3 py-1.5 text-xs font-medium transition",
                    active ? "bg-primary-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  )}
                >
                  {s.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex gap-2">
          <Button loading={updateMutation.isPending} onClick={() => updateMutation.mutate()}>
            Save profile
          </Button>
          {value.address.trim() && (
            <Button variant="secondary" loading={pinMutation.isPending} onClick={() => pinMutation.mutate()}>
              Save & re-pin my location
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}

function AvailabilitySection() {
  const queryClient = useQueryClient();
  const profileQuery = useQuery({ queryKey: ["worker-profile"], queryFn: () => workersApi.myProfile() });
  const [entries, setEntries] = useState<AvailabilityEntry[] | null>(null);

  const existing = profileQuery.data?.availability;
  const value = entries ?? defaultAvailability(existing);

  const mutation = useMutation({
    mutationFn: () => workersApi.setAvailability(value.filter((e) => e.is_available)),
    onSuccess: () => {
      toast.success("Availability saved.");
      setEntries(null);
      void queryClient.invalidateQueries({ queryKey: ["worker-profile"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const update = (idx: number, patch: Partial<AvailabilityEntry>) => {
    setEntries(value.map((e, i) => (i === idx ? { ...e, ...patch } : e)));
  };

  return (
    <Card>
      <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
        <Clock className="h-4 w-4" aria-hidden /> Weekly availability
      </h2>
      <p className="mt-1 text-sm text-slate-500">The matching engine only offers tasks inside these windows.</p>

      <div className="mt-4 space-y-2">
        {value.map((entry, idx) => (
          <div key={entry.day_of_week} className="flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 px-3 py-2">
            <label className="flex w-28 items-center gap-2 text-sm font-medium text-slate-700">
              <input
                type="checkbox"
                checked={entry.is_available}
                onChange={(e) => update(idx, { is_available: e.target.checked })}
                className="h-4 w-4 rounded border-slate-300 text-primary-600 accent-primary-600"
              />
              {DAY_NAMES[entry.day_of_week].slice(0, 3)}
            </label>
            <input
              type="time"
              className="input w-28 py-1.5 text-sm"
              value={entry.start_time}
              disabled={!entry.is_available}
              onChange={(e) => update(idx, { start_time: e.target.value })}
              aria-label={`${DAY_NAMES[entry.day_of_week]} start time`}
            />
            <span className="text-slate-400">–</span>
            <input
              type="time"
              className="input w-28 py-1.5 text-sm"
              value={entry.end_time}
              disabled={!entry.is_available}
              onChange={(e) => update(idx, { end_time: e.target.value })}
              aria-label={`${DAY_NAMES[entry.day_of_week]} end time`}
            />
          </div>
        ))}
      </div>

      <Button className="mt-4" loading={mutation.isPending} onClick={() => mutation.mutate()}>
        Save availability
      </Button>
    </Card>
  );
}

function DocumentsSection() {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [docType, setDocType] = useState("id_card");
  const [file, setFile] = useState<File | null>(null);

  const docsQuery = useQuery({ queryKey: ["worker-documents"], queryFn: () => workersApi.myDocuments() });

  const uploadMutation = useMutation({
    mutationFn: () => workersApi.uploadDocument(file!, docType),
    onSuccess: () => {
      toast.success("Document uploaded — our team will verify it shortly.");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      void queryClient.invalidateQueries({ queryKey: ["worker-documents"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => workersApi.deleteDocument(id),
    onSuccess: () => {
      toast.info("Document removed.");
      void queryClient.invalidateQueries({ queryKey: ["worker-documents"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const docs = docsQuery.data ?? [];

  return (
    <Card>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Verification documents</h2>
      <p className="mt-1 text-sm text-slate-500">
        Only TaskFlex admins can view these. Verified runners rank higher in customer searches and matching.
      </p>

      {docsQuery.isLoading ? (
        <p className="mt-4 text-sm text-slate-400">Loading documents…</p>
      ) : docs.length > 0 ? (
        <ul className="mt-4 space-y-2">
          {docs.map((d) => (
            <li key={d.id} className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-2.5">
              <FileUp className="h-4 w-4 shrink-0 text-primary-600" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-800">{d.file_name}</p>
                <p className="text-xs text-slate-400">
                  {DOC_TYPES.find((t) => t.value === d.document_type)?.label ?? d.document_type} · {formatBytes(d.file_size)} ·{" "}
                  {formatDateTime(d.created_at)}
                </p>
                {d.status === "rejected" && d.rejection_reason && (
                  <p className="mt-0.5 text-xs text-red-500">Rejected: {d.rejection_reason}</p>
                )}
              </div>
              <Badge className={DOC_STATUS_STYLES[d.status] ?? "bg-slate-100 text-slate-600"}>{d.status}</Badge>
              <button
                type="button"
                onClick={() => deleteMutation.mutate(d.id)}
                disabled={deleteMutation.isPending}
                className="rounded-lg p-1.5 text-slate-400 transition hover:bg-red-50 hover:text-red-500"
                aria-label={`Delete ${d.file_name}`}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          No documents uploaded yet. Your profile stays unverified until at least one ID document is approved.
        </p>
      )}

      <div className="mt-5 space-y-3 border-t border-slate-100 pt-4">
        <Field label="Document type" htmlFor="doc-type">
          <select id="doc-type" className="input appearance-none pr-8" value={docType} onChange={(e) => setDocType(e.target.value)}>
            {DOC_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="File" htmlFor="doc-file" hint="JPG, PNG or PDF up to 8 MB.">
          <input
            id="doc-file"
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,application/pdf"
            className="input file:mr-3 file:rounded-md file:border-0 file:bg-primary-50 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-700"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </Field>
        <Button loading={uploadMutation.isPending} disabled={!file} onClick={() => uploadMutation.mutate()}>
          Upload document
        </Button>
      </div>
    </Card>
  );
}

export default function WorkerSettings() {
  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Runner settings</h1>
        <p className="mt-0.5 text-sm text-slate-500">Everything customers and the matching engine see about you.</p>
      </div>
      <ProfileSection />
      <AvailabilitySection />
      <DocumentsSection />
    </div>
  );
}
