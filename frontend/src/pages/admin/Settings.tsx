import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Save } from "lucide-react";
import { adminApi } from "@/api/admin";
import { Button, Card, Input, PageLoader } from "@/components/ui";
import { errorMessage } from "@/lib/utils";
import { toast } from "@/stores/toast";
import type { SettingRow } from "@/api/admin";

export default function Settings() {
  const qc = useQueryClient();
  const [values, setValues] = useState<Record<string, string>>({});
  const [original, setOriginal] = useState<Record<string, string>>({});

  const settings = useQuery({
    queryKey: ["admin-settings"],
    queryFn: () => adminApi.settings(),
  });

  useEffect(() => {
    if (settings.data) {
      const next: Record<string, string> = {};
      for (const row of settings.data) next[row.key] = String(row.value);
      setValues(next);
      setOriginal(next);
    }
  }, [settings.data]);

  const save = useMutation({
    mutationFn: (changed: Record<string, string>) => adminApi.updateSettings(changed),
    onSuccess: (result) => {
      toast.success(`${result.updated} setting${result.updated === 1 ? "" : "s"} saved.`);
      setOriginal(values);
      void qc.invalidateQueries({ queryKey: ["admin-settings"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (settings.isLoading) return <PageLoader />;

  const rows: SettingRow[] = settings.data ?? [];
  const changedKeys = rows.filter((r) => (values[r.key] ?? "") !== (original[r.key] ?? "")).map((r) => r.key);

  const update = (key: string, value: string) => setValues((prev) => ({ ...prev, [key]: value }));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Platform settings</h1>
        <p className="text-sm text-slate-500">
          These values drive commission, matching and budget validation across the platform.
        </p>
      </div>

      <div className="space-y-3">
        {rows.map((row) => (
          <Card key={row.key} className="flex flex-wrap items-center gap-4 p-4">
            <div className="min-w-0 flex-1">
              <p className="font-mono text-sm font-semibold text-slate-800">{row.key}</p>
              <p className="text-xs text-slate-500">{row.description ?? "No description"}</p>
            </div>
            <div className="w-full sm:w-56">
              {row.value_type === "bool" ? (
                <button
                  type="button"
                  onClick={() => update(row.key, (values[row.key] ?? "").toLowerCase() === "true" ? "false" : "true")}
                  className={
                    (values[row.key] ?? "").toLowerCase() === "true"
                      ? "flex w-full items-center justify-between rounded-lg bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700 ring-1 ring-emerald-300"
                      : "flex w-full items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm font-medium text-slate-500 ring-1 ring-slate-200"
                  }
                >
                  {(values[row.key] ?? "").toLowerCase() === "true" ? "Enabled" : "Disabled"}
                  <span
                    className={
                      "h-4 w-8 rounded-full p-0.5 transition-colors " +
                      ((values[row.key] ?? "").toLowerCase() === "true" ? "bg-emerald-500" : "bg-slate-300")
                    }
                  >
                    <span
                      className={
                        "block h-3 w-3 rounded-full bg-white transition-transform " +
                        ((values[row.key] ?? "").toLowerCase() === "true" ? "translate-x-4" : "")
                      }
                    />
                  </span>
                </button>
              ) : (
                <Input
                  type={row.value_type === "int" || row.value_type === "float" ? "number" : "text"}
                  step={row.value_type === "float" ? "0.1" : undefined}
                  min={0}
                  value={values[row.key] ?? ""}
                  onChange={(e) => update(row.key, e.target.value)}
                />
              )}
            </div>
          </Card>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          disabled={changedKeys.length === 0}
          loading={save.isPending}
          onClick={() => {
            const changed: Record<string, string> = {};
            for (const key of changedKeys) changed[key] = values[key] ?? "";
            save.mutate(changed);
          }}
        >
          <Save className="mr-2 h-4 w-4" /> Save changes ({changedKeys.length})
        </Button>
        <Button variant="ghost" disabled={changedKeys.length === 0} onClick={() => setValues(original)}>
          <RotateCcw className="mr-2 h-4 w-4" /> Discard
        </Button>
        <span className="text-xs text-slate-400">Commission and radius changes apply to new matches immediately.</span>
      </div>
    </div>
  );
}
