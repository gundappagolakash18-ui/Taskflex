import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Link2, RefreshCw, ShieldOff } from "lucide-react";

import { SHAREABLE_STATUSES } from "@/lib/constants";
import { errorMessage, formatDateTime } from "@/lib/utils";
import { Button, Card, Field, Select } from "@/components/ui";
import { tasksApi } from "@/api/tasks";
import { toast } from "@/stores/toast";
import type { Task } from "@/types";

export function ShareTrackingCard({ task }: { task: Task }) {
  const queryClient = useQueryClient();
  const [hours, setHours] = useState(24);
  const [copied, setCopied] = useState(false);

  const shareable = SHAREABLE_STATUSES.includes(task.status);

  const linkQuery = useQuery({
    queryKey: ["task-share", task.id],
    queryFn: () => tasksApi.getShareLink(task.id),
    enabled: shareable,
    staleTime: 30_000,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["task-share", task.id] });
  };

  const createMutation = useMutation({
    mutationFn: (rotate: boolean) => tasksApi.createShareLink(task.id, { expires_in_hours: hours, rotate }),
    onSuccess: () => {
      toast.success("Live tracking link ready.");
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const revokeMutation = useMutation({
    mutationFn: () => tasksApi.revokeShareLink(task.id),
    onSuccess: () => {
      toast.info("Tracking link revoked.");
      setCopied(false);
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (!shareable) return null;

  const link = linkQuery.data ?? null;

  const copy = async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link.url);
      setCopied(true);
      toast.success("Link copied. Anyone with it can follow the runner — no account needed.");
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      toast.info(link.url);
    }
  };

  return (
    <Card>
      <h2 className="flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-slate-400">
        <Link2 className="h-4 w-4" aria-hidden /> Share live tracking
      </h2>
      <p className="mt-1 text-sm text-slate-500">
        Send a read-only tracking link to family or a colleague. It shows the runner's live position and ETA only —
        never your contact details, address text or task id.
      </p>

      {linkQuery.isLoading ? (
        <p className="mt-3 text-sm text-slate-400">Checking for an active link…</p>
      ) : link ? (
        <div className="mt-3 space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              readOnly
              value={link.url}
              aria-label="Public tracking link"
              className="input flex-1 text-xs text-slate-600"
              onFocus={(e) => e.currentTarget.select()}
            />
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => void copy()}>
                {copied ? <RefreshCw className="mr-1.5 h-4 w-4" aria-hidden /> : <Copy className="mr-1.5 h-4 w-4" aria-hidden />}
                {copied ? "Copied" : "Copy"}
              </Button>
              <Button variant="ghost" onClick={() => createMutation.mutate(true)} loading={createMutation.isPending}>
                <RefreshCw className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
            <span>Expires {formatDateTime(link.expires_at)}</span>
            <button
              type="button"
              className="inline-flex items-center gap-1 font-medium text-red-600 hover:underline"
              onClick={() => revokeMutation.mutate()}
              disabled={revokeMutation.isPending}
            >
              <ShieldOff className="h-3.5 w-3.5" aria-hidden /> Revoke link
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
          <Field label="Link validity" htmlFor="share-hours">
            <Select id="share-hours" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
              <option value={12}>12 hours</option>
              <option value={24}>24 hours</option>
              <option value={48}>48 hours</option>
              <option value={72}>72 hours</option>
            </Select>
          </Field>
          <Button loading={createMutation.isPending} onClick={() => createMutation.mutate(false)}>
            <Link2 className="mr-1.5 h-4 w-4" aria-hidden /> Create tracking link
          </Button>
        </div>
      )}
    </Card>
  );
}
