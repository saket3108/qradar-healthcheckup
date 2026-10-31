import { useMemo, useState } from "react";
import { Async, CommentBox, Disclosure, Kpi, PageHeader, RecoList, KV, Section } from "@/components/common";
import { Meter } from "@/components/charts/gauges";
import { Donut, Legend } from "@/components/charts/ChartKit";
import { Badge, PriorityBadge, SeverityBadge, StatusBadge } from "@/components/ui/badges";
import { Segmented } from "@/components/ui/tabs";
import { useAssessmentCtx } from "@/pages/AssessmentLayout";
import { useApplications, useSaveComment } from "@/lib/queries";
import { sevColor, sevRank } from "@/lib/utils";
import type { AppItem } from "@/types";

const hostSev = (a: AppItem) => a.issues.reduce((m, i) => (sevRank(i.severity) < sevRank(m) ? i.severity : m), "info" as string);
const metricColor = (v: number | null) => (v == null ? undefined : v >= 90 ? sevColor("critical") : v >= 75 ? sevColor("high") : v >= 60 ? sevColor("medium") : sevColor("ok"));

function AppCard({ a, id, canEdit, open, onToggle }: { a: AppItem; id: string; canEdit: boolean; open: boolean; onToggle: () => void }) {
  const save = useSaveComment(id);
  return (
    <Disclosure open={open} onToggle={onToggle}
      header={<div className="grid grid-cols-2 items-center gap-x-4 gap-y-2 md:grid-cols-[1.4fr_.7fr_1fr_.8fr_1fr_1fr_auto]">
        <div className="min-w-0"><div className="truncate text-sm font-semibold">{a.name}</div><div className="truncate text-xs text-muted-foreground">{a.host ?? "unknown host"}</div></div>
        <div className="text-xs"><div className="label-caps">Version</div><span className="font-mono">{a.version ?? "—"}</span>{a.latest_version && a.latest_version !== a.version && <span className="ml-1 text-sev-medium">→ {a.latest_version}</span>}</div>
        <div><StatusBadge status={a.status} /></div>
        <div className="text-xs"><div className="label-caps">Restarts</div><span className={a.restart_count && a.restart_count > 3 ? "font-semibold text-sev-critical" : ""}>{a.restart_count ?? "—"}</span></div>
        <div className="text-xs"><div className="label-caps">CPU {a.cpu_pct != null ? `${a.cpu_pct.toFixed(0)}%` : "—"}</div><Meter value={a.cpu_pct ?? 0} color={metricColor(a.cpu_pct)} /></div>
        <div className="text-xs"><div className="label-caps">Memory {a.memory_pct != null ? `${a.memory_pct.toFixed(0)}%` : "—"}</div><Meter value={a.memory_pct ?? 0} color={metricColor(a.memory_pct)} /></div>
        <div className="flex items-center gap-1.5">{a.issues.length ? <SeverityBadge severity={hostSev(a)} /> : <Badge tone="ok" dot>Healthy</Badge>}<PriorityBadge priority={a.priority} /></div>
      </div>}>
      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-3.5">
          <KV label="Observation">{a.observation}</KV>
          {a.issues.length > 0 && <KV label="Detected issues"><ul className="space-y-1">{a.issues.map((i, k) => <li key={k} className="flex items-start gap-2 text-sm"><SeverityBadge severity={i.severity} /><span className="mt-0.5">{i.observation}</span></li>)}</ul></KV>}
          {a.last_error && <KV label="Last error"><code className="block rounded bg-muted px-2 py-1.5 text-xs">{a.last_error}</code></KV>}
          <KV label="Impact">{a.impact}</KV>
        </div>
        <div className="space-y-3.5">
          <KV label="Recommendation"><RecoList items={a.recommendation} /></KV>
          <KV label="IBM best practice">{a.best_practice}</KV>
          <CommentBox value={a.comment ?? ""} readOnly={!canEdit} onSave={(text) => save.mutateAsync({ type: "application", key: a.id, text })} />
        </div>
      </div>
    </Disclosure>
  );
}

export default function Applications() {
  const { id, canEdit } = useAssessmentCtx();
  const q = useApplications(id, true);
  const [filter, setFilter] = useState("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const items = useMemo(() => {
    const xs = (q.data?.items ?? []).filter((a) => filter === "all" || (filter === "issues" ? a.issues.length > 0 : a.status === filter));
    return [...xs].sort((a, b) => sevRank(hostSev(a)) - sevRank(hostSev(b)) || a.name.localeCompare(b.name));
  }, [q.data, filter]);
  return (
    <div>
      <PageHeader title="Application Analysis" description="Installed applications and their runtime instances from the App Framework, with automatic detection of restart loops, outdated versions, resource and permission problems." />
      <Async q={q} rows={2}>
        {(d) => (
          <div className="space-y-6">
            <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Kpi label="Running" value={d.running} tone="ok" /><Kpi label="Stopped" value={d.stopped} /><Kpi label="Degraded" value={d.degraded} tone="medium" /><Kpi label="Error" value={d.error} tone="critical" />
                <Kpi label="Restart loops" value={d.restart_loops} tone={d.restart_loops ? "critical" : undefined} /><Kpi label="Outdated" value={d.outdated} tone={d.outdated ? "medium" : undefined} /><Kpi label="With issues" value={d.with_issues} tone={d.with_issues ? "high" : undefined} /><Kpi label="Total" value={d.total} />
              </div>
              <Section title="Status distribution" bodyClassName="py-1"><div className="grid grid-cols-[120px_1fr] items-center gap-3"><Donut height={120} data={[{ name: "Running", value: d.running }, { name: "Degraded", value: d.degraded }, { name: "Error", value: d.error }, { name: "Stopped", value: d.stopped }].filter((x) => x.value)} colors={[sevColor("ok"), sevColor("medium"), sevColor("critical"), sevColor("unknown")]} />
                <Legend items={[{ name: "Running", value: d.running, color: sevColor("ok") }, { name: "Degraded", value: d.degraded, color: sevColor("medium") }, { name: "Error", value: d.error, color: sevColor("critical") }, { name: "Stopped", value: d.stopped, color: sevColor("unknown") }]} /></div></Section>
            </div>
            <Segmented layoutId="app-filter" value={filter} onChange={setFilter} items={[{ key: "all", label: "All" }, { key: "issues", label: "With issues" }, { key: "running", label: "Running" }, { key: "degraded", label: "Degraded" }, { key: "error", label: "Error" }, { key: "stopped", label: "Stopped" }]} />
            <div className="space-y-2">{items.length === 0 ? <div className="rounded-lg border border-dashed py-10 text-center text-sm text-muted-foreground">No applications match this filter.</div> : items.map((a) => <AppCard key={a.id} a={a} id={id} canEdit={canEdit} open={openId === a.id} onToggle={() => setOpenId(openId === a.id ? null : a.id)} />)}</div>
          </div>
        )}
      </Async>
    </div>
  );
}
