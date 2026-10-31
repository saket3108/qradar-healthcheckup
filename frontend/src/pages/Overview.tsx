import { Cpu, HardDrive, MemoryStick, Network as NetIcon, RefreshCw, Server } from "lucide-react";
import { Async, Kpi, PageHeader, Section } from "@/components/common";
import { SemiGauge, Meter } from "@/components/charts/gauges";
import { Donut, Legend, PALETTE } from "@/components/charts/ChartKit";
import { Badge, StatusBadge } from "@/components/ui/badges";
import { useAssessmentCtx } from "@/pages/AssessmentLayout";
import { useOverview, usePerformance } from "@/lib/queries";
import { fmtBytes, fmtDate, fmtNum, scoreColor, sevColor } from "@/lib/utils";
import type { Environment, PerfHost, TopoNode } from "@/types";

const Row = ({ k, v }: { k: string; v: React.ReactNode }) => (
  <div className="flex items-center justify-between gap-3 border-b py-2 text-sm last:border-0"><span className="text-muted-foreground">{k}</span><span className="text-right font-medium">{v ?? "—"}</span></div>
);

function EnvCard({ e }: { e: Environment }) {
  return (
    <Section title="Environment information">
      <Row k="QRadar version" v={e.version} /><Row k="Fix pack" v={e.fix_pack} /><Row k="Build" v={e.build} /><Row k="Deployment type" v={e.deployment_type} />
      <Row k="Installation type" v={e.install_type} /><Row k="Software / hardware" v={e.software_hardware} /><Row k="Platform" v={[e.manufacturer, e.platform].filter(Boolean).join(" · ") || null} />
      <Row k="Managed hosts" v={e.hosts} /><Row k="Console" v={e.console} />
      {e.supported_line === false && <div role="alert" className="mt-2"><Badge tone="critical">Version is outside the supported QRadar 7.4 / 7.5 line</Badge></div>}
    </Section>
  );
}

function Appliances({ nodes, perf }: { nodes: TopoNode[]; perf?: Record<string, PerfHost> }) {
  return (
    <Section title="Appliance information" description="Per managed host" bodyClassName="overflow-x-auto p-0">
      <table className="w-full min-w-[900px] text-sm">
        <thead><tr className="border-b text-left [&>th]:px-4 [&>th]:py-2.5"><th className="label-caps">Hostname</th><th className="label-caps">IP address</th><th className="label-caps">Role</th><th className="label-caps">CPU</th><th className="label-caps">RAM</th><th className="label-caps">Disk</th><th className="label-caps">Managed host ID</th><th className="label-caps">Status</th></tr></thead>
        <tbody>
          {nodes.map((n) => {
            const hw = Object.values(perf ?? {}).find((p) => p.identity.hostname === n.hostname)?.hardware;
            const cpu = n.cpu_cores ?? hw?.cpus, mem = n.memory_bytes ?? hw?.memory_bytes, disk = n.disk_bytes ?? hw?.disk_bytes;
            return (
              <tr key={n.id} className="border-b last:border-0 [&>td]:px-4 [&>td]:py-2.5 hover:bg-accent/40">
                <td className="font-medium">{n.hostname}</td><td className="font-mono text-xs">{n.ip ?? "—"}</td><td><Badge tone="primary">{n.role}</Badge></td>
                <td className="tabular-nums">{cpu ? `${cpu} cores` : "—"}</td><td className="tabular-nums">{fmtBytes(mem, 0)}</td><td className="tabular-nums">{fmtBytes(disk, 1)}</td>
                <td className="font-mono text-xs">{n.id}</td><td><StatusBadge status={n.status} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Section>
  );
}

export default function Overview() {
  const { id } = useAssessmentCtx();
  const q = useOverview(id, true);
  const perf = usePerformance(id, true);
  return (
    <div>
      <PageHeader title="Overview" description="Environment, licensing and summaries across every analysed dataset." />
      <Async q={q} rows={3}>
        {(o) => {
          const lic = o.licensing, ls = o.logsources, wc = o.wincollect, ap = o.applications, au = o.autoupdate;
          const sev = o.scores.overall.severity_totals;
          const hosts = Object.values(perf.data?.hosts ?? {});
          const avg = (f: (h: PerfHost) => number | undefined) => { const v = hosts.map(f).filter((x): x is number => typeof x === "number"); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
          const cpuAvg = avg((h) => h.sar_summary.cpu?.avg), memAvg = avg((h) => h.sar_summary.memory?.avg), swapAvg = avg((h) => h.sar_summary.swap?.avg);
          const diskMax = hosts.flatMap((h) => h.df.map((d) => d.use_pct)).reduce((a, b) => Math.max(a, b), 0);
          const rx = avg((h) => h.sar_summary.network?.rx_kBps_avg), tx = avg((h) => h.sar_summary.network?.tx_kBps_avg);
          return (
            <div className="space-y-6">
              <div className="grid gap-4 lg:grid-cols-2"><EnvCard e={o.environment} />
                <Section title="License information" description={lic.expiry_days != null ? `${lic.license_type ?? "License"} ${lic.expiry_days < 0 ? "expired" : `expires in ${lic.expiry_days} days`} (${fmtDate(lic.expiry, false)})` : undefined}>
                  <div className="grid grid-cols-2 gap-2">
                    <SemiGauge size={200} value={lic.eps.consumption_pct} label="EPS license" sublabel={`${fmtNum(lic.eps.current)} of ${fmtNum(lic.eps.licensed)} EPS`} />
                    <SemiGauge size={200} value={lic.fpm.consumption_pct} label="FPM license" sublabel={`${fmtNum(lic.fpm.current)} of ${fmtNum(lic.fpm.licensed)} FPM`} />
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-3 border-t pt-3 text-center">
                    <div><div className="label-caps">App framework</div><div className="mt-1 font-semibold">{lic.app_framework.licensed ?? "—"}</div></div>
                    <div><div className="label-caps">EPS usage</div><div className="mt-1 font-semibold tabular-nums">{lic.eps.consumption_pct != null ? `${lic.eps.consumption_pct.toFixed(1)}%` : "—"}</div></div>
                    <div><div className="label-caps">FPM usage</div><div className="mt-1 font-semibold tabular-nums">{lic.fpm.consumption_pct != null ? `${lic.fpm.consumption_pct.toFixed(1)}%` : "—"}</div></div>
                  </div>
                </Section>
              </div>

              <Appliances nodes={o.topology.nodes} perf={perf.data?.hosts} />

              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <Section title="Log sources"><div className="grid grid-cols-2 gap-3"><Kpi label="Total" value={fmtNum(ls.total)} /><Kpi label="Enabled" value={fmtNum(ls.enabled)} tone="ok" /><Kpi label="Disabled" value={fmtNum(ls.disabled)} /><Kpi label="Error" value={fmtNum(ls.error)} tone="critical" /></div><div className="mt-2 text-xs text-muted-foreground">Unknown: {ls.unknown} · {fmtNum(ls.total_eps)} EPS total</div></Section>
                <Section title="WinCollect"><div className="grid grid-cols-2 gap-3"><Kpi label="Agents" value={fmtNum(wc.total)} /><Kpi label="Managed" value={fmtNum(wc.managed)} tone="ok" /><Kpi label="Standalone" value={fmtNum(wc.standalone)} /><Kpi label="Outdated" value={fmtNum(wc.outdated)} tone="high" /></div><div className="mt-2 text-xs text-muted-foreground">Error/disconnected: {wc.error}/{wc.disconnected}</div></Section>
                <Section title="Notifications"><div className="grid grid-cols-2 gap-3"><Kpi label="Critical" value={sev.critical} tone="critical" /><Kpi label="High" value={sev.high} tone="high" /><Kpi label="Medium" value={sev.medium} tone="medium" /><Kpi label="Low" value={sev.low} tone="low" /></div><div className="mt-2 text-xs text-muted-foreground">Finding counts by severity</div></Section>
                <Section title="Applications"><div className="grid grid-cols-2 gap-3"><Kpi label="Running" value={ap.running} tone="ok" /><Kpi label="Stopped" value={ap.stopped} /><Kpi label="Degraded" value={ap.degraded} tone="medium" /><Kpi label="Error" value={ap.error} tone="critical" /></div></Section>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <Section title="Auto update summary" actions={<RefreshCw className="size-4 text-muted-foreground" />}>
                  <Row k="Current version" v={au.current_version ?? o.environment.version} /><Row k="Latest version" v={au.latest_version ?? "Unknown"} /><Row k="Pending updates" v={au.pending_updates} />
                  <Row k="Repository connectivity" v={<Badge tone={au.repo_reachable ? "ok" : "critical"} dot>{au.repo_reachable ? "Reachable" : "Unreachable / failing"}</Badge>} />
                  <Row k="Last run" v={au.last_run ? `${fmtDate(au.last_run)} (${au.last_status ?? "n/a"})` : "—"} />
                  {au.history.slice(0, 3).map((h, i) => <div key={i} className="mt-2 rounded-md bg-muted/50 px-3 py-2 text-xs"><StatusBadge status={h.status} /> <span className="ml-1 text-muted-foreground">{h.type} {h.version} · {h.message}</span></div>)}
                </Section>
                <Section title="Hardware summary" description="Average across hosts from SAR / system data">
                  {hosts.length === 0 ? <div className="text-sm text-muted-foreground">No performance data available.</div> : (
                    <div className="grid gap-4 sm:grid-cols-2">
                      {[{ icon: <Cpu />, label: "CPU", v: cpuAvg }, { icon: <MemoryStick />, label: "Memory", v: memAvg }, { icon: <HardDrive />, label: "Disk (worst mount)", v: diskMax || null }, { icon: <Server />, label: "Swap", v: swapAvg }].map((m) => (
                        <div key={m.label}><div className="mb-1.5 flex items-center justify-between text-sm"><span className="flex items-center gap-1.5 text-muted-foreground [&_svg]:size-4">{m.icon}{m.label}</span><span className="font-semibold tabular-nums" style={{ color: m.v != null ? scoreColor(100 - m.v) : undefined }}>{m.v != null ? `${m.v.toFixed(0)}%` : "—"}</span></div><Meter value={m.v ?? 0} color={m.v != null ? scoreColor(100 - m.v) : undefined} /></div>
                      ))}
                      <div className="sm:col-span-2"><div className="flex items-center gap-1.5 text-sm text-muted-foreground"><NetIcon className="size-4" />Network (avg per host)</div><div className="mt-1 text-sm font-medium tabular-nums">↓ {fmtBytes((rx ?? 0) * 1024)}/s &nbsp; ↑ {fmtBytes((tx ?? 0) * 1024)}/s</div></div>
                    </div>
                  )}
                </Section>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <Section title="Log source status distribution"><div className="grid items-center gap-4 sm:grid-cols-2">
                  <Donut centerLabel="Log sources" data={[{ name: "Enabled", value: ls.enabled - ls.error }, { name: "Error", value: ls.error }, { name: "Disabled", value: ls.disabled }, { name: "Unknown", value: ls.unknown }].filter((d) => d.value > 0)} colors={[sevColor("ok"), sevColor("critical"), sevColor("unknown"), sevColor("info")]} />
                  <Legend items={[{ name: "Healthy", value: ls.enabled - ls.error, color: sevColor("ok") }, { name: "Error", value: ls.error, color: sevColor("critical") }, { name: "Disabled", value: ls.disabled, color: sevColor("unknown") }, { name: "Unknown", value: ls.unknown, color: sevColor("info") }]} /></div></Section>
                <Section title="Top log source types by EPS"><Legend items={ls.types.slice(0, 8).map((t, i) => ({ name: t.name, value: `${fmtNum(t.eps)} EPS`, color: PALETTE[i % PALETTE.length]! }))} /></Section>
              </div>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
