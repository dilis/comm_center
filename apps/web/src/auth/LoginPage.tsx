import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useLocation, useNavigate } from "react-router";
import { z } from "zod";

import { errorMessage } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { useAuth } from "./AuthContext";

const schema = z.object({
  username: z.string().min(1, "Enter your username"),
  password: z.string().min(1, "Enter your password"),
});
type Values = z.infer<typeof schema>;

export default function LoginPage() {
  const { status, login } = useAuth();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [failure, setFailure] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  if (status === "authenticated") return <Navigate to={from} replace />;

  const submit = handleSubmit(async ({ username, password }) => {
    setFailure(null);
    try {
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err) {
      setFailure(errorMessage(err));
    }
  });

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 bg-brand p-4">
      <p className="text-sm font-semibold uppercase tracking-[0.2em] text-brand-foreground">Comm Center</p>
      <form onSubmit={submit} noValidate className="w-full max-w-sm space-y-4 rounded-md border-t-4 border-t-accent-line bg-card p-8 shadow-xl">
        <h1 className="text-xl font-semibold tracking-tight text-primary">Sign in</h1>
        <div className="space-y-1.5">
          <Label htmlFor="username">Username</Label>
          <Input id="username" autoComplete="username" autoFocus {...register("username")} />
          {errors.username && <p className="text-xs text-destructive">{errors.username.message}</p>}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input id="password" type="password" autoComplete="current-password" {...register("password")} />
          {errors.password && <p className="text-xs text-destructive">{errors.password.message}</p>}
        </div>
        {failure && (
          <p role="alert" className="text-sm text-destructive">
            {failure}
          </p>
        )}
        <Button type="submit" className="w-full" disabled={isSubmitting}>
          Sign in
        </Button>
      </form>
    </main>
  );
}
