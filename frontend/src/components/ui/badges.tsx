import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

const TONE: Record<string, string> = {
  critical: "bg-sev-critical/15 text-sev-critical border-sev-critical/30",
  high: "bg-sev-high/15 text-sev-high border-sev-high/30",
  medium: "bg-sev-medium/15 text-sev-medium border-sev-medium/30",
  low: "bg-sev-low/15 text-sev-low border-sev-low/30",
  info: "bg-sev-info/15 text-sev-info border-sev-info/30",
  ok: "bg-sev-ok/15 text-sev-ok border-sev-ok/30",
  neutral: "bg-muted text-muted-foreground border-border",
  primary: "bg-primary/15 text-primary border-primary/30",
};
export function Badge({ tone = "neutral", children, className, dot }: { tone?: string; children: ReactNode; className?: string; dot?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold leading-4", TONE[tone] ?? TONE.neutral, className)}>
      {dot && <span className="size-1.5 rounded-full bg-current" />}{children}
    </span>
  );
}
export const SeverityBadge = ({ severity }: { severity: string }) => <Badge tone={severity === "info" ? "info" : severity} dot>{severity.charAt(0).toUpperCase() + severity.slice(1)}</Badge>;
export const PriorityBadge = ({ priority }: { priority: string }) => <Badge tone={priority === "P1" ? "critical" : priority === "P2" ? "high" : priority === "P3" ? "medium" : "low"}>{priority}</Badge>;

const STATUS_TONE: Record<string, string> = {
  running: "ok", healthy: "ok", pass: "ok", connected: "ok", enabled: "ok", completed: "ok", ok: "ok", open: "high", accepted: "info", resolved: "ok", dismissed: "neutral",
  stopped: "neutral", disabled: "neutral", unknown: "neutral", queued: "info", processing: "primary", partial: "medium",
  degraded: "medium", warning: "medium", error: "critical", critical: "critical", failed: "critical", disconnected: "high",
};
export const StatusBadge = ({ status }: { status: string }) => <Badge tone={STATUS_TONE[status.toLowerCase()] ?? "neutral"} dot>{status.charAt(0).toUpperCase() + status.slice(1).toLowerCase()}</Badge>;
