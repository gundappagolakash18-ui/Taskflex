import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { adminApi } from "@/api/admin";
import { Badge, Button, Card, EmptyState, PageLoader, Select } from "@/components/ui";
import type { Payment } from "@/types";

const PAYMENT_STYLES: Record<string, string> = {
  PENDING: "bg-amber-100 text-amber-700",
  INITIATED: "bg-amber-100 text-amber-700",
  AUTHORIZED: "bg-sky-100 text-sky-700",
  CAPTURED: "bg-emerald-100 text-emerald-700",
  FAILED: "bg-red-100 text-red-700",
  REFUNDED: "bg-slate-200 text-slate-600",
  CANCELLED: "bg-slate-100 text-slate-500",
};

const STATUS_OPTIONS = ["", "INITIATED", "AUTHORIZED", "CAPTURED", "FAILED", "REFUNDED", "CANCELLED"];

function money(amount: number): string {
  return `₹${amount.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
}

export default function Payments() {
  const [tab, setTab] = useState<"payments" | "transactions">("payments");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);

  const payments = useQuery({
    queryKey: ["admin-payments", status, page],
    queryFn: () => adminApi.payments({ status: status || undefined, page, page_size: 20 }),
    enabled: tab === "payments",
  });

  const transactions = useQuery({
    queryKey: ["admin-transactions", page],
    queryFn: () => adminApi.transactions({ page, page_size: 20 }),
    enabled: tab === "transactions",
  });

  const activeQuery = tab === "payments" ? payments : transactions;
  const rows = activeQuery.data?.items ?? [];
  const total = activeQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 20));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Payments</h1>
        <p className="text-sm text-slate-500">Escrow payments and wallet transactions</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-lg border border-slate-200 bg-white p-1">
          {(["payments", "transactions"] as const).map((t) => (
            <button
              key={t}
              onClick={() => {
                setTab(t);
                setPage(1);
              }}
              className={
                tab === t
                  ? "rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white"
                  : "rounded-md px-4 py-1.5 text-sm font-medium text-slate-500 hover:text-slate-800"
              }
            >
              {t === "payments" ? "Escrow payments" : "Wallet transactions"}
            </button>
          ))}
        </div>
        {tab === "payments" && (
          <Select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
            className="w-44"
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s === "" ? "Any status" : s.toLowerCase()}
              </option>
            ))}
          </Select>
        )}
      </div>

      {activeQuery.isLoading ? (
        <PageLoader />
      ) : rows.length === 0 ? (
        <EmptyState
          icon="💳"
          title={tab === "payments" ? "No payments yet" : "No transactions yet"}
          description="Records appear once customers start funding errands."
        />
      ) : tab === "payments" ? (
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3">Task</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Commission</th>
                <th className="px-4 py-3">Runner payout</th>
                <th className="px-4 py-3">Provider</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Captured</th>
              </tr>
            </thead>
            <tbody>
              {(rows as Payment[]).map((p) => (
                <tr key={p.id} className="border-b border-slate-100 last:border-0">
                  <td className="max-w-56 truncate px-4 py-3 text-slate-700">
                    {p.task_id.slice(0, 8)}…
                  </td>
                  <td className="px-4 py-3 font-medium text-slate-900">{money(p.amount)}</td>
                  <td className="px-4 py-3 text-slate-600">{money(p.commission_amount)}</td>
                  <td className="px-4 py-3 text-slate-600">{money(p.worker_payout_amount)}</td>
                  <td className="px-4 py-3 text-slate-500">{p.provider}</td>
                  <td className="px-4 py-3">
                    <Badge className={PAYMENT_STYLES[p.status] ?? "bg-slate-100 text-slate-600"}>{p.status.toLowerCase()}</Badge>
                  </td>
                  <td className="px-4 py-3 text-slate-500">
                    {p.captured_at ? new Date(p.captured_at).toLocaleDateString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3">Description</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Balance after</th>
                <th className="px-4 py-3">Date</th>
              </tr>
            </thead>
            <tbody>
              {(rows as { id: string; type: string; amount: number; balance_after: number; description: string; created_at: string }[]).map((t) => (
                <tr key={t.id} className="border-b border-slate-100 last:border-0">
                  <td className="max-w-72 truncate px-4 py-3 text-slate-700">{t.description}</td>
                  <td className="px-4 py-3">
                    <Badge className="bg-slate-100 text-slate-600">{t.type.toLowerCase()}</Badge>
                  </td>
                  <td className={"px-4 py-3 font-medium " + (t.amount >= 0 ? "text-emerald-600" : "text-red-600")}>
                    {t.amount >= 0 ? "+" : ""}
                    {money(t.amount)}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{money(t.balance_after)}</td>
                  <td className="px-4 py-3 text-slate-500">{new Date(t.created_at).toLocaleString()}</td>
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
