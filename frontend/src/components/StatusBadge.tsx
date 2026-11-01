import { Badge } from "@/components/ui";
import { TASK_STATUS_LABELS, TASK_STATUS_STYLES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { TaskStatus } from "@/types";

export function StatusBadge({ status, className }: { status: TaskStatus | string; className?: string }) {
  const style = TASK_STATUS_STYLES[status as TaskStatus] ?? "bg-slate-100 text-slate-600";
  const label = TASK_STATUS_LABELS[status as TaskStatus] ?? status;
  return <Badge className={cn(style, className)}>{label}</Badge>;
}
