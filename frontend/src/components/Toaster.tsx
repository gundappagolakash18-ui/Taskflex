import { cn } from "@/lib/utils";
import { useToastStore } from "@/stores/toast";
import { CheckCircle2, Info, XCircle } from "lucide-react";

export function Toaster() {
  const { toasts, dismiss } = useToastStore();
  return (
    <div className="pointer-events-none fixed inset-x-0 top-3 z-[100] flex flex-col items-center gap-2 px-3">
      {toasts.map((t) => (
        <button
          key={t.id}
          onClick={() => dismiss(t.id)}
          className={cn(
            "pointer-events-auto flex w-full max-w-md items-start gap-2.5 rounded-xl px-4 py-3 text-left text-sm shadow-lg animate-slide-up",
            t.kind === "success" && "bg-emerald-600 text-white",
            t.kind === "error" && "bg-red-600 text-white",
            t.kind === "info" && "bg-slate-900 text-white"
          )}
        >
          {t.kind === "success" && <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />}
          {t.kind === "error" && <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
          {t.kind === "info" && <Info className="mt-0.5 h-4 w-4 shrink-0" />}
          <span className="min-w-0 flex-1">{t.message}</span>
        </button>
      ))}
    </div>
  );
}
