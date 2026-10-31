import { Area, ComposedChart, CartesianGrid, Legend as RLegend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { TrendingUp } from "lucide-react";
import { Async, Kpi, PageHeader, Section, CommentBox } from "@/components/common";
import { ChartTooltip, axisProps, gridProps } from "@/components/charts/ChartKit";
import { SemiGauge } from "@/components/charts/gauges";
import { Badge } from "@/components/ui/badges";
import { useAssessmentCtx } from "@/pages/AssessmentLayout";
import { useComments, useLicensing, useSaveComment } from "@/lib/queries";
import { fmtDate, fmtNum, sevColor } from "@/lib/utils";
import type { LicMetric } from "@/types";

const riskTone = (r: string) => (r === "critical" ? "critical" : r === "high" ? "high" : r === "medium" ? "medium" : r === "low" ? "ok" : "neutral");

export function riskNarrative(m: LicMetric): string {
  if (m.licensed == null) return `${m.name} licence capacity could not be determined from the bundle. Confirm entitlements in the License Pool Management page.`;
  const pct = m.consumption_pct ?? 0;
  const parts = [`${m.name} consumption is ${pct.toFixed(1)}% of the licensed ${fmtNum(m.licensed)} ${m.unit} (peak ${m.peak_pct?.toFixed(1) ?? "n/a"}%).`];
  if (m.trend) parts.push(`Usage is ${m.trend.direction} at about ${m.trend.growth_pct_per_month.toFixed(1)}% per month.`);
  if (m.days_to_limit != null) parts.push(m.days_to_limit <= 0 ? "The licensed limit has already been reached." : `At the current trend the limit is reached in roughly ${m.days_to_limit} days.`);
  return parts.join(" ");
}

function MetricBlock({ m }: { m: LicMetric }) {
  const forecast = m.forecast.map((f) => ({ ts: `+${f.months} mo`, months: f.months, value: f.value }));
  const data = m.series.map((s) => ({ ts: s.ts, value: s.value, peak: s.peak, licensed: m.licensed ?? undefined }));
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <div className="card-surface flex flex-col items-center p-4"><SemiGauge value={m.consumption_pct} label={`${m.name} consumption`} sublabel={`${fmtNum(m.current)} of ${fmtNum(m.licensed)} ${m.unit}`} /><div className="mt-3"><Badge tone={riskTone(m.risk)} dot>{m.risk} risk</Badge></div></div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          <Kpi label={`Licensed ${m.name}`} value={fmtNum(m.licensed)} sub={m.unit} /><Kpi label={`Current ${m.name}`} value={fmtNum(m.current)} sub={`avg ${fmtNum(m.average)}`} /><Kpi label={`Peak ${m.name}`} value={fmtNum(m.peak)} sub={m.peak_pct != null ? `${m.peak_pct.toFixed(1)}% of licence` : undefined} tone={m.peak_pct != null && m.peak_pct > 100 ? "critical" : undefined} />
          <Kpi label="Consumption" value={m.consumption_pct != null ? `${m.consumption_pct.toFixed(1)}%` : "—"} tone={m.consumption_pct != null && m.consumption_pct >= 100 ? "critical" : m.consumption_pct != null && m.consumption_pct >= 80 ? "high" : "ok"} />
          <Kpi label="Growth trend" value={m.trend ? `${m.trend.growth_pct_per_month > 0 ? "+" : ""}${m.trend.growth_pct_per_month.toFixed(1)}%/mo` : "—"} sub={m.trend?.direction} icon={<TrendingUp />} />
          <Kpi label="Days to limit" value={m.days_to_limit == null ? "n/a" : m.days_to_limit <= 0 ? "Reached" : fmtNum(m.days_to_limit)} tone={m.days_to_limit != null && m.days_to_limit < 90 ? "critical" : undefined} />
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Section title={`${m.name} history`} description="Daily average and peak against the licensed capacity">
          <div className="h-[290px]" role="img" aria-label={`${m.name} history`}><ResponsiveContainer><ComposedChart data={data} margin={{ left: -4, right: 8 }}>
            <defs><linearGradient id={`lg-${m.name}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#4589ff" stopOpacity={0.4} /><stop offset="100%" stopColor="#4589ff" stopOpacity={0.02} /></linearGradient></defs>
            <CartesianGrid {...gridProps} /><XAxis dataKey="ts" {...axisProps} tickFormatter={(t) => fmtDate(String(t), false)} minTickGap={40} /><YAxis {...axisProps} tickFormatter={(v) => fmtNum(v)} />
            <Tooltip content={<ChartTooltip labelFormatter={(l) => fmtDate(String(l), false)} />} /><RLegend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
            {m.licensed != null && <ReferenceLine y={m.licensed} stroke={sevColor("critical")} strokeDasharray="5 4" label={{ value: "Licensed", fill: sevColor("critical"), fontSize: 11, position: "insideTopRight" }} />}
            <Area type="monotone" dataKey="value" name="Average" stroke="#4589ff" fill={`url(#lg-${m.name})`} strokeWidth={2} /><Line type="monotone" dataKey="peak" name="Peak" stroke="#ff832b" strokeWidth={1.5} dot={false} />
          </ComposedChart></ResponsiveContainer></div>
        </Section>
        <Section title="Forecast" description="Linear projection from the observed trend">
          {forecast.length === 0 ? <p className="text-sm text-muted-foreground">Not enough history to forecast.</p> : (
            <table className="w-full text-sm"><thead><tr className="border-b text-left [&>th]:py-2"><th className="label-caps">Horizon</th><th className="label-caps text-right">Projected</th><th className="label-caps text-right">vs licence</th></tr></thead>
              <tbody>{m.forecast.map((f) => <tr key={f.months} className="border-b last:border-0 [&>td]:py-2.5"><td>{f.months} months</td><td className="text-right tabular-nums">{fmtNum(f.value)}</td><td className="text-right font-semibold tabular-nums" style={{ color: f.pct != null ? (f.pct >= 100 ? sevColor("critical") : f.pct >= 80 ? sevColor("high") : sevColor("ok")) : undefined }}>{f.pct != null ? `${f.pct.toFixed(0)}%` : "—"}</td></tr>)}</tbody></table>
          )}
          <p className="mt-3 border-t pt-3 text-xs leading-relaxed text-muted-foreground">{riskNarrative(m)}</p>
        </Section>
      </div>
    </div>
  );
}

export default function Licensing() {
  const { id, canEdit } = useAssessmentCtx();
  const q = useLicensing(id, true);
  const comments = useComments(id, "licensing");
  const save = useSaveComment(id);
  return (
    <div>
      <PageHeader title="Licensing" description="EPS and FPM consumption against licensed capacity, growth trend, forecast and utilisation risk." />
      <Async q={q} rows={3}>
        {({ licensing: l }) => (
          <div className="space-y-8">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi label="Utilisation risk" value={<Badge tone={riskTone(l.utilisation_risk)} dot className="!text-sm">{l.utilisation_risk}</Badge>} />
              <Kpi label="License expiry" value={l.expiry_days == null ? "—" : l.expiry_days < 0 ? "Expired" : `${l.expiry_days} days`} sub={fmtDate(l.expiry, false)} tone={l.expiry_days != null && l.expiry_days < 60 ? "high" : undefined} />
              <Kpi label="App framework" value={l.app_framework.licensed ?? "—"} sub="licensed applications" /><Kpi label="License type" value={l.license_type ?? "—"} />
            </div>
            {!l.has_data ? <div className="rounded-lg border border-dashed py-10 text-center text-sm text-muted-foreground">No licensing data found in the bundle.</div> : <>
              <section aria-label="EPS licensing"><h2 className="mb-3 text-sm font-semibold">Events per second (EPS)</h2><MetricBlock m={l.eps} /></section>
              <section aria-label="FPM licensing"><h2 className="mb-3 text-sm font-semibold">Flows per minute (FPM)</h2><MetricBlock m={l.fpm} /></section>
            </>}
            <Section title="Consultant notes" description="Included in the licensing section of the report.">
              <CommentBox label="Licensing comment" value={comments.data?.find((c) => c.target_key === "licensing")?.text ?? ""} readOnly={!canEdit} onSave={(text) => save.mutateAsync({ type: "licensing", key: "licensing", text })} />
            </Section>
          </div>
        )}
      </Async>
    </div>
  );
}
