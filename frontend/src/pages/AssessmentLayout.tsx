import { motion } from "framer-motion";
import { Activity, AppWindow, ArrowLeft, Bell, Bot, FileText, Gauge, Layers, LayoutDashboard, Loader2, Network, RotateCw, ScrollText, ShieldCheck, Cpu, BadgeCheck } from "lucide-react";
import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/badges";
import { ErrorState, LoadingGrid } from "@/components/common";
import { Meter } from "@/components/charts/gauges";
import { useAssessment, useResume } from "@/lib/queries";
import { cn, fmtDate } from "@/lib/utils";
import { useAppSelector } from "@/store/hooks";
import { can } from "@/store/auth";
import type { Assessment } from "@/types";
import { createContext, useContext } from "react";

export const TABS = [
  { to: "", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "overview", label: "Overview", icon: Layers },
  { to: "deployment", label: "Deployment", icon: Network },
  { to: "notifications", label: "Notifications", icon: Bell },
  { to: "logsources", label: "Log Sources", icon: ScrollText },
  { to: "applications", label: "Applications", icon: AppWindow },
  { to: "performance", label: "Performance", icon: Cpu },
  { to: "licensing", label: "Licensing", icon: BadgeCheck },
  { to: "health", label: "Health Score", icon: Gauge },
  { to: "assistant", label: "AI Assistant", icon: Bot },
  { to: "report", label: "Report Builder", icon: FileText },
] as const;

interface Ctx { id: string; assessment: Assessment; canEdit: boolean; canExport: boolean }
const AssessmentCtx = createContext<Ctx | null>(null);
export function useAssessmentCtx(): Ctx {
  const c = useContext(AssessmentCtx);
  if (!c) throw new Error("useAssessmentCtx must be used inside AssessmentLayout");
  return c;
}

function Progress({ a }: { a: Assessment }) {
  const resume = useResume(a.id);
  const failed = a.status === "failed";
  return (
    <div className="mx-auto mt-10 max-w-2xl">
      <div className="card-surface p-6">
        <div className="flex items-center gap-3">
          {failed ? <ShieldCheck className="size-6 text-sev-critical" /> : <Loader2 className="size-6 animate-spin text-primary" />}
          <div>
            <h2 className="font-semibold">{failed ? "Analysis failed" : a.status === "queued" ? "Queued for analysis" : "Analysing your get_logs package"}</h2>
            <p className="text-sm text-muted-foreground">{failed ? "The job stopped. Completed stages are checkpointed, so you can resume without starting over." : `Current stage: ${a.current_stage ?? "waiting for a worker"}`}</p>
          </div>
        </div>
        {!failed && <div className="mt-5"><Meter value={a.progress} color="hsl(var(--primary))" /><div className="mt-1.5 text-xs text-muted-foreground">{Math.round(a.progress)}% complete</div></div>}
        {failed && a.error && <div role="alert" className="mt-4 rounded-md border border-sev-critical/40 bg-sev-critical/10 p-3 text-sm">{a.error}</div>}
        <ol className="mt-5 grid gap-1.5">
          {(a.stages ?? []).map((s) => (
            <li key={s.name} className="flex items-center gap-2.5 text-sm">
              <span className={cn("size-2 rounded-full", s.status === "done" ? "bg-sev-ok" : s.status === "running" ? "animate-pulseDot bg-primary" : s.status === "failed" ? "bg-sev-critical" : s.status === "skipped" ? "bg-sev-medium" : "bg-muted-foreground/30")} />
              <span className={cn(s.status === "pending" && "text-muted-foreground")}>{s.label}</span>
              <span className="ml-auto max-w-[55%] truncate text-xs text-muted-foreground" title={s.message ?? undefined}>{s.status === "running" ? `${Math.round(s.progress * 100)}%` : s.message ?? s.status}</span>
            </li>
          ))}
        </ol>
        {failed && <Button className="mt-5" onClick={() => resume.mutate(undefined)} disabled={resume.isPending}><RotateCw className={cn(resume.isPending && "animate-spin")} />Resume analysis</Button>}
      </div>
    </div>
  );
}

export default function AssessmentLayout() {
  const { id = "" } = useParams();
  const user = useAppSelector((s) => s.auth.user);
  const q = useAssessment(id);
  if (q.isLoading) return <LoadingGrid />;
  if (q.error || !q.data) return <div className="space-y-3"><Link to="/" className="text-sm text-primary">← Back to assessments</Link><ErrorState error={q.error ?? "Assessment not found"} retry={() => void q.refetch()} /></div>;
  const a = q.data;
  const ready = a.status === "completed" || a.status === "partial";

  return (
    <AssessmentCtx.Provider value={{ id, assessment: a, canEdit: can(user?.role, "edit"), canExport: can(user?.role, "export") }}>
      <div>
        <Link to="/" className="mb-3 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="size-3.5" />All assessments</Link>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">{a.customer_name || a.name}</h1>
          <StatusBadge status={a.status} />
          <span className="text-xs text-muted-foreground">{a.qradar_version ? `QRadar ${a.qradar_version} · ` : ""}{a.source_filename} · {fmtDate(a.created_at)}{a.consultant_name ? ` · ${a.consultant_name}` : ""}</span>
        </div>
        {!ready ? <Progress a={a} /> : (
          <>
            {a.status === "partial" && <div role="status" className="mb-4 flex items-center gap-2 rounded-md border border-sev-medium/40 bg-sev-medium/10 px-3 py-2 text-sm"><Activity className="size-4 text-sev-medium" />Some analysis stages could not complete (missing or unreadable data). Available results are shown; you can resume to retry.</div>}
            <nav aria-label="Assessment sections" className="sticky top-14 z-30 -mx-4 mb-6 overflow-x-auto border-b bg-background/80 px-4 backdrop-blur-md lg:-mx-6 lg:px-6">
              <div className="flex min-w-max gap-1">
                {TABS.map((t) => (
                  <NavLink key={t.to} to={t.to} end={"end" in t ? t.end : false} className={({ isActive }) => cn("relative flex items-center gap-1.5 px-3 py-3 text-sm text-muted-foreground transition-colors hover:text-foreground", isActive && "text-foreground")}>
                    {({ isActive }) => (<>
                      <t.icon className="size-4" />{t.label}
                      {isActive && <motion.span layoutId="tab-underline" className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary" />}
                    </>)}
                  </NavLink>
                ))}
              </div>
            </nav>
            <motion.div key="content" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}><Outlet /></motion.div>
          </>
        )}
      </div>
    </AssessmentCtx.Provider>
  );
}
