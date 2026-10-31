import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Async, CommentBox, EmptyState, Kpi, PageHeader, Section } from "@/components/common";
import { ChartTooltip, Donut, Legend, PALETTE, TreemapChart, axisProps, gridProps } from "@/components/charts/ChartKit";
import { Badge, SeverityBadge, StatusBadge } from "@/components/ui/badges";
import { Segmented } from "@/components/ui/tabs";
import { useAssessmentCtx } from "@/pages/AssessmentLayout";
import { useComments, useLogSourceAnalysis, useSaveComment } from "@/lib/queries";
import { fmtDate, fmtNum, sevColor, timeAgo } from "@/lib/utils";
import type { LogSourceSummary, WcAgent, WinCollectSummary } from "@/types";

export const PROTOCOL_GROUPS = ["Syslog", "TCP", "UDP", "TLS", "SNMP", "JDBC", "WinCollect", "AWS", "Azure", "Office365", "SFTP", "OPSEC", "LEEF", "REST API", "Universal DSM"];

export function generalRecommendation(ls: LogSourceSummary): string {
  const out: string[] = [];
  if (ls.error) out.push(`Investigate the ${ls.error} log source(s) in error state: verify credentials, network reachability and protocol configuration, then re-enable them.`);
  if (ls.silent_count) out.push(`${ls.silent_count} enabled log source(s) have stopped sending events. Confirm the source is still forwarding and add log source inactivity alerts.`);
  if (ls.unparsed_types) out.push(`${ls.unparsed_types} log source type(s) show parsing or unknown-event symptoms. Validate DSM versions and consider custom DSM extensions.`);
  if (ls.disabled) out.push(`Review ${ls.disabled} disabled log source(s) and remove those no longer required to simplify the deployment.`);
  const top = ls.top_eps.slice(0, 3);
  if (top.length) out.push(`The highest-volume sources are ${top.map((t) => `${t.name} (${fmtNum(t.eps)} EPS)`).join(", ")}; review them for noise reduction and event coalescing.`);
  out.push("Follow IBM guidance: keep log source names consistent, group by log source extension, and periodically audit sources against the asset inventory.");
  return out.join("\n");
}
export function wincollectRecommendation(wc: WinCollectSummary): string {
  const out: string[] = [];
  if (wc.outdated) out.push(`Upgrade the ${wc.outdated} outdated WinCollect agent(s) to ${wc.latest_seen ?? "the latest supported version"} using the WinCollect agent update workflow.`);
  if (wc.communication_problems.length) out.push(`Resolve connectivity for ${wc.communication_problems.length} agent(s) not checking in (verify service state, firewall rules on TCP 514/8413 and certificate validity).`);
  if (wc.config_issues.length) out.push(`Fix configuration errors reported by ${wc.config_issues.length} agent(s) and redeploy the agent configuration from the Console.`);
  if (wc.standalone) out.push(`Consider migrating ${wc.standalone} standalone agent(s) to managed mode so configuration and upgrades are centrally controlled.`);
  if (!out.length) out.push("WinCollect agents are healthy. Continue to review versions quarterly.");
  return out.join("\n");
}

function useRecoComment(id: string, key: string, fallback: string) {
  const c = useComments(id);
  const save = useSaveComment(id);
  const type = key === "wincollect-recommendation" ? "wincollect" : "logsource";
  const stored = c.data?.find((x) => x.target_type === type && x.target_key === key)?.text;
  return { value: stored ?? fallback, save: (text: string) => save.mutateAsync({ type, key, text }), loading: c.isLoading, edited: stored != null };
}

function ProtocolCharts({ ls }: { ls: LogSourceSummary }) {
  const [view, setView] = useState("bar");
  const [by, setBy] = useState<"count" | "eps">("count");
  const data = useMemo(() => ls.protocols.map((p) => ({ name: p.name, value: by === "count" ? p.count : p.eps, count: p.count, eps: p.eps })), [ls.protocols, by]);
  return (
    <Section title="Protocol analysis" description="Log sources grouped by integration protocol"
      actions={<div className="flex gap-2"><Segmented layoutId="proto-by" value={by} onChange={(v) => setBy(v as "count" | "eps")} items={[{ key: "count", label: "Count" }, { key: "eps", label: "EPS" }]} />
        <Segmented layoutId="proto-view" value={view} onChange={setView} items={[{ key: "bar", label: "Bar" }, { key: "pie", label: "Pie" }, { key: "tree", label: "Treemap" }]} /></div>}>
      {data.length === 0 ? <EmptyState title="No protocol data" /> : view === "bar" ? (
        <div className="h-[300px]" role="img" aria-label="Log sources by protocol"><ResponsiveContainer><BarChart data={data} margin={{ left: -10, right: 8 }}>
          <CartesianGrid {...gridProps} /><XAxis dataKey="name" {...axisProps} interval={0} angle={-25} textAnchor="end" height={60} /><YAxis {...axisProps} />
          <Tooltip content={<ChartTooltip />} cursor={{ fill: "hsl(var(--accent))" }} /><Bar dataKey="value" name={by === "count" ? "Log sources" : "EPS"} radius={[6, 6, 0, 0]}>{data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}</Bar>
        </BarChart></ResponsiveContainer></div>
      ) : view === "pie" ? (
        <div className="grid items-center gap-4 sm:grid-cols-[1fr_260px]"><Donut height={280} data={data.map((d) => ({ name: d.name, value: d.value }))} centerLabel={by === "count" ? "Log sources" : "EPS"} /><Legend items={data.map((d, i) => ({ name: d.name, value: d.value, color: PALETTE[i % PALETTE.length]! }))} /></div>
      ) : <TreemapChart data={data.map((d) => ({ name: d.name, size: d.value }))} height={300} />}
    </Section>
  );
}

function LogSourcePart({ ls, id, canEdit }: { ls: LogSourceSummary; id: string; canEdit: boolean }) {
  const reco = useRecoComment(id, "general-recommendation", generalRecommendation(ls));
  const [sev, setSev] = useState("all");
  const rows = ls.problematic.filter((p) => sev === "all" || p.severity === sev);
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <Kpi label="Total" value={fmtNum(ls.total)} /><Kpi label="Active" value={fmtNum(ls.enabled)} tone="ok" /><Kpi label="Disabled" value={fmtNum(ls.disabled)} /><Kpi label="Error" value={fmtNum(ls.error)} tone="critical" />
        <Kpi label="Unknown" value={fmtNum(ls.unknown)} /><Kpi label="Total EPS" value={fmtNum(ls.total_eps)} /><Kpi label="Average EPS" value={fmtNum(ls.average_eps, 1)} sub="per log source" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Top EPS sources" bodyClassName="p-0"><table className="w-full text-sm"><thead><tr className="border-b text-left [&>th]:px-4 [&>th]:py-2"><th className="label-caps">Name</th><th className="label-caps">Type</th><th className="label-caps">Protocol</th><th className="label-caps text-right">EPS</th></tr></thead>
          <tbody>{ls.top_eps.slice(0, 10).map((t) => <tr key={t.name} className="border-b last:border-0 [&>td]:px-4 [&>td]:py-2"><td className="font-medium">{t.name}</td><td className="text-muted-foreground">{t.type}</td><td>{t.protocol}</td><td className="text-right tabular-nums">{fmtNum(t.eps, 1)}</td></tr>)}</tbody></table></Section>
        <ProtocolCharts ls={ls} />
      </div>
      <Section title="Problematic log sources" description={`${ls.problematic.length} flagged · ${ls.silent_count} silent`}
        actions={<Segmented layoutId="prob-sev" value={sev} onChange={setSev} items={[{ key: "all", label: "All" }, { key: "critical", label: "Critical" }, { key: "high", label: "High" }, { key: "medium", label: "Medium" }]} />} bodyClassName="overflow-x-auto p-0">
        {rows.length === 0 ? <div className="p-4"><EmptyState title="No problematic log sources" /></div> : (
          <table className="w-full min-w-[820px] text-sm"><thead><tr className="border-b text-left [&>th]:px-4 [&>th]:py-2.5">{["Name", "Type", "Protocol", "Status", "EPS", "Last event received", "Severity", "Reason"].map((h) => <th key={h} className="label-caps">{h}</th>)}</tr></thead>
            <tbody>{rows.map((p) => <tr key={p.id} className="border-b last:border-0 [&>td]:px-4 [&>td]:py-2.5 hover:bg-accent/40"><td className="font-medium">{p.name}</td><td className="text-muted-foreground">{p.type}</td><td className="text-xs">{p.protocol}</td><td><StatusBadge status={p.status} /></td>
              <td className="tabular-nums">{fmtNum(p.eps, 1)}</td><td className="text-xs" title={fmtDate(p.last_event)}>{timeAgo(p.last_event)}</td><td><SeverityBadge severity={p.severity} /></td><td className="max-w-[260px] text-xs text-muted-foreground">{p.reasons.join("; ")}</td></tr>)}</tbody></table>
        )}
      </Section>
      <Section title="General recommendation" description="AI-generated from the analysis above. Edit it to tailor the message for your customer."><CommentBox label="Recommendation (editable)" value={reco.value} readOnly={!canEdit} onSave={reco.save} /></Section>
    </div>
  );
}

function AgentTable({ title, rows, empty }: { title: string; rows: WcAgent[]; empty: string }) {
  return (
    <Section title={title} description={`${rows.length} agent${rows.length === 1 ? "" : "s"}`} bodyClassName="max-h-[320px] overflow-auto p-0">
      {rows.length === 0 ? <div className="p-4 text-sm text-muted-foreground">{empty}</div> : (
        <table className="w-full text-sm"><thead className="sticky top-0 bg-card"><tr className="border-b text-left [&>th]:px-4 [&>th]:py-2"><th className="label-caps">Agent</th><th className="label-caps">IP</th><th className="label-caps">Version</th><th className="label-caps">Last check-in</th><th className="label-caps">Detail</th></tr></thead>
          <tbody>{rows.map((a) => <tr key={a.id} className="border-b last:border-0 [&>td]:px-4 [&>td]:py-2"><td className="font-medium">{a.name}</td><td className="font-mono text-xs">{a.ip ?? "—"}</td><td>{a.version ?? "—"}</td><td className="text-xs">{timeAgo(a.last_checkin)}</td><td className="text-xs text-muted-foreground">{a.reason ?? a.config_error ?? a.status}</td></tr>)}</tbody></table>
      )}
    </Section>
  );
}

function WinCollectPart({ wc, id, canEdit }: { wc: WinCollectSummary; id: string; canEdit: boolean }) {
  const reco = useRecoComment(id, "wincollect-recommendation", wincollectRecommendation(wc));
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Kpi label="Total agents" value={fmtNum(wc.total)} /><Kpi label="Managed" value={fmtNum(wc.managed)} tone="ok" /><Kpi label="Standalone" value={fmtNum(wc.standalone)} /><Kpi label="Unmanaged" value={fmtNum(wc.unmanaged)} tone="medium" /><Kpi label="Disconnected" value={fmtNum(wc.disconnected)} tone="critical" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Version distribution" description={wc.latest_seen ? `Latest version seen: ${wc.latest_seen}` : undefined}>
          <div className="h-[260px]" role="img" aria-label="WinCollect version distribution"><ResponsiveContainer><BarChart data={wc.versions} margin={{ left: -10 }}>
            <CartesianGrid {...gridProps} /><XAxis dataKey="version" {...axisProps} /><YAxis {...axisProps} allowDecimals={false} /><Tooltip content={<ChartTooltip />} cursor={{ fill: "hsl(var(--accent))" }} />
            <Bar dataKey="count" name="Agents" radius={[6, 6, 0, 0]}>{wc.versions.map((v, i) => <Cell key={i} fill={v.version === wc.latest_seen ? sevColor("ok") : sevColor("high")} />)}</Bar></BarChart></ResponsiveContainer></div>
        </Section>
        <Section title="Agent health"><div className="grid items-center gap-4 sm:grid-cols-2"><Donut data={[{ name: "Connected", value: wc.connected }, { name: "Disconnected", value: wc.disconnected }, { name: "Error", value: wc.error }].filter((d) => d.value)} centerLabel="Agents" colors={[sevColor("ok"), sevColor("high"), sevColor("critical")]} />
          <Legend items={[{ name: "Connected", value: wc.connected, color: sevColor("ok") }, { name: "Disconnected", value: wc.disconnected, color: sevColor("high") }, { name: "Error", value: wc.error, color: sevColor("critical") }, { name: "Outdated version", value: wc.outdated, color: sevColor("medium") }]} /></div></Section>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <AgentTable title="Old versions" rows={wc.old_versions} empty="All agents run a current version." />
        <AgentTable title="Communication problems" rows={wc.communication_problems} empty="All agents are checking in." />
        <AgentTable title="Configuration issues" rows={wc.config_issues} empty="No configuration errors reported." />
        <AgentTable title="Deployment problems" rows={wc.deployment_problems} empty="No deployment problems detected." />
      </div>
      <Section title="WinCollect recommendations" description="Generated from agent data. Editable."><CommentBox label="Recommendation (editable)" value={reco.value} readOnly={!canEdit} onSave={reco.save} /></Section>
    </div>
  );
}

export default function LogSources() {
  const { id, canEdit } = useAssessmentCtx();
  const q = useLogSourceAnalysis(id, true);
  const [tab, setTab] = useState("ls");
  return (
    <div>
      <PageHeader title="Log Source Analysis" description="Collection health, protocol mix and WinCollect agent status."
        actions={<Segmented layoutId="ls-tab" value={tab} onChange={setTab} items={[{ key: "ls", label: "Log sources" }, { key: "wc", label: "WinCollect", badge: q.data ? <Badge tone="neutral">{q.data.wincollect.total}</Badge> : undefined }]} />} />
      <Async q={q} rows={3}>{(d) => (tab === "ls" ? <LogSourcePart ls={d.logsources} id={id} canEdit={canEdit} /> : <WinCollectPart wc={d.wincollect} id={id} canEdit={canEdit} />)}</Async>
    </div>
  );
}
