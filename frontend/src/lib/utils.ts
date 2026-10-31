import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

export function fmtBytes(n: number | null | undefined, digits = 1): string {
  if (n == null || !isFinite(n)) return "—";
  const u = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0, v = Math.abs(n);
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${(n < 0 ? -v : v).toFixed(i === 0 ? 0 : digits)} ${u[i]}`;
}
export function fmtNum(n: number | null | undefined, digits = 0): string {
  if (n == null || !isFinite(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
export function fmtCompact(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return "—";
  return Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);
}
export function fmtPct(n: number | null | undefined, digits = 0): string {
  return n == null || !isFinite(n) ? "—" : `${n.toFixed(digits)}%`;
}
export function fmtDate(s: string | null | undefined, withTime = true): string {
  if (!s) return "—";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return withTime ? d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : d.toLocaleDateString(undefined, { dateStyle: "medium" });
}
export function timeAgo(s: string | null | undefined): string {
  if (!s) return "—";
  const t = new Date(s).getTime();
  if (isNaN(t)) return s;
  const sec = Math.max(0, (Date.now() - t) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

export const SEV_ORDER = ["critical", "high", "medium", "low", "info"] as const;
export const sevRank = (s: string) => { const i = (SEV_ORDER as readonly string[]).indexOf(s); return i < 0 ? 9 : i; };
export const SEV_VAR: Record<string, string> = { critical: "var(--critical)", high: "var(--high)", medium: "var(--medium)", low: "var(--low)", info: "var(--info)", ok: "var(--ok)", unknown: "var(--muted-foreground)" };
export const sevColor = (s: string) => `hsl(${SEV_VAR[s] ?? SEV_VAR.unknown})`;

export function scoreTone(score: number | null | undefined): "ok" | "low" | "medium" | "high" | "critical" {
  if (score == null) return "low";
  return score >= 85 ? "ok" : score >= 70 ? "low" : score >= 55 ? "medium" : score >= 40 ? "high" : "critical";
}
export const scoreColor = (score: number | null | undefined) => sevColor(scoreTone(score));

export function errMsg(e: unknown): string {
  if (e instanceof Error) return e.message;
  return typeof e === "string" ? e : "Unexpected error";
}
