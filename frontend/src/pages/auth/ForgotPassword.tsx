import { useState } from "react";
import { Link } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { authApi } from "@/api/auth";
import { toast } from "@/stores/toast";
import { errorMessage } from "@/lib/utils";
import { Button, Card, Field, Input } from "@/components/ui";

const schema = z.object({
  email: z.string().email("Enter a valid email address"),
});

type FormValues = z.infer<typeof schema>;

export default function ForgotPassword() {
  const [resetToken, setResetToken] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { email: "" } });

  async function onSubmit(values: FormValues) {
    try {
      const result = await authApi.forgotPassword(values.email);
      setSent(true);
      setResetToken(result.reset_token ?? null);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-md">
        <Card className="p-6">
          <h1 className="text-xl font-bold text-slate-900">Reset your password</h1>
          <p className="mt-1 text-sm text-slate-500">
            Enter your account email. {sent ? "" : "We'll send reset instructions."}
          </p>

          {!sent ? (
            <form onSubmit={handleSubmit(onSubmit)} className="mt-5 space-y-4" noValidate>
              <Field label="Email" htmlFor="email">
                <Input id="email" type="email" autoComplete="email" error={errors.email?.message} {...register("email")} />
              </Field>
              <Button type="submit" loading={isSubmitting} className="w-full">
                Send reset link
              </Button>
            </form>
          ) : (
            <div className="mt-5 space-y-4">
              <p className="rounded-lg bg-emerald-50 px-3 py-2.5 text-sm text-emerald-800">
                If an account exists for that email, reset instructions are on the way.
              </p>
              {resetToken && (
                <div className="rounded-lg border border-dashed border-amber-300 bg-amber-50 px-3 py-2.5 text-sm text-amber-900">
                  <p className="font-semibold">Demo mode:</p>
                  <p className="mt-1 break-all font-mono text-xs">{resetToken}</p>
                  <Link to={`/reset-password?token=${encodeURIComponent(resetToken)}`} className="mt-2 inline-block font-semibold text-amber-800 underline">
                    Open reset form with this token →
                  </Link>
                </div>
              )}
              <Link to="/login" className="btn-secondary w-full">
                Back to sign in
              </Link>
            </div>
          )}

          <p className="mt-4 text-center text-sm">
            <Link to="/login" className="font-medium text-primary-600 hover:underline">
              ← Back to sign in
            </Link>
          </p>
        </Card>
      </div>
    </div>
  );
}
