import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownLeft,
  ArrowUpRight,
  CheckCircle2,
  Download,
  IndianRupee,
  Landmark,
  ReceiptText,
  Wallet as WalletIcon,
} from "lucide-react";

import { cn, errorMessage, formatDate, formatDateTime, formatMoney } from "@/lib/utils";
import { STATEMENT_CATEGORY_LABELS } from "@/lib/constants";
import { Badge, Button, Card, EmptyState, Field, Input, PageLoader, SkeletonList } from "@/components/ui";
import { usersApi } from "@/api/users";
import { walletApi } from "@/api/wallet";
import { workersApi } from "@/api/workers";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";
import type { StatementCategory } from "@/types";

const TXN_STYLES: Record<string, { label: string; positive: boolean }> = {
  CREDIT: { label: "Credit", positive: true },
  DEBIT: { label: "Debit", positive: false },
  TOPUP: { label: "Top-up", positive: true },
  REFUND: { label: "Refund", positive: true },
  PAYOUT: { label: "Payout", positive: true },
  PAYMENT: { label: "Payment", positive: false },
  COMMISSION: { label: "Commission", positive: false },
};

const UPI_PATTERN = /^[\w.\-]+@[\w]+$/;

const STATEMENT_ORDER: StatementCategory[] = [
  "base_earnings",
  "overtime_earnings",
  "reimbursed_expenses",
  "tips",
  "quest_bonuses",
];

export default function Wallet() {
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const isWorker = user?.role === "WORKER";

  const [upiInput, setUpiInput] = useState("");
  const [withdrawAmount, setWithdrawAmount] = useState("");
  const [statementDays, setStatementDays] = useState(30);
  const [lastPayout, setLastPayout] = useState<{ amount: number; reference_utr: string; upi_id: string } | null>(null);

  const walletQuery = useQuery({ queryKey: ["wallet"], queryFn: () => usersApi.wallet() });
  const txnsQuery = useQuery({
    queryKey: ["transactions"],
    queryFn: () => usersApi.transactions(1, 50),
  });
  const profileQuery = useQuery({
    queryKey: ["worker-profile"],
    queryFn: () => workersApi.myProfile(),
    enabled: isWorker,
  });
  const payoutsQuery = useQuery({
    queryKey: ["payouts"],
    queryFn: () => walletApi.payouts(1, 20),
    enabled: isWorker,
  });
  const statementQuery = useQuery({
    queryKey: ["wallet-statement", statementDays],
    queryFn: () => walletApi.statement(statementDays),
    enabled: isWorker,
  });

  const savedUpi = profileQuery.data?.upi_id ?? "";
  const effectiveUpi = upiInput.trim() || savedUpi;

  const upiMutation = useMutation({
    mutationFn: () => walletApi.setUpi(upiInput.trim()),
    onSuccess: (data) => {
      toast.success(`UPI ID ${data.upi_id} saved — withdrawals will use it.`);
      setUpiInput("");
      void queryClient.invalidateQueries({ queryKey: ["worker-profile"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const withdrawMutation = useMutation({
    mutationFn: () => walletApi.withdraw(Number(withdrawAmount), upiInput.trim() || null),
    onSuccess: (result) => {
      setLastPayout({
        amount: result.payout.amount,
        reference_utr: result.payout.reference_utr,
        upi_id: result.payout.upi_id,
      });
      toast.success(
        `${formatMoney(result.payout.amount)} sent to ${result.payout.upi_id} — UTR ${result.payout.reference_utr}.`
      );
      setWithdrawAmount("");
      void queryClient.invalidateQueries({ queryKey: ["wallet"] });
      void queryClient.invalidateQueries({ queryKey: ["transactions"] });
      void queryClient.invalidateQueries({ queryKey: ["payouts"] });
      void queryClient.invalidateQueries({ queryKey: ["wallet-statement"] });
      void queryClient.invalidateQueries({ queryKey: ["worker-profile"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const csvMutation = useMutation({
    mutationFn: () => walletApi.statementCsv(statementDays),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `taskflex-statement-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      toast.success("Statement downloaded as CSV.");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (walletQuery.isLoading) return <PageLoader label="Loading wallet…" />;

  const wallet = walletQuery.data;
  const balance = wallet?.balance ?? 0;
  const numericWithdraw = Number(withdrawAmount);
  const withdrawValid =
    Number.isFinite(numericWithdraw) &&
    numericWithdraw >= 100 &&
    numericWithdraw <= balance &&
    UPI_PATTERN.test(effectiveUpi);
  const statement = statementQuery.data;
  const totals = useMemo(() => {
    if (!statement) return [] as { category: StatementCategory; value: number }[];
    return STATEMENT_ORDER.map((category) => ({ category, value: statement.categories[category] ?? 0 }));
  }, [statement]);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Wallet</h1>
        <p className="mt-0.5 text-sm text-slate-500">Every rupee in and out of your TaskFlex account, fully traceable.</p>
      </div>

      {wallet && (
        <div className="overflow-hidden rounded-2xl bg-gradient-to-br from-primary-600 to-primary-800 p-6 text-white shadow-lg">
          <div className="flex items-center justify-between">
            <p className="flex items-center gap-2 text-sm font-medium text-primary-100">
              <WalletIcon className="h-4 w-4" aria-hidden /> Available balance
            </p>
            <span className="rounded-full bg-white/15 px-2.5 py-0.5 text-xs font-medium">Escrow-secured balance</span>
          </div>
          <p className="mt-2 text-4xl font-bold tracking-tight">{formatMoney(wallet.balance, wallet.currency)}</p>
          <div className="mt-5 grid grid-cols-2 gap-4 border-t border-white/15 pt-4 text-sm">
            <div>
              <p className="text-primary-200">Total in</p>
              <p className="mt-0.5 font-semibold">{formatMoney(wallet.total_earned, wallet.currency)}</p>
            </div>
            <div>
              <p className="text-primary-200">Total out</p>
              <p className="mt-0.5 font-semibold">{formatMoney(wallet.total_spent, wallet.currency)}</p>
            </div>
          </div>
        </div>
      )}

      {isWorker && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
              <Landmark className="h-4 w-4" aria-hidden /> UPI payout account
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Withdrawals are sent instantly to your UPI ID. Use the VPA format, e.g. <code>name@bank</code>.
            </p>
            <div className="mt-3 rounded-xl bg-slate-50 px-3 py-2 text-sm">
              {savedUpi ? (
                <span className="flex items-center gap-1.5 font-medium text-slate-800">
                  <CheckCircle2 className="h-4 w-4 text-emerald-500" aria-hidden /> {savedUpi}
                </span>
              ) : (
                <span className="text-slate-500">No UPI ID saved yet.</span>
              )}
            </div>
            <div className="mt-3 flex items-start gap-2">
              <div className="flex-1">
                <Field label="UPI ID" htmlFor="upi-id">
                  <Input
                    id="upi-id"
                    placeholder="yourname@okhdfcbank"
                    value={upiInput}
                    onChange={(e) => setUpiInput(e.target.value)}
                    error={upiInput.trim() && !UPI_PATTERN.test(upiInput.trim()) ? "Enter a valid UPI ID." : undefined}
                  />
                </Field>
              </div>
              <Button
                className="self-start"
                loading={upiMutation.isPending}
                disabled={!UPI_PATTERN.test(upiInput.trim())}
                onClick={() => upiMutation.mutate()}
              >
                Save
              </Button>
            </div>
          </Card>

          <Card>
            <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
              <IndianRupee className="h-4 w-4" aria-hidden /> Withdraw to UPI
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Minimum ₹100 per withdrawal. The amount is debited from your wallet atomically and a UTR is generated.
            </p>
            <div className="mt-3">
              <Field
                label="Amount"
                htmlFor="withdraw-amount"
                hint={`Available ${formatMoney(balance)}${effectiveUpi ? ` · to ${effectiveUpi}` : " · add a UPI ID first"}`}
              >
                <Input
                  id="withdraw-amount"
                  type="number"
                  min={100}
                  max={balance}
                  placeholder="1000"
                  value={withdrawAmount}
                  onChange={(e) => setWithdrawAmount(e.target.value)}
                  error={
                    withdrawAmount.trim() && Number(withdrawAmount) < 100
                      ? "Minimum withdrawal is ₹100."
                      : withdrawAmount.trim() && Number(withdrawAmount) > balance
                        ? "Amount exceeds your available balance."
                        : undefined
                  }
                />
              </Field>
            </div>
            <Button
              className="mt-3 w-full"
              loading={withdrawMutation.isPending}
              disabled={!withdrawValid}
              onClick={() => withdrawMutation.mutate()}
            >
              <IndianRupee className="h-4 w-4" aria-hidden /> Withdraw {withdrawAmount.trim() ? formatMoney(numericWithdraw) : ""}
            </Button>
            <div className="mt-2 flex gap-2">
              {[500, 1000, 2000].map((quick) => (
                <button
                  key={quick}
                  type="button"
                  disabled={quick > balance}
                  onClick={() => setWithdrawAmount(String(quick))}
                  className="flex-1 rounded-lg border border-slate-200 px-2 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  ₹{quick}
                </button>
              ))}
            </div>
            {lastPayout && (
              <div className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                <span className="font-semibold">Last payout:</span> {formatMoney(lastPayout.amount)} to {lastPayout.upi_id} ·
                UTR {lastPayout.reference_utr}
              </div>
            )}
          </Card>
        </div>
      )}

      {isWorker && (
        <Card>
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
            <ArrowUpRight className="h-4 w-4" aria-hidden /> Payout history
          </h2>
          {payoutsQuery.isLoading ? (
            <div className="mt-3">
              <SkeletonList rows={2} />
            </div>
          ) : (payoutsQuery.data?.items.length ?? 0) === 0 ? (
            <EmptyState
              icon="🏦"
              title="No withdrawals yet"
              description="Once your wallet has ₹100 or more, withdraw to UPI and the payout will be listed here with its UTR."
            />
          ) : (
            <ul className="mt-3 divide-y divide-slate-100">
              {payoutsQuery.data!.items.map((payout) => (
                <li key={payout.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-800">
                      {formatMoney(payout.amount)} → {payout.upi_id}
                    </p>
                    <p className="text-xs text-slate-400">
                      UTR {payout.reference_utr} · {formatDateTime(payout.created_at)}
                    </p>
                  </div>
                  <Badge
                    className={
                      payout.status === "COMPLETED"
                        ? "bg-emerald-100 text-emerald-800"
                        : payout.status === "FAILED"
                          ? "bg-red-100 text-red-700"
                          : "bg-amber-100 text-amber-800"
                    }
                  >
                    {payout.status.toLowerCase()}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {isWorker && (
        <Card>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
                <ReceiptText className="h-4 w-4" aria-hidden /> Earnings statement
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Categorised breakdown for the selected period. Tips and quest bonuses are always commission-free.
              </p>
            </div>
            <div className="flex items-end gap-2">
              <Field label="Period" htmlFor="statement-days">
                <select
                  id="statement-days"
                  className="input appearance-none pr-8"
                  value={statementDays}
                  onChange={(e) => setStatementDays(Number(e.target.value))}
                >
                  <option value={7}>Last 7 days</option>
                  <option value={30}>Last 30 days</option>
                  <option value={90}>Last 90 days</option>
                </select>
              </Field>
              <Button
                variant="secondary"
                loading={csvMutation.isPending}
                onClick={() => csvMutation.mutate()}
              >
                <Download className="h-4 w-4" aria-hidden /> CSV
              </Button>
            </div>
          </div>

          {statementQuery.isLoading ? (
            <div className="mt-4">
              <SkeletonList rows={3} />
            </div>
          ) : statementQuery.isError || !statement ? (
            <EmptyState icon="📄" title="Statement unavailable" description={errorMessage(statementQuery.error)} />
          ) : (
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <div>
                <dl className="divide-y divide-slate-100">
                  {totals.map(({ category, value }) => (
                    <div key={category} className="flex items-center justify-between py-2 text-sm">
                      <dt className="text-slate-600">{STATEMENT_CATEGORY_LABELS[category] ?? category}</dt>
                      <dd className="font-semibold text-slate-900">{formatMoney(value, statement.currency)}</dd>
                    </div>
                  ))}
                  <div className="flex items-center justify-between py-2 text-sm">
                    <dt className="text-slate-600">Platform fees</dt>
                    <dd className="font-semibold text-red-500">−{formatMoney(statement.platform_fees, statement.currency)}</dd>
                  </div>
                  <div className="flex items-center justify-between py-2 text-sm">
                    <dt className="text-slate-600">Withdrawals</dt>
                    <dd className="font-semibold text-slate-900">−{formatMoney(statement.withdrawn, statement.currency)}</dd>
                  </div>
                  <div className="flex items-center justify-between py-2 text-sm font-bold">
                    <dt className="text-slate-900">Net earnings</dt>
                    <dd className="text-emerald-600">{formatMoney(statement.net_earnings, statement.currency)}</dd>
                  </div>
                </dl>
                <p className="mt-2 text-xs text-slate-400">
                  {formatDate(statement.period.from)} – {formatDate(statement.period.to)} · {statement.transaction_count}{" "}
                  transactions · balance {formatMoney(statement.wallet_balance, statement.currency)}
                </p>
              </div>
              <div className="max-h-72 overflow-y-auto rounded-xl border border-slate-100">
                {statement.transactions.length === 0 ? (
                  <p className="p-4 text-sm text-slate-500">No ledger entries in this period.</p>
                ) : (
                  <ul className="divide-y divide-slate-100">
                    {statement.transactions.map((entry) => (
                      <li key={entry.id} className="flex items-center justify-between gap-2 px-3 py-2">
                        <div className="min-w-0">
                          <p className="truncate text-xs font-medium text-slate-800">{entry.description}</p>
                          <p className="text-[11px] text-slate-400">
                            {STATEMENT_CATEGORY_LABELS[entry.category] ?? entry.category} · {formatDate(entry.created_at)}
                          </p>
                        </div>
                        <span
                          className={cn(
                            "shrink-0 text-xs font-bold",
                            entry.amount >= 0 ? "text-emerald-600" : "text-red-500"
                          )}
                        >
                          {entry.amount >= 0 ? "+" : ""}
                          {formatMoney(entry.amount, entry.currency)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </Card>
      )}

      <Card>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Recent transactions</h2>
        {txnsQuery.isLoading ? (
          <div className="mt-4">
            <SkeletonList rows={4} />
          </div>
        ) : (txnsQuery.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            icon="🧾"
            title="No transactions yet"
            description="Once you confirm or complete tasks, payments and payouts will appear here."
          />
        ) : (
          <ul className="mt-4 divide-y divide-slate-100">
            {txnsQuery.data!.items.map((t) => {
              const meta = TXN_STYLES[t.type] ?? { label: t.type, positive: t.amount >= 0 };
              const positive = meta.positive;
              return (
                <li key={t.id} className="flex items-center gap-3 py-3">
                  <div
                    className={cn(
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
                      positive ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-500"
                    )}
                  >
                    {positive ? <ArrowDownLeft className="h-4 w-4" aria-hidden /> : <ArrowUpRight className="h-4 w-4" aria-hidden />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-slate-800">{t.description}</p>
                    <p className="text-xs text-slate-400">
                      {meta.label} · {formatDateTime(t.created_at)}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className={cn("text-sm font-bold", positive ? "text-emerald-600" : "text-red-500")}>
                      {positive ? "+" : ""}
                      {formatMoney(t.amount, t.currency)}
                    </p>
                    <p className="text-xs text-slate-400">bal. {formatMoney(t.balance_after, t.currency)}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}
