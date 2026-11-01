import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, Users as UsersIcon } from "lucide-react";
import { adminApi } from "@/api/admin";
import { Avatar, Badge, Button, Card, EmptyState, Input, PageLoader, Select } from "@/components/ui";
import { errorMessage } from "@/lib/utils";
import { toast } from "@/stores/toast";
import type { AdminUserRow } from "@/types";

const ROLES = ["", "CUSTOMER", "WORKER", "ADMIN"];

function RoleBadge({ role }: { role: string }) {
  const styles: Record<string, string> = {
    CUSTOMER: "bg-sky-100 text-sky-700",
    WORKER: "bg-primary-100 text-primary-700",
    ADMIN: "bg-purple-100 text-purple-700",
  };
  return <Badge className={styles[role] ?? "bg-slate-100 text-slate-600"}>{role.toLowerCase()}</Badge>;
}

export default function Users() {
  const qc = useQueryClient();
  const [role, setRole] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);

  const users = useQuery({
    queryKey: ["admin-users", role, query, status, page],
    queryFn: () =>
      adminApi.users({
        role: role || undefined,
        search: query || undefined,
        is_active: status === "" ? undefined : status === "active",
        page,
        page_size: 20,
      }),
  });

  const toggleActive = useMutation({
    mutationFn: (u: AdminUserRow) => adminApi.setUserActive(u.id, !u.is_active),
    onSuccess: (updated) => {
      toast.success(updated.is_active ? "Account reactivated." : "Account deactivated.");
      void qc.invalidateQueries({ queryKey: ["admin-users"] });
      void qc.invalidateQueries({ queryKey: ["admin-dashboard"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const rows = users.data?.items ?? [];
  const total = users.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 20));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Users</h1>
        <p className="text-sm text-slate-500">{total} accounts registered</p>
      </div>

      <Card className="flex flex-wrap items-center gap-3 p-4">
        <form
          className="relative flex-1 min-w-56"
          onSubmit={(e) => {
            e.preventDefault();
            setPage(1);
            setQuery(search);
          }}
        >
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, email or phone…"
            className="pl-9"
          />
        </form>
        <Select
          value={role}
          onChange={(e) => {
            setRole(e.target.value);
            setPage(1);
          }}
          className="w-40"
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r === "" ? "All roles" : r.toLowerCase()}
            </option>
          ))}
        </Select>
        <Select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
          className="w-40"
        >
          <option value="">Any status</option>
          <option value="active">Active</option>
          <option value="inactive">Deactivated</option>
        </Select>
      </Card>

      {users.isLoading ? (
        <PageLoader />
      ) : rows.length === 0 ? (
        <EmptyState icon="👥" title="No users found" description="Try clearing the filters or search." />
      ) : (
        <div className="space-y-3">
          {rows.map((u) => (
            <Card key={u.id} className="flex flex-wrap items-center gap-4 p-4">
              <Avatar name={u.full_name} url={null} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="truncate font-semibold text-slate-800">{u.full_name}</p>
                  <RoleBadge role={u.role} />
                  {u.worker && u.worker.is_verified && <Badge className="bg-emerald-100 text-emerald-700">verified runner</Badge>}
                  {!u.is_active && <Badge className="bg-red-100 text-red-700">deactivated</Badge>}
                </div>
                <p className="truncate text-xs text-slate-500">
                  {u.email}
                  {u.phone ? ` · ${u.phone}` : ""}
                  {u.city ? ` · ${u.city}` : ""}
                  {u.worker ? ` · ${u.worker.rating_average.toFixed(1)}★ · ₹${Math.round(u.worker.total_earnings).toLocaleString()} earned` : ""}
                </p>
                <p className="text-[11px] text-slate-400">Joined {new Date(u.created_at).toLocaleDateString()}</p>
              </div>
              {u.role !== "ADMIN" && (
                <Button
                  variant={u.is_active ? "danger" : "secondary"}
                  loading={toggleActive.isPending && toggleActive.variables?.id === u.id}
                  onClick={() => toggleActive.mutate(u)}
                  className="text-xs"
                >
                  {u.is_active ? "Deactivate" : "Reactivate"}
                </Button>
              )}
            </Card>
          ))}
        </div>
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

      <div className="flex items-center gap-2 text-xs text-slate-400">
        <UsersIcon className="h-3.5 w-3.5" />
        Deactivating an account blocks sign-in immediately; workers can no longer receive offers.
      </div>
    </div>
  );
}
