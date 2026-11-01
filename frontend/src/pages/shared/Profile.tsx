import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, MapPin, Pin, Trash2 } from "lucide-react";

import { cn, errorMessage } from "@/lib/utils";
import { Avatar, Badge, Button, Card, Field, Input, PageLoader } from "@/components/ui";
import { locationApi } from "@/api/location";
import { usersApi } from "@/api/users";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";
import type { UserRole } from "@/types";

const ROLE_LABELS: Record<UserRole, string> = {
  CUSTOMER: "Customer",
  WORKER: "Runner",
  ADMIN: "Administrator",
};

function SavedLocations() {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState("");
  const [address, setAddress] = useState("");
  const [coords, setCoords] = useState<{ lat: number; lng: number; display: string } | null>(null);

  const locationsQuery = useQuery({ queryKey: ["locations"], queryFn: () => usersApi.locations() });

  const pinMutation = useMutation({
    mutationFn: () => locationApi.geocode(address),
    onSuccess: (result) => {
      if (!result) {
        toast.error("Couldn't find that address. Try adding the area or city.");
        return;
      }
      setCoords({ lat: result.latitude, lng: result.longitude, display: result.display_name });
      toast.success("Address located.");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      usersApi.createLocation({
        label: label.trim(),
        address: address.trim(),
        latitude: coords!.lat,
        longitude: coords!.lng,
      }),
    onSuccess: () => {
      toast.success("Location saved.");
      setLabel("");
      setAddress("");
      setCoords(null);
      void queryClient.invalidateQueries({ queryKey: ["locations"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => usersApi.deleteLocation(id),
    onSuccess: () => {
      toast.info("Location removed.");
      void queryClient.invalidateQueries({ queryKey: ["locations"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  return (
    <Card>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Saved places</h2>
      <p className="mt-1 text-sm text-slate-500">Quick-pick locations when you create errands.</p>

      {locationsQuery.isLoading ? (
        <p className="mt-4 text-sm text-slate-400">Loading…</p>
      ) : (
        <ul className="mt-4 space-y-2">
          {(locationsQuery.data ?? []).map((loc) => (
            <li key={loc.id} className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-2.5">
              <MapPin className="h-4 w-4 shrink-0 text-primary-600" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-800">
                  {loc.label}
                  {loc.is_default && <Badge className="ml-2 bg-primary-100 text-primary-700">default</Badge>}
                </p>
                <p className="truncate text-xs text-slate-500">{loc.address}</p>
              </div>
              <button
                type="button"
                onClick={() => deleteMutation.mutate(loc.id)}
                disabled={deleteMutation.isPending}
                className="rounded-lg p-1.5 text-slate-400 transition hover:bg-red-50 hover:text-red-500"
                aria-label={`Delete ${loc.label}`}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </button>
            </li>
          ))}
          {(locationsQuery.data ?? []).length === 0 && (
            <li className="text-sm text-slate-400">No saved places yet.</li>
          )}
        </ul>
      )}

      <div className="mt-5 space-y-3 border-t border-slate-100 pt-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Label" htmlFor="loc-label">
            <Input id="loc-label" placeholder="Home, Office…" value={label} maxLength={50} onChange={(e) => setLabel(e.target.value)} />
          </Field>
          <Field label="Address" htmlFor="loc-address">
            <Input id="loc-address" placeholder="Street, area, city" value={address} onChange={(e) => setAddress(e.target.value)} />
          </Field>
        </div>
        {coords && (
          <p className="flex items-center gap-1.5 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
            <Check className="h-3.5 w-3.5" aria-hidden /> {coords.display} ({coords.lat.toFixed(4)}, {coords.lng.toFixed(4)})
          </p>
        )}
        <div className="flex gap-2">
          <Button
            variant="secondary"
            loading={pinMutation.isPending}
            disabled={address.trim().length < 4}
            onClick={() => pinMutation.mutate()}
          >
            <Pin className="mr-1.5 h-4 w-4" aria-hidden /> Locate
          </Button>
          <Button
            loading={createMutation.isPending}
            disabled={!coords || label.trim().length < 2}
            onClick={() => createMutation.mutate()}
          >
            Save place
          </Button>
        </div>
      </div>
    </Card>
  );
}

export default function Profile() {
  const { user, setUser } = useAuthStore();
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [phone, setPhone] = useState(user?.phone ?? "");
  const [city, setCity] = useState(user?.city ?? "");

  const saveMutation = useMutation({
    mutationFn: () =>
      usersApi.updateMe({
        full_name: fullName.trim(),
        phone: phone.trim(),
        city: city.trim() || undefined,
      }),
    onSuccess: (updated) => {
      setUser(updated);
      toast.success("Profile updated.");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (!user) return <PageLoader />;

  const dirty =
    fullName.trim() !== user.full_name || phone.trim() !== user.phone || city.trim() !== (user.city ?? "");

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Profile</h1>
        <p className="mt-0.5 text-sm text-slate-500">Your account details as they appear to the people you work with.</p>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <div className="flex items-center gap-4">
            <Avatar name={user.full_name} url={user.avatar_url} size="lg" />
            <div className="min-w-0">
              <p className="truncate text-base font-semibold text-slate-900">{user.full_name}</p>
              <p className="truncate text-sm text-slate-500">{user.email}</p>
              <div className="mt-1.5 flex items-center gap-2">
                <Badge className="bg-primary-50 text-primary-700">{ROLE_LABELS[user.role]}</Badge>
                <Badge className={cn(user.is_email_verified ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700")}>
                  {user.is_email_verified ? "email verified" : "email unverified"}
                </Badge>
              </div>
            </div>
          </div>

          <div className="mt-5 space-y-3 border-t border-slate-100 pt-4">
            <Field label="Full name" htmlFor="profile-name">
              <Input id="profile-name" value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={120} />
            </Field>
            <Field label="Phone" htmlFor="profile-phone" hint="Used for task coordination. Never shown publicly.">
              <Input id="profile-phone" value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={20} />
            </Field>
            <Field label="City" htmlFor="profile-city">
              <Input id="profile-city" value={city} placeholder="e.g. Bengaluru" onChange={(e) => setCity(e.target.value)} maxLength={80} />
            </Field>
            <Button loading={saveMutation.isPending} disabled={!dirty || fullName.trim().length < 2} onClick={() => saveMutation.mutate()}>
              Save changes
            </Button>
          </div>
        </Card>

        <SavedLocations />
      </div>
    </div>
  );
}
