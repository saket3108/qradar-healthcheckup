import { motion } from "framer-motion";
import { AlertOctagon, AlertTriangle, ChevronRight, Info, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, PriorityBadge, SeverityBadge } from "@/components/ui/badges";
import { Async, Disclosure, KV, Kpi, PageHeader, RecoList, Section } from "@/components/common";
import { Meter, ScoreRing } from "@/components/charts/gauges";
import { useAssessmentCtx } from "@/pages/AssessmentLayout";
import { useHealth } from "@/lib/queries";
import { scoreColor } from "@/lib/utils";
import type { CategoryScore } from "@/types";

export const CATEGORY_ORDER = ["deployment", "applications", "performance", "notifications", "logsources", "wincollect", "licensing"] as const;
export const CATEGORY_LINK: Record<string, string> = { deployment: "deployment", applications: "applications", performance: "performance", notifications: "notifications", logsources: "logsources", wincollect: "logsources", licensing: "licensing" };

export function CategoryCard({ c, to }: { c: CategoryScore; to: string }) {
  const total = c.findings.critical + c.findings.high + c.findings.medium + c.findings.low;
  return (
    <Link to={to} className="card-surface group block p-4 transition-all hover:-translate-y-0.5 hover:border-primary/40" aria-label={`${c.label} score ${c.score}`}>
      <div className="flex items-center justify-between"><span className="label-caps">{c.label}</span><ChevronRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" /></div>
      <div className="mt-2 flex items-baseline gap-1.5"><span className="text-3xl font-semibold tabular-nums leading-none" style={{ color: scoreColor(c.score) }}>{c.score}</span><span className="text-xs text-muted-foreground">/100 · grade {c.grade}</span></div>
      <Meter className="mt-3" value={c.score} color={scoreColor(c.score)} />
      <div className="mt-2.5 text-xs text-muted-foreground">{c.data_available ? (total ? `${total} open finding${total === 1 ? "" : "s"}` : "No findings") : "No data in bundle"}</div>
    </Link>
  );
}

export default function Dashboard() {
  const { id, assessment } = useAssessmentCtx();
  const q = useHealth(id, true);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div>
      <PageHeader title="Executive Health Dashboard" description="Overall posture of the QRadar deployment, derived from every dataset in the get_logs package." />
      <Async q={q} rows={2}>
        {(h) => {
          const o = h.scores.overall;
          const sev = o.severity_totals;
          return (
            <div className="space-y-6">
              <div className="grid gap-4 lg:grid-cols-[auto_1fr]">
                <motion.div initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} className="card-surface flex flex-col items-center justify-center gap-3 p-6 lg:min-w-[320px]">
                  <div className="label-caps">Overall health score</div>
                  <ScoreRing score={o.score} size={190} label={`Grade ${o.grade}`} />
                  <div className="flex flex-wrap justify-center gap-2">
                    <Badge tone={o.risk_level === "Critical" ? "critical" : o.risk_level === "High" ? "high" : o.risk_level === "Medium" ? "medium" : "ok"}>{o.risk_level} risk · {o.risk_score}</Badge>
                    <Badge tone="primary">Maturity: {o.maturity_level}</Badge>
                  </div>
                </motion.div>
                <div className="space-y-4">
                  <Section title={h.summary.headline} description={`${assessment.customer_name ?? assessment.name} · executive summary`}>
                    <div className="space-y-2.5 text-sm leading-relaxed">{h.summary.paragraphs.map((p, i) => <p key={i}>{p}</p>)}</div>
                    {h.summary.highlights.length > 0 && <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">{h.summary.highlights.map((x, i) => <li key={i} className="flex gap-2 text-xs text-muted-foreground"><span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" />{x}</li>)}</ul>}
                  </Section>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="Risk summary">
                    <Kpi label="Critical findings" value={sev.critical} tone="critical" icon={<AlertOctagon />} />
                    <Kpi label="High findings" value={sev.high} tone="high" icon={<ShieldAlert />} />
                    <Kpi label="Medium findings" value={sev.medium} tone="medium" icon={<AlertTriangle />} />
                    <Kpi label="Low findings" value={sev.low} tone="low" icon={<Info />} />
                  </div>
                </div>
              </div>

              <section aria-label="Category health scores">
                <h2 className="mb-3 text-sm font-semibold">Category health</h2>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
                  {CATEGORY_ORDER.map((k) => h.scores.categories[k] && <CategoryCard key={k} c={h.scores.categories[k]} to={CATEGORY_LINK[k]} />)}
                </div>
              </section>

              <Section title="Top 10 recommendations" description="Highest-impact actions ranked by severity, priority and number of affected objects.">
                <div className="space-y-2">
                  {h.top_recommendations.slice(0, 10).map((r, i) => (
                    <Disclosure key={r.code} open={open === r.code} onToggle={() => setOpen(open === r.code ? null : r.code)}
                      header={<div className="flex items-center gap-3"><span className="grid size-6 shrink-0 place-items-center rounded-full bg-accent text-xs font-semibold tabular-nums">{i + 1}</span><SeverityBadge severity={r.severity} /><PriorityBadge priority={r.priority} />
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">{r.title}</span>{r.count > 1 && <span className="text-xs text-muted-foreground">{r.count} occurrences</span>}</div>}>
                      <div className="grid gap-4 md:grid-cols-2">
                        <div className="space-y-3"><KV label="Impact">{r.impact}</KV><KV label="Business impact">{r.business_impact}</KV><KV label="IBM best practice">{r.best_practice}</KV></div>
                        <div className="space-y-3"><KV label="Recommended actions"><RecoList items={r.recommendation} /></KV>
                          {r.observations.length > 0 && <KV label="Observed"><ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">{r.observations.slice(0, 5).map((o, j) => <li key={j}>{o}</li>)}</ul></KV>}</div>
                      </div>
                    </Disclosure>
                  ))}
                </div>
              </Section>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
