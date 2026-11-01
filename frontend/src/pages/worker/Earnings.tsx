import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Crown, Gift, IndianRupee, TrendingUp, Wallet, Hourglass } from "lucide-react";

import { formatMoney, timeAgo } from "@/lib/utils";
import { TIER_ICONS, TIER_LABELS, TIER_STYLES, WS_EVENTS } from "@/lib/constants";
import { Badge, Card, EmptyState, PageLoader, Stat } from "@/components/ui";
import { usersApi } from "@/api/users";
import { workersApi } from "@/api/workers";
import { celebrate } from "@/lib/celebrate";
import { toast } from "@/stores/toast";
import { wsService } from "@/services/websocket";

export default function WorkerEarnings() {
  const queryClient = useQueryClient();
  const earningsQuery = useQuery({ queryKey: ["worker-earnings"], queryFn: () => workersApi.myEarnings() });
  const walletQuery = useQuery({ queryKey: ["wallet"], queryFn: () => usersApi.wallet() });
  const txnsQuery = useQuery({ queryKey: ["transactions"], queryFn: () => usersApi.transactions(1, 30) });
  const tierQuery = useQuery({ queryKey: ["worker-tier"], queryFn: () => workersApi.myTier() });

  useEffect(() => {
    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: ["worker-tier"] });
      void queryClient.invalidateQueries({ queryKey: ["worker-earnings"] });
      void queryClient.invalidateQueries({ queryKey: ["wallet"] });
      void queryClient.invalidateQueries({ queryKey: ["transactions"] });
    };
    const offQuest = wsService.on(WS_EVENTS.QUEST_COMPLETED, (frame) => {
      const data = frame.data as { title?: string; bonus_amount?: number };
      toast.success(
        `Quest complete${data.title ? `: ${data.title}` : ""} — ${formatMoney(data.bonus_amount ?? 0)} credited to your wallet!`
      );
      celebrate();
      refresh();
    });
    const offTier = wsService.on(WS_EVENTS.TIER_UPGRADED, (frame) => {
      const data = frame.data as { tier?: string; previous_tier?: string };
      toast.success(
        `Tier upgraded${data.tier ? ` to ${TIER_LABELS[data.tier] ?? data.tier}` : ""} — your commission rate just dropped!`
      );
      celebrate();
      refresh();
    });
    return () => {
      offQuest();
      offTier();
    };
  }, [queryClient]);

  if (earningsQuery.isLoading) return <PageLoader label="Crunching your numbers…" />;

  const e = earningsQuery.data;
  const wallet = walletQuery.data;
  const payouts = (txnsQuery.data?.items ?? []).filter((t) => t.type === "PAYOUT" || t.type === "CREDIT");
  const tier = tierQuery.data;
  const nextRule = tier?.next_tier_rule ?? null;
  const nextTierProgress =
    tier && nextRule
      ? Math.min(100, Math.round((tier.stats.completed_30d / Math.max(nextRule.min_tasks, 1)) * 100))
      : null;

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Earnings</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          TaskFlex keeps a small platform commission on each task — everything else is yours.
        </p>
      </div>

      {e && (
        <>
          <div className="overflow-hidden rounded-2xl bg-gradient-to-br from-accent-500 to-accent-700 p-6 text-white shadow-lg">
            <p className="text-sm font-medium text-accent-100">Total lifetime earnings</p>
            <p className="mt-1 text-4xl font-bold tracking-tight">{formatMoney(e.total_earnings, e.currency)}</p>
            <div className="mt-5 grid grid-cols-3 gap-4 border-t border-white/15 pt-4 text-sm">
              <div>
                <p className="text-accent-100">Today</p>
                <p className="mt-0.5 font-semibold">{formatMoney(e.today_earnings, e.currency)}</p>
              </div>
              <div>
                <p className="text-accent-100">This week</p>
                <p className="mt-0.5 font-semibold">{formatMoney(e.week_earnings, e.currency)}</p>
              </div>
              <div>
                <p className="text-accent-100">This month</p>
                <p className="mt-0.5 font-semibold">{formatMoney(e.month_earnings, e.currency)}</p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Stat label="Tasks completed" value={e.completed_tasks} icon={<TrendingUp className="h-5 w-5" />} />
            <Stat
              label="Pending clearance"
              value={formatMoney(e.pending_clearance, e.currency)}
              sub="Awaiting customer confirmation"
              icon={<Hourglass className="h-5 w-5" />}
            />
            <Stat
              label="Wallet balance"
              value={wallet ? formatMoney(wallet.balance, wallet.currency) : "—"}
              sub="Available for payout"
              icon={<Wallet className="h-5 w-5" />}
            />
          </div>
        </>
      )}

      {tier && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
                  <Crown className="h-4 w-4" aria-hidden /> Your tier
                </h2>
                <p className="mt-2 flex items-center gap-2">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-bold ${TIER_STYLES[tier.tier] ?? ""}`}
                  >
                    <span aria-hidden>{TIER_ICONS[tier.tier] ?? "🏅"}</span>
                    {TIER_LABELS[tier.tier] ?? tier.tier}
                  </span>
                  <span className="text-sm text-slate-500">
                    {(tier.commission_rate * 100).toFixed(tier.commission_rate * 100 % 1 === 0 ? 0 : 1)}% platform fee
                  </span>
                </p>
              </div>
              <Badge className="bg-emerald-50 text-emerald-700">
                {tier.tier === "PLATINUM" ? "+0.10" : tier.tier === "GOLD" ? "+0.05" : "no"} matching boost
              </Badge>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-lg bg-slate-50 px-3 py-2">
                <p className="text-[11px] uppercase tracking-wide text-slate-400">Tasks (30d)</p>
                <p className="text-lg font-bold text-slate-900">{tier.stats.completed_30d}</p>
              </div>
              <div className="rounded-lg bg-slate-50 px-3 py-2">
                <p className="text-[11px] uppercase tracking-wide text-slate-400">Rating</p>
                <p className="text-lg font-bold text-slate-900">
                  {tier.stats.rating_count_30d > 0 ? tier.stats.rating.toFixed(2) : "—"}
                </p>
              </div>
              <div className="rounded-lg bg-slate-50 px-3 py-2">
                <p className="text-[11px] uppercase tracking-wide text-slate-400">Cancelled</p>
                <p className="text-lg font-bold text-slate-900">{tier.stats.cancelled_30d}</p>
              </div>
              <div className="rounded-lg bg-slate-50 px-3 py-2">
                <p className="text-[11px] uppercase tracking-wide text-slate-400">Cancel rate</p>
                <p className="text-lg font-bold text-slate-900">
                  {tier.stats.cancellation_rate.toFixed(1)}%
                </p>
              </div>
            </div>

            {nextRule && nextTierProgress !== null ? (
              <div className="mt-4 rounded-xl border border-dashed border-slate-200 p-3">
                <p className="text-sm font-semibold text-slate-800">
                  Next tier: {TIER_ICONS[tier.next_tier ?? ""] ?? ""} {TIER_LABELS[tier.next_tier ?? ""] ?? tier.next_tier} ·{" "}
                  {(nextRule.commission_rate * 100).toFixed(1)}% fee
                </p>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full rounded-full bg-primary-500 transition-all" style={{ width: `${nextTierProgress}%` }} />
                </div>
                <p className="mt-1.5 text-xs text-slate-500">
                  {tier.stats.completed_30d}/{nextRule.min_tasks} tasks · rating ≥ {nextRule.min_rating.toFixed(1)} ·
                  cancellation rate &lt; {(nextRule.max_cancel_rate * 100).toFixed(0)}% (rolling 30 days)
                </p>
              </div>
            ) : (
              <p className="mt-4 rounded-xl bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-800">
                You're at the top tier — the lowest commission TaskFlex offers.
              </p>
            )}
          </Card>

          <Card>
            <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
              <Gift className="h-4 w-4" aria-hidden /> Today's quests
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Complete tasks today to unlock automatic cash bonuses. Rewards land in your wallet the moment a target is hit.
            </p>
            {tier.quests.length === 0 ? (
              <p className="mt-3 text-sm text-slate-500">No quests are running today — check back tomorrow.</p>
            ) : (
              <ul className="mt-3 space-y-3">
                {tier.quests.map((quest) => (
                  <li key={quest.id} className="rounded-xl border border-slate-200 p-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-slate-900">{quest.title}</p>
                        <p className="text-xs text-slate-500">{quest.description}</p>
                      </div>
                      <Badge
                        className={
                          quest.is_claimed
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-amber-50 text-amber-800"
                        }
                      >
                        {quest.is_claimed ? "Bonus credited" : `+${formatMoney(quest.bonus_amount)}`}
                      </Badge>
                    </div>
                    <div className="mt-2 flex items-center gap-2">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className={`h-full rounded-full transition-all ${quest.is_claimed ? "bg-emerald-500" : "bg-amber-500"}`}
                          style={{ width: `${Math.min(100, quest.progress_percent)}%` }}
                        />
                      </div>
                      <span className="shrink-0 text-xs font-semibold tabular-nums text-slate-600">
                        {quest.completed_count}/{quest.target_tasks_count}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}

      <Card>
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
          <IndianRupee className="h-4 w-4" aria-hidden /> Payout history
        </h2>
        {(txnsQuery.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            icon="🧾"
            title="No payouts yet"
            description="Complete your first task — the payout lands in your wallet the moment the customer confirms."
          />
        ) : (
          <ul className="mt-4 divide-y divide-slate-100">
            {payouts.map((t) => (
              <li key={t.id} className="flex items-center justify-between py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-800">{t.description}</p>
                  <p className="text-xs text-slate-400">{timeAgo(t.created_at)}</p>
                </div>
                <p className="shrink-0 text-sm font-bold text-emerald-600">+{formatMoney(t.amount, t.currency)}</p>
              </li>
            ))}
            {payouts.length === 0 && (
              <li className="py-3 text-sm text-slate-400">No credit transactions in your recent history.</li>
            )}
          </ul>
        )}
      </Card>
    </div>
  );
}
