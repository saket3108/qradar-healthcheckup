import { Search } from "lucide-react";
import { useState } from "react";
import { Async, CommentBox, Disclosure, EmptyState, KV, Kpi, PageHeader, RecoList, Section } from "@/components/common";
import { Donut, Legend } from "@/components/charts/ChartKit";
import { Badge, PriorityBadge, SeverityBadge, StatusBadge } from "@/components/ui/badges";
import { Input, Select } from "@/components/ui/primitives";
import { useAssessmentCtx } from "@/pages/AssessmentLayout";
import { useNotifications, useSaveComment } from "@/lib/queries";
import { fmtDate, sevColor } from "@/lib/utils";
import type { Notification } from "@/types";

function NotificationCard({ n, id, canEdit, open, onToggle }: { n: Notification; id: string; canEdit: boolean; open: boolean; onToggle: () => void }) {
  const save = useSaveComment(id);
  return (
    <Disclosure open={open} onToggle={onToggle}
      header={<div className="flex flex-wrap items-center gap-2.5"><SeverityBadge severity={n.effective_severity} /><PriorityBadge priority={n.priority} /><span className="min-w-0 flex-1 truncate text-sm font-medium" title={n.message}>{n.title || n.message}</span>
        {n.comment && <Badge tone="info">Commented</Badge>}<StatusBadge status={n.status} /><span className="text-xs text-muted-foreground">{fmtDate(n.timestamp)}</span></div>}>
      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-3.5">
          <KV label="Notification">{n.message}</KV>
          <div className="grid grid-cols-2 gap-3"><KV label="Severity">{n.effective_severity}{n.severity_raw && n.severity_raw.toLowerCase() !== n.effective_severity ? ` (QRadar reported: ${n.severity_raw})` : ""}</KV><KV label="Timestamp">{fmtDate(n.timestamp)}</KV><KV label="Current status">{n.status}</KV><KV label="Host / category">{n.host ?? "—"} · {n.domain}</KV></div>
          <KV label="Root cause">{n.root_cause}</KV>
          <KV label="Technical explanation">{n.technical_explanation}</KV>
          <KV label="Business impact">{n.business_impact}</KV>
          <KV label="Risk">{n.risk}</KV>
        </div>
        <div className="space-y-3.5">
          <KV label="Recommendation"><RecoList items={n.recommendation} /></KV>
          <KV label="IBM best practice">{n.best_practice}</KV>
          <CommentBox value={n.comment} readOnly={!canEdit} onSave={(text) => save.mutateAsync({ type: "notification", key: String(n.id), text })} />
        </div>
      </div>
    </Disclosure>
  );
}

export default function Notifications() {
  const { id, canEdit } = useAssessmentCtx();
  const [sev, setSev] = useState("");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const query = useNotifications(id, true, sev, q);
  return (
    <div>
      <PageHeader title="Notification Analysis" description="Every QRadar system notification from notification_view, enriched with root cause, business impact and IBM best practice." />
      <Async q={query} rows={2}>
        {(d) => (
          <div className="space-y-6">
            <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                <Kpi label="Total" value={d.total} />
                <Kpi label="Open" value={d.open} tone="high" />
                <Kpi label="Critical" value={d.by_severity.critical ?? 0} tone="critical" onClick={() => setSev(sev === "critical" ? "" : "critical")} />
                <Kpi label="High" value={d.by_severity.high ?? 0} tone="high" onClick={() => setSev(sev === "high" ? "" : "high")} />
                <Kpi label="Unmapped" value={d.unmapped} sub="No KB match" />
              </div>
              <Section title="By domain" bodyClassName="py-2">
                <div className="grid grid-cols-[110px_1fr] items-center gap-3">
                  <Donut height={110} data={Object.entries(d.by_domain).map(([name, value]) => ({ name, value }))} />
                  <Legend items={Object.entries(d.by_domain).slice(0, 5).map(([name, value], i) => ({ name, value, color: ["#4589ff", "#8a3ffc", "#33b1ff", "#08bdba", "#d12771"][i]! }))} />
                </div>
              </Section>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-[220px] max-w-sm flex-1"><Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" /><Input aria-label="Search notifications" className="pl-9" placeholder="Search notifications…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
              <Select aria-label="Filter by severity" value={sev} onChange={(e) => setSev(e.target.value)}>
                <option value="">All severities</option>{["critical", "high", "medium", "low", "info"].map((s) => <option key={s} value={s}>{s}</option>)}
              </Select>
              <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground"><span className="size-2 rounded-full" style={{ background: sevColor(sev || "info") }} />{d.items.length} shown</span>
            </div>
            {d.items.length === 0 ? <EmptyState title="No notifications match" description="Adjust the search or severity filter." /> : (
              <div className="space-y-2">{d.items.map((n) => <NotificationCard key={n.id} n={n} id={id} canEdit={canEdit} open={openId === n.id} onToggle={() => setOpenId(openId === n.id ? null : n.id)} />)}</div>
            )}
          </div>
        )}
      </Async>
    </div>
  );
}
