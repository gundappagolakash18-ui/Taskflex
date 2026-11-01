import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { authApi } from "@/api/auth";
import { ApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";
import { errorMessage } from "@/lib/utils";
import { Button, Card, Field, Input } from "@/components/ui";
import GoogleSignInButton from "@/components/GoogleSignInButton";

const schema = z.object({
  identifier: z
    .string()
    .trim()
    .min(3, "Enter your email or phone number")
    .refine(
      (v) =>
        v.includes("@")
          ? /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)
          : v.replace(/\D/g, "").length >= 8,
      "Enter a valid email address or phone number"
    ),
  password: z.string().min(1, "Password is required"),
});

type FormValues = z.infer<typeof schema>;

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { identifier: "", password: "" } });

  const from = (location.state as { from?: string } | null)?.from;

  async function onSubmit(values: FormValues) {
    setServerError(null);
    try {
      const result = await authApi.login(values.identifier, values.password);
      setAuth(result.user, result.tokens.access_token, result.tokens.refresh_token);
      toast.success(`Welcome back, ${result.user.full_name.split(" ")[0]}!`);
      if (from) navigate(from, { replace: true });
      else if (result.user.role === "ADMIN") navigate("/admin", { replace: true });
      else if (result.user.role === "WORKER") navigate("/worker", { replace: true });
      else navigate("/app", { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.code === "ACCOUNT_DISABLED") {
        setServerError("This account has been disabled. Contact support.");
      } else if (error instanceof ApiError && error.code === "EMAIL_NOT_VERIFIED") {
        toast.info("Verify your account to finish signing in.");
        navigate("/verify-email", { state: { identifier: values.identifier } });
      } else {
        setServerError(errorMessage(error));
      }
    }
  }

  async function handleGoogle(credential: string) {
    setServerError(null);
    try {
      const result = await authApi.googleAuth(credential);
      setAuth(result.user, result.tokens.access_token, result.tokens.refresh_token);
      toast.success(`Welcome back, ${result.user.full_name.split(" ")[0]}!`);
      if (from) navigate(from, { replace: true });
      else if (result.user.role === "ADMIN") navigate("/admin", { replace: true });
      else if (result.user.role === "WORKER") navigate("/worker", { replace: true });
      else navigate("/app", { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.code === "ACCOUNT_DISABLED") {
        setServerError("This account has been disabled. Contact support.");
      } else {
        setServerError(errorMessage(error));
      }
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
          <h1 className="text-xl font-bold text-slate-900">Welcome back</h1>
          <p className="mt-1 text-sm text-slate-500">Sign in to post errands or pick up work.</p>

          <form onSubmit={handleSubmit(onSubmit)} className="mt-5 space-y-4" noValidate>
            <Field label="Email or phone" htmlFor="identifier">
              <Input
                id="identifier"
                type="text"
                autoComplete="username"
                placeholder="you@example.com or 98765 43210"
                error={errors.identifier?.message}
                {...register("identifier")}
              />
            </Field>
            <Field label="Password" htmlFor="password">
              <Input id="password" type="password" autoComplete="current-password" placeholder="••••••••" error={errors.password?.message} {...register("password")} />
            </Field>

            {serverError && (
              <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
                {serverError}
              </p>
            )}

            <Button type="submit" loading={isSubmitting} className="w-full">
              Sign in
            </Button>
          </form>

          <GoogleSignInButton text="signin_with" onCredential={handleGoogle} />

          <div className="mt-4 flex items-center justify-between text-sm">
            <Link to="/forgot-password" className="font-medium text-primary-600 hover:underline">
              Forgot password?
            </Link>
            <Link to="/register" className="font-medium text-primary-600 hover:underline">
              Create account
            </Link>
          </div>
        </Card>
      </div>
    </div>
  );
}
