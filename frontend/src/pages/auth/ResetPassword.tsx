import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { authApi } from "@/api/auth";
import { toast } from "@/stores/toast";
import { errorMessage } from "@/lib/utils";
import { Button, Card, Field, Input } from "@/components/ui";

const schema = z
  .object({
    token: z.string().min(4, "Paste the reset token from your email"),
    new_password: z
      .string()
      .min(8, "At least 8 characters")
      .regex(/[A-Za-z]/, "Include a letter")
      .regex(/[0-9]/, "Include a number"),
    confirm: z.string(),
  })
  .refine((data) => data.new_password === data.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  });

type FormValues = z.infer<typeof schema>;

export default function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { token: params.get("token") ?? "", new_password: "", confirm: "" },
  });

  async function onSubmit(values: FormValues) {
    setServerError(null);
    try {
      await authApi.resetPassword(values.token, values.new_password);
      toast.success("Password updated — sign in with your new password.");
      navigate("/login", { replace: true });
    } catch (error) {
      setServerError(errorMessage(error));
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-md">
        <Card className="p-6">
          <h1 className="text-xl font-bold text-slate-900">Choose a new password</h1>
          <form onSubmit={handleSubmit(onSubmit)} className="mt-5 space-y-4" noValidate>
            <Field label="Reset token" htmlFor="token" hint="From the reset link you received.">
              <Input id="token" className="font-mono text-xs" error={errors.token?.message} {...register("token")} />
            </Field>
            <Field label="New password" htmlFor="new_password">
              <Input id="new_password" type="password" autoComplete="new-password" error={errors.new_password?.message} {...register("new_password")} />
            </Field>
            <Field label="Confirm password" htmlFor="confirm">
              <Input id="confirm" type="password" autoComplete="new-password" error={errors.confirm?.message} {...register("confirm")} />
            </Field>

            {serverError && (
              <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
                {serverError}
              </p>
            )}

            <Button type="submit" loading={isSubmitting} className="w-full">
              Update password
            </Button>
          </form>
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
