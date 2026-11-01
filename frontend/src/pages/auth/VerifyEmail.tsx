import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { authApi } from "@/api/auth";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";
import { errorMessage } from "@/lib/utils";
import { Button, Card, Field, Input } from "@/components/ui";

const RESEND_COOLDOWN_SECONDS = 60;

interface VerifyState {
  identifier?: string;
  email?: string;
}

export default function VerifyEmail() {
  const navigate = useNavigate();
  const location = useLocation();
  const setAuth = useAuthStore((s) => s.setAuth);
  const state = (location.state ?? {}) as VerifyState;

  const [identifier, setIdentifier] = useState(state.identifier ?? state.email ?? "");
  const [code, setCode] = useState("");
  const [serverError, setServerError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const isPhone = Boolean(identifier) && !identifier.includes("@");

  const codeRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (identifier) codeRef.current?.focus();
  }, [identifier]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setInterval(() => setCooldown((s) => (s <= 1 ? 0 : s - 1)), 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  function destinationFor(role: string) {
    if (role === "ADMIN") return "/admin";
    if (role === "WORKER") return "/worker";
    return "/app";
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setServerError(null);
    if (!identifier) {
      setServerError("Enter the email or phone number you registered with.");
      return;
    }
    setSubmitting(true);
    try {
      const result = await authApi.verifyEmail(identifier.trim(), code.trim());
      setAuth(result.user, result.tokens.access_token, result.tokens.refresh_token);
      toast.success("Email verified — welcome to TaskFlex!");
      navigate(destinationFor(result.user.role), { replace: true });
    } catch (error) {
      setServerError(errorMessage(error));
      setCode("");
      codeRef.current?.focus();
    } finally {
      setSubmitting(false);
    }
  }

  async function onResend() {
    setServerError(null);
    try {
      await authApi.resendOtp(identifier.trim());
      setCooldown(RESEND_COOLDOWN_SECONDS);
      toast.info("A new code is on its way.");
    } catch (error) {
      setServerError(errorMessage(error));
      const wait = errorMessage(error).match(/wait (\d+)s/);
      if (wait) setCooldown(Number(wait[1]));
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-md">
        <Link to="/" className="mb-6 flex items-center justify-center gap-2">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-600 text-lg font-black text-white">T</span>
          <span className="text-xl font-extrabold text-slate-900">
            Task<span className="text-primary-600">Flex</span>
          </span>
        </Link>

        <Card className="p-6">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-50 text-2xl" aria-hidden>
            ✉️
          </div>
          <h1 className="mt-3 text-xl font-bold text-slate-900">Verify your email</h1>
          <p className="mt-1 text-sm text-slate-500">
            {isPhone
              ? "We sent a 6-digit code to the email address linked to this phone number. Enter it below to activate your account."
              : (
                <>
                  We sent a 6-digit code to{identifier ? " " : " your email"}
                  {identifier && <span className="font-semibold text-slate-700">{identifier}</span>}. Enter it below
                  to activate your account.
                </>
              )}
          </p>

          <form onSubmit={onSubmit} className="mt-5 space-y-4" noValidate>
            <Field label="Email or phone" htmlFor="identifier">
              <Input
                id="identifier"
                type="text"
                autoComplete="username"
                placeholder="you@example.com or 98765 43210"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                disabled={Boolean(state.identifier ?? state.email)}
              />
            </Field>

            <Field label="Verification code" htmlFor="code">
              <Input
                id="code"
                ref={codeRef}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                placeholder="••••••"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                className="text-center text-2xl font-bold tracking-[0.6em]"
              />
            </Field>

            {serverError && (
              <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
                {serverError}
              </p>
            )}

            <Button type="submit" loading={submitting} disabled={code.length < 4} className="w-full">
              Verify and continue
            </Button>
          </form>

          <p className="mt-4 text-center text-sm text-slate-500">
            Didn&apos;t get the code?{" "}
            {cooldown > 0 ? (
              <span className="text-slate-400">Resend in {cooldown}s</span>
            ) : (
              <button
                type="button"
                onClick={onResend}
                disabled={!identifier}
                className="font-medium text-primary-600 hover:underline disabled:text-slate-400"
              >
                Resend code
              </button>
            )}
          </p>

          <p className="mt-2 text-center text-sm text-slate-500">
            Wrong email?{" "}
            <Link to="/register" className="font-medium text-primary-600 hover:underline">
              Register again
            </Link>
          </p>
        </Card>
      </div>
    </div>
  );
}
