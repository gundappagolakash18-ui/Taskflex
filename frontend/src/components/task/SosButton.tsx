import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Siren } from "lucide-react";

import { errorMessage } from "@/lib/utils";
import { Button, Card, Field, Modal, Textarea } from "@/components/ui";
import { tasksApi } from "@/api/tasks";
import { toast } from "@/stores/toast";

function currentPosition(): Promise<{ latitude: number; longitude: number } | null> {
  if (!("geolocation" in navigator)) return Promise.resolve(null);
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (position) => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 2500, maximumAge: 30_000 }
    );
  });
}

export function SosButton({ taskId, status }: { taskId: string; status: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");

  const mutation = useMutation({
    mutationFn: async () => {
      const position = await currentPosition();
      return tasksApi.triggerSos(taskId, {
        latitude: position?.latitude ?? null,
        longitude: position?.longitude ?? null,
        message: message.trim() || null,
      });
    },
    onSuccess: () => {
      toast.success("Emergency alert raised — our support team has been paged.");
      setOpen(false);
      setMessage("");
      void queryClient.invalidateQueries({ queryKey: ["task", taskId] });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (status === "EMERGENCY_ALERT") {
    return (
      <Card className="border-red-300 bg-red-50">
        <p className="flex items-center gap-2 text-sm font-bold text-red-800">
          <Siren className="h-5 w-5" aria-hidden /> Emergency alert active
        </p>
        <p className="mt-1 text-sm text-red-700">
          Support has been paged and the last known GPS positions are frozen as evidence. If anyone is in immediate
          danger, call local emergency services now.
        </p>
      </Card>
    );
  }

  return (
    <>
      <Button variant="danger" className="w-full" onClick={() => setOpen(true)}>
        <Siren className="mr-1.5 h-4 w-4" aria-hidden /> Emergency SOS
      </Button>

      <Modal open={open} onClose={() => setOpen(false)} title="Raise an emergency alert?">
        <div className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
          Use this only for a real safety emergency. It flips the task to <strong>EMERGENCY_ALERT</strong>, freezes the
          last 20 GPS fixes as evidence, and notifies every admin immediately.
        </div>
        <div className="mt-4">
          <Field label="What is happening? (optional)" htmlFor="sos-message" hint="Shared with the safety team only.">
            <Textarea
              id="sos-message"
              rows={3}
              maxLength={500}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="e.g. I feel unsafe at this location."
            />
          </Field>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          We will attach your device's last known position if the browser allows it.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button variant="danger" loading={mutation.isPending} onClick={() => mutation.mutate()}>
            <Siren className="mr-1.5 h-4 w-4" aria-hidden /> Raise alert
          </Button>
        </div>
      </Modal>
    </>
  );
}
