import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";

import { Button, Field, Input, Modal } from "@/components/ui";

interface OtpEntryModalProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  loading?: boolean;
  error?: string | null;
  onClose: () => void;
  onSubmit: (otp: string) => void;
}

export function OtpEntryModal({
  open,
  title,
  description,
  confirmLabel,
  loading = false,
  error,
  onClose,
  onSubmit,
}: OtpEntryModalProps) {
  const [otp, setOtp] = useState("");

  useEffect(() => {
    if (open) setOtp("");
  }, [open]);

  const valid = /^\d{4}$/.test(otp);

  return (
    <Modal open={open} onClose={onClose} title={title}>
      <p className="flex items-start gap-2 text-sm text-slate-600">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary-600" aria-hidden />
        {description}
      </p>
      <div className="mt-4">
        <Field label="4-digit code" htmlFor="otp-code">
          <Input
            id="otp-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={4}
            placeholder="0000"
            value={otp}
            onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 4))}
            className="text-center text-2xl font-bold tracking-[0.5em]"
            error={error ?? undefined}
            autoFocus
          />
        </Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button loading={loading} disabled={!valid} onClick={() => onSubmit(otp)}>
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
