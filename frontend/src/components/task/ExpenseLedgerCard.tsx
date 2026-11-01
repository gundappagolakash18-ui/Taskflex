import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Paperclip, Plus, Receipt, X } from "lucide-react";

import {
  CLOSED_TASK_STATUSES,
  EXPENSE_CATEGORY_LABELS,
  EXPENSE_EDITABLE_STATUSES,
  EXPENSE_STATUS_LABELS,
  EXPENSE_STATUS_STYLES,
} from "@/lib/constants";
import { errorMessage, formatDateTime, formatMoney } from "@/lib/utils";
import { Badge, Button, Card, Field, Input, Select, Textarea } from "@/components/ui";
import { PrivateFileButton } from "@/components/task/PrivateFile";
import { tasksApi } from "@/api/tasks";
import { toast } from "@/stores/toast";
import type { ExpenseCategory, Task } from "@/types";

const CATEGORY_OPTIONS = Object.entries(EXPENSE_CATEGORY_LABELS);

export function ExpenseLedgerCard({
  task,
  isWorker,
  isCustomer,
}: {
  task: Task;
  isWorker: boolean;
  isCustomer: boolean;
}) {
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState<ExpenseCategory>("OTHER");
  const [description, setDescription] = useState("");
  const [receipt, setReceipt] = useState<File | null>(null);
  const [decidingId, setDecidingId] = useState<string | null>(null);

  const expenses = task.expenses ?? [];
  const totals = task.expense_totals;
  const canAdd = isWorker && EXPENSE_EDITABLE_STATUSES.includes(task.status);
  const canDecide =
    isCustomer && !CLOSED_TASK_STATUSES.includes(task.status) && task.status !== "COMPLETED";
  const currency = task.currency || "INR";

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["task", task.id] });
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
  };

  const addMutation = useMutation({
    mutationFn: () =>
      tasksApi.addExpense(task.id, {
        amount: Number(amount),
        category,
        description: description.trim(),
        receipt,
      }),
    onSuccess: () => {
      toast.success("Expense submitted — your customer has been asked to approve it.");
      setFormOpen(false);
      setAmount("");
      setCategory("OTHER");
      setDescription("");
      setReceipt(null);
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const decideMutation = useMutation({
    mutationFn: ({ expenseId, approve }: { expenseId: string; approve: boolean }) =>
      approve ? tasksApi.approveExpense(task.id, expenseId) : tasksApi.rejectExpense(task.id, expenseId),
    onMutate: ({ expenseId }) => setDecidingId(expenseId),
    onSuccess: (_data, variables) => {
      toast.success(variables.approve ? "Expense approved — added to the runner's payout." : "Expense rejected.");
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => setDecidingId(null),
  });

  if (!canAdd && expenses.length === 0) return null;

  const valid = Number(amount) > 0 && description.trim().length >= 5;

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-slate-400">
          <Receipt className="h-4 w-4" aria-hidden /> Incidental expenses
        </h2>
        {totals && totals.count > 0 && (
          <div className="flex flex-wrap gap-2 text-[11px]">
            <span className="rounded-full bg-amber-50 px-2 py-0.5 font-medium text-amber-800">
              {formatMoney(totals.pending_total, currency)} pending
            </span>
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700">
              {formatMoney(totals.worker_reimbursement_total, currency)} reimbursable
            </span>
          </div>
        )}
      </div>

      {expenses.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">No incidental expenses claimed yet.</p>
      ) : (
        <ul className="mt-3 divide-y divide-slate-100">
          {expenses.map((expense) => (
            <li key={expense.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-800">
                  {formatMoney(expense.amount, currency)}
                  <span className="text-xs font-normal text-slate-400">
                    {EXPENSE_CATEGORY_LABELS[expense.category] ?? expense.category}
                  </span>
                  <Badge className={EXPENSE_STATUS_STYLES[expense.status] ?? "bg-slate-100 text-slate-600"}>
                    {EXPENSE_STATUS_LABELS[expense.status] ?? expense.status}
                  </Badge>
                </p>
                <p className="mt-0.5 text-sm text-slate-600">{expense.description}</p>
                <div className="mt-1 flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
                  <span>{formatDateTime(expense.created_at)}</span>
                  {expense.receipt_available && (
                    <PrivateFileButton
                      fetcher={() => tasksApi.receiptFile(task.id, expense.id)}
                      label="View receipt"
                    />
                  )}
                </div>
                {expense.decision_note && (
                  <p className="mt-1 text-xs text-slate-500">Customer note: {expense.decision_note}</p>
                )}
              </div>
              {canDecide && expense.status === "PENDING_APPROVAL" && (
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    loading={decidingId === expense.id}
                    onClick={() => decideMutation.mutate({ expenseId: expense.id, approve: true })}
                  >
                    <Check className="mr-1 h-3.5 w-3.5" aria-hidden /> Approve
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={decidingId === expense.id}
                    onClick={() => decideMutation.mutate({ expenseId: expense.id, approve: false })}
                  >
                    <X className="mr-1 h-3.5 w-3.5" aria-hidden /> Reject
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {canAdd && (
        <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4">
          {formOpen ? (
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (valid) addMutation.mutate();
              }}
            >
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Amount (₹)" htmlFor="expense-amount">
                  <Input
                    id="expense-amount"
                    type="number"
                    min={1}
                    step="0.01"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    placeholder="e.g. 50"
                  />
                </Field>
                <Field label="Category" htmlFor="expense-category">
                  <Select
                    id="expense-category"
                    value={category}
                    onChange={(e) => setCategory(e.target.value as ExpenseCategory)}
                  >
                    {CATEGORY_OPTIONS.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              <Field label="What did you pay for?" htmlFor="expense-description" hint="At least 5 characters. The customer sees this.">
                <Textarea
                  id="expense-description"
                  rows={2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  maxLength={500}
                  placeholder="e.g. ₹50 parking fee at the court complex."
                />
              </Field>
              <Field label="Receipt (optional)" htmlFor="expense-receipt" hint="JPEG, PNG, WebP or PDF.">
                <input
                  id="expense-receipt"
                  type="file"
                  accept="image/jpeg,image/png,image/webp,application/pdf"
                  className="block w-full text-xs text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:bg-white file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-slate-700"
                  onChange={(e) => setReceipt(e.target.files?.[0] ?? null)}
                />
              </Field>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setFormOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" loading={addMutation.isPending} disabled={!valid}>
                  Submit expense
                </Button>
              </div>
            </form>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="flex items-center gap-1.5 text-sm font-medium text-slate-800">
                  <Paperclip className="h-4 w-4 text-primary-600" aria-hidden /> Paid for something on the job?
                </p>
                <p className="mt-0.5 text-xs text-slate-500">
                  Log it here with a receipt. Approved amounts are reimbursed with your payout at completion.
                </p>
              </div>
              <Button variant="secondary" onClick={() => setFormOpen(true)}>
                <Plus className="mr-1.5 h-4 w-4" aria-hidden /> Add expense
              </Button>
            </div>
          )}
        </div>
      )}

      {isCustomer && !canDecide && expenses.some((e) => e.status === "PENDING_APPROVAL") && (
        <p className="mt-3 text-xs text-slate-500">This task is closed, so pending expenses can no longer be decided.</p>
      )}
    </Card>
  );
}
