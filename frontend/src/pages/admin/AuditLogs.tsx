import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { adminApi } from "@/api/admin";
import { Badge, Button, Card, EmptyState, PageLoader, Select } from "@/components/ui";
import type { AuditLog } from "@/types";

const ACTION_OPTIONS = ["", "USER_LOGIN", "USER_DEACTIVATED", "DOCUMENT_APPROVED", "DOCUMENT_REJECTED", "TASK_CANCELLED", "SETTING_UPDATED", "DISPUTE_RESOLVED"];

function actionStyle(action: string): string {
  if (action.includes("REJECT") || action.includes("DEACTIVAT") || action.includes("CANCEL")) {
    return "bg-red-100 text-red-700";
  }
  if (action.includes("APPROVE") || action.includes("LOGIN")) {
    return "bg-emerald-100 text-emerald-700";
  }
  return "bg-slate-100 text-slate-600";
}

export default function AuditLogs() {
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);

  const logs = useQuery({
    queryKey: ["admin-audit-logs", action, page],
    queryFn: () => adminApi.auditLogs({ action: action || undefined, page, page_size: 30 }),
  });

  const rows = logs.data?.items ?? [];
  const total = logs.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 30));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Audit logs</h1>
          <p className="text-sm text-slate-500">{total} recorded admin actions</p>
        </div>
        <Select
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
            setPage(1);
          }}
          className="w-52"
        >
          {ACTION_OPTIONS.map((a) => (
            <option key={a} value={a}>
              {a === "" ? "All actions" : a.replaceAll("_", " ").toLowerCase()}
            </option>
          ))}
        </Select>
      </div>

      {logs.isLoading ? (
        <PageLoader />
      ) : rows.length === 0 ? (
        <EmptyState icon="🗂️" title="No audit entries" description="Administrative actions will be recorded here." />
      ) : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3">Action</th>
                <th className="px-4 py-3">Entity</th>
                <th className="px-4 py-3">Actor</th>
                <th className="px-4 py-3">IP</th>
                <th className="px-4 py-3">When</th>
              </tr>
            </thead>
            <tbody>
              {(rows as AuditLog[]).map((log) => (
                <tr key={log.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-3">
                    <Badge className={actionStyle(log.action)}>{log.action.replaceAll("_", " ").toLowerCase()}</Badge>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600">
                    {log.entity_type ? `${log.entity_type} · ${log.entity_id?.slice(0, 8)}…` : "—"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600">
                    {log.user_id ? log.user_id.slice(0, 8) + "…" : "system"}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">{log.ip_address ?? "—"}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">{new Date(log.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <span className="text-sm text-slate-500">
            Page {page} of {totalPages}
          </span>
          <Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
