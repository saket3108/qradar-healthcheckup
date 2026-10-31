import { useMemo, useState } from "react";
import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer, Tooltip } from "recharts";
import { Async, CommentBox, Disclosure, EmptyState, KV, Kpi, PageHeader, RecoList, Section } from "@/components/common";
import { ChartTooltip } from "@/components/charts/ChartKit";
import { Meter, ScoreRing } from "@/components/charts/gauges";
import { Badge, PriorityBadge, SeverityBadge, StatusBadge } from "@/components/ui/badges";
import { Select } from "@/components/ui/primitives";
import { Segmented } from "@/components/ui/tabs";
import { useAssessmentCtx } from "@/pages/AssessmentLayout";
import { useFindings, useHealth, useSaveComment, useUpdateFinding } from "@/lib/queries";
import { scoreColor, sevRank } from "@/lib/utils";
import type { Finding } from "@/types";
import { CATEGORY_ORDER } from "@/pages/Dashboard";

const MATURITY = [{ lvl: 1, name: "Initial" }, { lvl: 2, name: "Developing" }, { lvl: 3, name: "Defined" }, { lvl: 4, name: "Managed" }, { lvl: 5, name: "Optimised" }];

function FindingRow({ f, id, canEdit, open, onToggle }: { f: Finding; id: string; canEdit: boolean; open: boolean; onToggle: () => void }) {
  const upd = useUpdateFinding(id);
  const save = useSaveComment(id);
  return (
    <Disclosure open={open} onToggle={onToggle}
      header={<div className="flex flex-wrap items-center gap-2.5"><SeverityBadge severity={f.severity} /><PriorityBadge priority={f.priority} /><span className="min-w-0 flex-1 truncate text-sm font-medium">{f.title}</span><Badge tone="neutral">{f.category}</Badge><StatusBadge status={f.status} /></div>}>
      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-3.5"><KV label="Observation">{f.observation}</KV><KV label="Description">{f.description}</KV><KV label="Root cause">{f.root_cause}</KV><KV label="Impact">{f.impact}</KV><KV label="Business impact">{f.business_impact}</KV><KV label="Risk">{f.risk}</KV>
          {f.hosts.length > 0 && <KV label="Affected hosts"><div className="flex flex-wrap gap-1.5">{f.hosts.map((h) => <Badge key={h}>{h}</Badge>)}</div></KV>}</div>
        <div className="space-y-3.5"><KV label="Recommendation"><RecoList items={f.recommendation} /></KV><KV label="IBM best practice">{f.best_practice}</KV>
          {canEdit && <div className="grid grid-cols-2 gap-3"><div className="space-y-1"><div className="label-caps">Status</div><Select aria-label="Finding status" className="w-full" value={f.status} disabled={upd.isPending} onChange={(e) => upd.mutate({ fid: f.id, status: e.target.value })}>{["open", "accepted", "resolved", "dismissed"].map((s) => <option key={s} value={s}>{s}</option>)}</Select></div>
            <div className="space-y-1"><div className="label-caps">Severity</div><Select aria-label="Finding severity" className="w-full" value={f.severity} disabled={upd.isPending} onChange={(e) => upd.mutate({ fid: f.id, severity: e.target.value })}>{["critical", "high", "medium", "low", "info"].map((s) => <option key={s} value={s}>{s}</option>)}</Select></div></div>}
          {upd.error && <p role="alert" className="text-xs text-sev-critical">{(upd.error as Error).message}</p>}
          <CommentBox value={f.comment} readOnly={!canEdit} onSave={(text) => save.mutateAsync({ type: "finding", key: f.id, text })} /></div>
      </div>
    </Disclosure>
  );
}

export default function HealthScore() {
  const { id, canEdit } = useAssessmentCtx();
  const q = useHealth(id, true);
  const fq = useFindings(id, true);
  const [cat, setCat] = useState("all");
  const [open, setOpen] = useState<string | null>(null);
  const findings = useMemo(() => (fq.data ?? []).filter((f) => cat === "all" || f.category === cat).sort((a, b) => sevRank(a.severity) - sevRank(b.severity) || a.priority.localeCompare(b.priority)), [fq.data, cat]);
  return (
    <div>
      <PageHeader title="Health Score" description="Scoring engine breakdown: category scores, overall health, risk score and maturity level. Changing a finding's status or severity recalculates the score." />
      <Async q={q} rows={2}>
        {(h) => {
          const o = h.scores.overall;
          const cats = CATEGORY_ORDER.map((k) => h.scores.categories[k]).filter(Boolean);
          return (
            <div className="space-y-6">
              <div className="grid gap-4 lg:grid-cols-[auto_1fr_1fr]">
                <div className="card-surface flex flex-col items-center gap-2 p-6"><div className="label-caps">Overall health</div><ScoreRing score={o.score} label={`Grade ${o.grade}`} size={170} /></div>
                <div className="card-surface flex flex-col items-center gap-2 p-6"><div className="label-caps">Risk score</div><ScoreRing score={100 - o.risk_score} sub="inverse" size={170} label={`${o.risk_score}/100 · ${o.risk_level}`} /></div>
                <Section title="Maturity level" description={`Level ${o.maturity_index} of 5`}>
                  <ol className="space-y-2">{MATURITY.map((m) => (<li key={m.lvl} className="flex items-center gap-3"><span className={`grid size-6 place-items-center rounded-full text-xs font-semibold ${m.lvl <= o.maturity_index ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}>{m.lvl}</span>
                    <span className={m.lvl === o.maturity_index ? "font-semibold" : "text-muted-foreground"}>{m.name}</span>{m.lvl === o.maturity_index && <Badge tone="primary">Current</Badge>}</li>))}</ol>
                </Section>
              </div>
              <div className="grid gap-4 xl:grid-cols-[1fr_1.4fr]">
                <Section title="Category profile"><div className="h-[300px]" role="img" aria-label="Category score radar"><ResponsiveContainer><RadarChart data={cats.map((c) => ({ name: c!.label, score: c!.score }))} outerRadius="75%">
                  <PolarGrid stroke="hsl(var(--border))" /><PolarAngleAxis dataKey="name" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} /><PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                  <Radar dataKey="score" name="Score" stroke="#4589ff" fill="#4589ff" fillOpacity={0.3} strokeWidth={2} /><Tooltip content={<ChartTooltip />} /></RadarChart></ResponsiveContainer></div></Section>
                <Section title="Scoring breakdown" description="Weighted contribution of each category to the overall score" bodyClassName="p-0">
                  <table className="w-full text-sm"><thead><tr className="border-b text-left [&>th]:px-4 [&>th]:py-2.5"><th className="label-caps">Category</th><th className="label-caps">Score</th><th className="label-caps">Weight</th><th className="label-caps">C / H / M / L</th><th className="label-caps w-40">&nbsp;</th></tr></thead>
                    <tbody>{cats.map((c) => (<tr key={c!.key} className="border-b last:border-0 [&>td]:px-4 [&>td]:py-2.5"><td className="font-medium">{c!.label}{!c!.data_available && <Badge className="ml-2">no data</Badge>}</td><td className="font-semibold tabular-nums" style={{ color: scoreColor(c!.score) }}>{c!.score} <span className="text-xs font-normal text-muted-foreground">({c!.grade})</span></td><td className="tabular-nums text-muted-foreground">{Math.round(c!.weight * 100)}%</td>
                      <td className="tabular-nums text-xs">{c!.findings.critical} / {c!.findings.high} / {c!.findings.medium} / {c!.findings.low}</td><td><Meter value={c!.score} color={scoreColor(c!.score)} /></td></tr>))}</tbody></table>
                </Section>
              </div>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4"><Kpi label="Critical" value={o.severity_totals.critical} tone="critical" /><Kpi label="High" value={o.severity_totals.high} tone="high" /><Kpi label="Medium" value={o.severity_totals.medium} tone="medium" /><Kpi label="Low" value={o.severity_totals.low} tone="low" /></div>
              <Section title="Findings" description="Review, re-prioritise, accept or dismiss findings. The score updates immediately."
                actions={<Segmented layoutId="find-cat" value={cat} onChange={setCat} items={[{ key: "all", label: "All" }, ...CATEGORY_ORDER.map((c) => ({ key: c, label: h.scores.categories[c]?.label ?? c }))]} className="max-w-full overflow-x-auto" />}>
                {fq.isLoading ? <p className="text-sm text-muted-foreground">Loading findings…</p> : findings.length === 0 ? <EmptyState title="No findings" description="Nothing to report in this category." /> : <div className="space-y-2">{findings.map((f) => <FindingRow key={f.id} f={f} id={id} canEdit={canEdit} open={open === f.id} onToggle={() => setOpen(open === f.id ? null : f.id)} />)}</div>}
              </Section>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
