import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { authApi } from "@/api/auth";
import { ApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";
import { errorMessage } from "@/lib/utils";
import { Button, Card, Field, Input } from "@/components/ui";
import { cn } from "@/lib/utils";
import GoogleSignInButton from "@/components/GoogleSignInButton";

const schema = z.object({
  role: z.enum(["CUSTOMER", "WORKER"]),
  full_name: z.string().min(2, "Enter your full name").max(120),
  email: z.string().email("Enter a valid email address"),
  phone: z
    .string()
    .min(8, "Phone must contain at least 8 digits")
    .regex(/^[+0-9 ]+$/, "Digits and + only"),
  city: z.string().max(100).optional().or(z.literal("")),
  password: z
    .string()
    .min(8, "At least 8 characters")
    .regex(/[A-Za-z]/, "Include a letter")
    .regex(/[0-9]/, "Include a number"),
});

type FormValues = z.infer<typeof schema>;

export default function Register() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      role: params.get("role") === "WORKER" ? "WORKER" : "CUSTOMER",
      full_name: "",
      email: "",
      phone: "",
      city: "Belagavi",
      password: "",
    },
  });

  const role = watch("role");

  async function onSubmit(values: FormValues) {
    setServerError(null);
    try {
      await authApi.register({
        role: values.role,
        full_name: values.full_name,
        email: values.email,
        phone: values.phone,
        password: values.password,
        city: values.city || undefined,
      });
      toast.success("Account created! Check your email for the 6-digit code.");
      navigate("/verify-email", { state: { identifier: values.email } });
    } catch (error) {
      setServerError(errorMessage(error));
    }
  }

  function pickRole(next: "CUSTOMER" | "WORKER") {
    setValue("role", next);
  }

  async function handleGoogle(credential: string) {
    setServerError(null);
    try {
      const result = await authApi.googleAuth(credential, role);
      setAuth(result.user, result.tokens.access_token, result.tokens.refresh_token);
      toast.success(`Welcome to TaskFlex, ${result.user.full_name.split(" ")[0]}!`);
      if (result.user.role === "WORKER") navigate("/worker", { replace: true });
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
          <h1 className="text-xl font-bold text-slate-900">Create your account</h1>
          <p className="mt-1 text-sm text-slate-500">Choose how you want to use TaskFlex.</p>

          <div className="mt-4 grid grid-cols-2 gap-2" role="radiogroup" aria-label="Account type">
            {(
              [
                { value: "CUSTOMER", title: "I need errands done", sub: "Post and delegate tasks" },
                { value: "WORKER", title: "I want to earn", sub: "Run errands for others" },
              ] as const
            ).map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={role === option.value}
                onClick={() => pickRole(option.value)}
                className={cn(
                  "rounded-xl border p-3 text-left transition-colors",
                  role === option.value
                    ? "border-primary-500 bg-primary-50 ring-2 ring-primary-500/20"
                    : "border-slate-200 bg-white hover:border-slate-300"
                )}
              >
                <p className="text-sm font-semibold text-slate-900">{option.title}</p>
                <p className="mt-0.5 text-xs text-slate-500">{option.sub}</p>
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit(onSubmit)} className="mt-5 space-y-4" noValidate>
            <Field label="Full name" htmlFor="full_name">
              <Input id="full_name" autoComplete="name" placeholder="Ananya Desai" error={errors.full_name?.message} {...register("full_name")} />
            </Field>
            <Field label="Email" htmlFor="email">
              <Input id="email" type="email" autoComplete="email" placeholder="you@example.com" error={errors.email?.message} {...register("email")} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Phone" htmlFor="phone">
                <Input id="phone" autoComplete="tel" placeholder="+919812345678" error={errors.phone?.message} {...register("phone")} />
              </Field>
              <Field label="City" htmlFor="city">
                <Input id="city" placeholder="Belagavi" error={errors.city?.message} {...register("city")} />
              </Field>
            </div>
            <Field label="Password" htmlFor="password" hint="Minimum 8 characters with a letter and a number.">
              <Input id="password" type="password" autoComplete="new-password" placeholder="••••••••" error={errors.password?.message} {...register("password")} />
            </Field>

            {serverError && (
              <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
                {serverError}
              </p>
            )}

            <Button type="submit" loading={isSubmitting} className="w-full">
              Create account
            </Button>
          </form>

          <GoogleSignInButton text="signup_with" onCredential={handleGoogle} />

          <p className="mt-4 text-center text-sm text-slate-500">
            Already have an account?{" "}
            <Link to="/login" className="font-medium text-primary-600 hover:underline">
              Sign in
            </Link>
          </p>
        </Card>
      </div>
    </div>
  );
}
