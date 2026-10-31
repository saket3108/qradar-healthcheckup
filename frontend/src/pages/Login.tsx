import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { Activity, Loader2, Lock, Mail, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/primitives";
import { post } from "@/lib/api";
import { errMsg } from "@/lib/utils";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { loggedIn } from "@/store/auth";
import type { User } from "@/types";

export const loginSchema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});
type Form = z.infer<typeof loginSchema>;

export default function Login() {
  const dispatch = useAppDispatch();
  const nav = useNavigate();
  const loc = useLocation();
  const token = useAppSelector((s) => s.auth.token);
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Form>({ resolver: zodResolver(loginSchema) });

  if (token) return <Navigate to="/" replace />;

  const onSubmit = handleSubmit(async (v) => {
    setError(null);
    try {
      const r = await post<{ access_token: string; user: User }>("/api/auth/login", v);
      dispatch(loggedIn({ token: r.access_token, user: r.user }));
      nav((loc.state as { from?: string } | null)?.from ?? "/", { replace: true });
    } catch (e) { setError(errMsg(e)); }
  });

  return (
    <div className="relative grid min-h-screen place-items-center overflow-hidden px-4">
      <div className="aurora bg-grid absolute inset-0" aria-hidden />
      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="relative grid w-full max-w-4xl overflow-hidden rounded-2xl border glass md:grid-cols-2">
        <div className="hidden flex-col justify-between bg-gradient-to-br from-primary/25 via-transparent to-sev-info/20 p-8 md:flex">
          <div className="flex items-center gap-2.5 font-semibold"><span className="grid size-9 place-items-center rounded-lg bg-primary text-primary-foreground"><Activity className="size-5" /></span>QRadar Health Checkup</div>
          <div>
            <h2 className="text-2xl font-semibold leading-snug">From get_logs to a customer-ready assessment in minutes.</h2>
            <ul className="mt-5 space-y-3 text-sm text-muted-foreground">
              {["Deployment, HA and validation analysis", "Notification, log source and WinCollect root-cause", "AI-assisted findings mapped to IBM best practice", "PDF, Word and PowerPoint reports"].map((t) => (
                <li key={t} className="flex items-center gap-2"><Sparkles className="size-4 text-primary" />{t}</li>
              ))}
            </ul>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground"><ShieldCheck className="size-4" />Uploads are validated against zip-slip, traversal and malicious archives.</div>
        </div>
        <form onSubmit={onSubmit} noValidate className="space-y-5 p-8" aria-label="Sign in">
          <div>
            <h1 className="text-xl font-semibold">Sign in</h1>
            <p className="mt-1 text-sm text-muted-foreground">Use your platform account to continue.</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <div className="relative"><Mail className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
              <Input id="email" type="email" autoComplete="username" className="pl-9" placeholder="you@company.com" aria-invalid={!!errors.email} {...register("email")} /></div>
            {errors.email && <p role="alert" className="text-xs text-sev-critical">{errors.email.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <div className="relative"><Lock className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
              <Input id="password" type="password" autoComplete="current-password" className="pl-9" placeholder="••••••••••••" aria-invalid={!!errors.password} {...register("password")} /></div>
            {errors.password && <p role="alert" className="text-xs text-sev-critical">{errors.password.message}</p>}
          </div>
          {error && <div role="alert" className="rounded-md border border-sev-critical/40 bg-sev-critical/10 px-3 py-2 text-sm text-sev-critical">{error}</div>}
          <Button type="submit" size="lg" className="w-full" disabled={isSubmitting}>{isSubmitting && <Loader2 className="animate-spin" />}Sign in</Button>
        </form>
      </motion.div>
    </div>
  );
}
