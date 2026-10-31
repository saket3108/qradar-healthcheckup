import { useMemo, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend as RLegend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Cpu, Gauge as GaugeIcon, HardDrive, MemoryStick, Network as NetIcon, Activity } from "lucide-react";
import { Async, Disclosure, EmptyState, KV, Kpi, PageHeader, RecoList, Section } from "@/components/common";
import { ChartTooltip, axisProps, gridProps } from "@/components/charts/ChartKit";
import { Meter, SemiGauge } from "@/components/charts/gauges";
import { PriorityBadge, SeverityBadge } from "@/components/ui/badges";
import { Select } from "@/components/ui/primitives";
import { Segmented } from "@/components/ui/tabs";
import { useAssessmentCtx } from "@/pages/AssessmentLayout";
import { usePerformance } from "@/lib/queries";
import { fmtBytes, fmtNum, scoreColor, sevColor, sevRank } from "@/lib/utils";
import type { DiskStat, IfaceStat, PerfAssessment, PerfHost } from "@/types";

const hhmm = (ts: string | number) => { const d = new Date(String(ts)); return isNaN(d.getTime()) ? String(ts) : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); };
const C = { primary: "#4589ff", violet: "#8a3ffc", cyan: "#33b1ff", teal: "#08bdba", orange: "#ff832b", red: "#fa4d56", yellow: "#f1c21b" };

function Grad({ id, color }: { id: string; color: string }) {
  return <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={0.45} /><stop offset="100%" stopColor={color} stopOpacity={0.02} /></linearGradient></defs>;
}

function TopProcs({ rows, metric }: { rows: PerfHost["top_cpu"]; metric: "cpu" | "mem" }) {
  const data = rows.slice(0, 10).map((r) => ({ name: r.command, value: r[metric], rss: r.rss_kb }));
  if (!data.length) return <EmptyState title="No process data" />;
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div className="space-y-2" role="img" aria-label={`Top ${metric === "cpu" ? "CPU" : "memory"} processes`}>
      {data.map((d, i) => (
        <div key={d.name + i} className="grid grid-cols-[110px_1fr_70px] items-center gap-3 text-sm">
          <span className="truncate font-mono text-xs" title={d.name}>{d.name}</span>
          <div className="h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full" style={{ width: `${(d.value / max) * 100}%`, background: `linear-gradient(90deg, ${C.primary}, ${C.violet})` }} /></div>
          <span className="text-right text-xs tabular-nums">{d.value.toFixed(1)}%{metric === "mem" ? <span className="block text-[10px] text-muted-foreground">{fmtBytes(d.rss * 1024, 0)}</span> : null}</span>
        </div>
      ))}
    </div>
  );
}

function CpuSection({ h }: { h: PerfHost }) {
  const s = h.sar_summary.cpu, series = h.series.cpu ?? [];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4"><Kpi label="Avg CPU" value={s ? `${s.avg.toFixed(0)}%` : "—"} tone={s && s.avg >= 85 ? "critical" : s && s.avg >= 70 ? "medium" : "ok"} icon={<Cpu />} /><Kpi label="Peak CPU" value={s ? `${s.max.toFixed(0)}%` : "—"} /><Kpi label="I/O wait (avg)" value={s ? `${s.iowait_avg.toFixed(1)}%` : "—"} tone={s && s.iowait_avg >= 10 ? "high" : undefined} /><Kpi label="Saturation" value={s ? `${s.saturation_pct.toFixed(0)}%` : "—"} sub="of samples ≥ 90% busy" tone={s && s.saturation_pct >= 25 ? "critical" : undefined} /></div>
      <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Section title="CPU utilisation trend" description="User / system / I/O wait (stacked)">
          <div className="h-[280px]" role="img" aria-label="CPU utilisation trend"><ResponsiveContainer><AreaChart data={series} margin={{ left: -10, right: 8 }}>
            <Grad id="gu" color={C.primary} /><Grad id="gs" color={C.violet} /><Grad id="gw" color={C.orange} />
            <CartesianGrid {...gridProps} /><XAxis dataKey="ts" tickFormatter={hhmm} {...axisProps} minTickGap={50} /><YAxis {...axisProps} domain={[0, 100]} unit="%" />
            <Tooltip content={<ChartTooltip unit="%" labelFormatter={(l) => hhmm(l)} />} /><RLegend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
            <ReferenceLine y={85} stroke={C.red} strokeDasharray="4 4" label={{ value: "85%", fill: C.red, fontSize: 10, position: "right" }} />
            <Area type="monotone" dataKey="user" name="User" stackId="1" stroke={C.primary} fill="url(#gu)" strokeWidth={1.5} /><Area type="monotone" dataKey="system" name="System" stackId="1" stroke={C.violet} fill="url(#gs)" strokeWidth={1.5} /><Area type="monotone" dataKey="iowait" name="I/O wait" stackId="1" stroke={C.orange} fill="url(#gw)" strokeWidth={1.5} />
          </AreaChart></ResponsiveContainer></div>
        </Section>
        <Section title="Top 10 CPU processes"><TopProcs rows={h.top_cpu} metric="cpu" /></Section>
      </div>
    </div>
  );
}

function MemorySection({ h }: { h: PerfHost }) {
  const s = h.sar_summary.memory, sw = h.sar_summary.swap, series = h.series.memory ?? [];
  const m = h.memory;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4"><Kpi label="Avg memory used" value={s ? `${s.avg.toFixed(0)}%` : "—"} icon={<MemoryStick />} tone={s && s.avg >= 90 ? "critical" : s && s.avg >= 80 ? "high" : "ok"} /><Kpi label="Peak memory" value={s ? `${s.max.toFixed(0)}%` : "—"} /><Kpi label="Swap used (avg)" value={sw ? `${sw.avg.toFixed(0)}%` : "—"} tone={sw && sw.avg >= 20 ? "high" : undefined} /><Kpi label="Total / available" value={m ? `${fmtBytes(m.total, 0)} / ${fmtBytes(m.available, 0)}` : "—"} /></div>
      <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Section title="Memory utilisation trend" description="Memory pressure is highlighted above 90%">
          <div className="h-[260px]" role="img" aria-label="Memory utilisation trend"><ResponsiveContainer><ComposedChart data={series.map((p, i) => ({ ...p, swap: h.series.swap?.[i]?.used_pct }))} margin={{ left: -10, right: 8 }}>
            <Grad id="gm" color={C.teal} /><CartesianGrid {...gridProps} /><XAxis dataKey="ts" tickFormatter={hhmm} {...axisProps} minTickGap={50} /><YAxis {...axisProps} domain={[0, 100]} unit="%" />
            <Tooltip content={<ChartTooltip unit="%" labelFormatter={(l) => hhmm(l)} />} /><RLegend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
            <ReferenceLine y={90} stroke={C.red} strokeDasharray="4 4" label={{ value: "pressure", fill: C.red, fontSize: 10, position: "right" }} />
            <Area type="monotone" dataKey="used_pct" name="Memory used" stroke={C.teal} fill="url(#gm)" strokeWidth={2} /><Line type="monotone" dataKey="swap" name="Swap used" stroke={C.yellow} strokeWidth={1.5} dot={false} />
          </ComposedChart></ResponsiveContainer></div>
        </Section>
        <Section title="Top 10 memory processes"><TopProcs rows={h.top_mem} metric="mem" /></Section>
      </div>
    </div>
  );
}

function DiskSection({ h }: { h: PerfHost }) {
  const devs = Object.entries(h.disks);
  const [dev, setDev] = useState(devs[0]?.[0] ?? "");
  const d: DiskStat | undefined = h.disks[dev] ?? devs[0]?.[1];
  const fs = [...h.df].sort((a, b) => b.use_pct - a.use_pct);
  return (
    <div className="space-y-4">
      <Section title="Disk usage by filesystem" description="Mounts above 80% are flagged; QRadar halts processing at 95% on /store">
        <div className="grid gap-4 md:grid-cols-2">
          {fs.map((f) => (
            <div key={f.mount} className="rounded-lg border p-3">
              <div className="flex items-center justify-between text-sm"><span className="font-mono font-medium">{f.mount}</span><span className="font-semibold tabular-nums" style={{ color: f.use_pct >= 90 ? sevColor("critical") : f.use_pct >= 80 ? sevColor("high") : f.use_pct >= 70 ? sevColor("medium") : sevColor("ok") }}>{f.use_pct.toFixed(0)}%</span></div>
              <Meter className="mt-2" value={f.use_pct} color={f.use_pct >= 90 ? sevColor("critical") : f.use_pct >= 80 ? sevColor("high") : f.use_pct >= 70 ? sevColor("medium") : sevColor("ok")} />
              <div className="mt-1.5 text-xs text-muted-foreground">{fmtBytes(f.used_bytes)} used of {fmtBytes(f.size_bytes)} · {fmtBytes(f.avail_bytes)} free</div>
            </div>
          ))}
        </div>
      </Section>
      {d ? (
        <>
          <div className="flex items-center gap-2"><HardDrive className="size-4 text-muted-foreground" /><span className="text-sm text-muted-foreground">Device</span><Select aria-label="Disk device" value={dev} onChange={(e) => setDev(e.target.value)}>{devs.map(([k]) => <option key={k} value={k}>{k}</option>)}</Select></div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Section title="Disk throughput" description="Read vs. write (kB/s)"><div className="h-[240px]" role="img" aria-label="Disk read and write throughput"><ResponsiveContainer><AreaChart data={d.series} margin={{ left: -6, right: 8 }}>
              <Grad id="gr" color={C.cyan} /><Grad id="gwr" color={C.violet} /><CartesianGrid {...gridProps} /><XAxis dataKey="ts" tickFormatter={hhmm} {...axisProps} minTickGap={50} /><YAxis {...axisProps} />
              <Tooltip content={<ChartTooltip unit=" kB/s" labelFormatter={(l) => hhmm(l)} />} /><RLegend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
              <Area type="monotone" dataKey="read_kBps" name="Read" stroke={C.cyan} fill="url(#gr)" strokeWidth={1.5} /><Area type="monotone" dataKey="write_kBps" name="Write" stroke={C.violet} fill="url(#gwr)" strokeWidth={1.5} /></AreaChart></ResponsiveContainer></div></Section>
            <Section title="Latency and utilisation" description="await (ms) and %util"><div className="h-[240px]" role="img" aria-label="Disk await and utilisation"><ResponsiveContainer><ComposedChart data={d.series} margin={{ left: -6, right: 8 }}>
              <CartesianGrid {...gridProps} /><XAxis dataKey="ts" tickFormatter={hhmm} {...axisProps} minTickGap={50} /><YAxis yAxisId="l" {...axisProps} unit="ms" /><YAxis yAxisId="r" orientation="right" {...axisProps} domain={[0, 100]} unit="%" />
              <Tooltip content={<ChartTooltip labelFormatter={(l) => hhmm(l)} />} /><RLegend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
              <ReferenceLine yAxisId="l" y={20} stroke={C.red} strokeDasharray="4 4" /><Line yAxisId="l" type="monotone" dataKey="await" name="await (ms)" stroke={C.orange} strokeWidth={2} dot={false} /><Line yAxisId="r" type="monotone" dataKey="util" name="%util" stroke={C.primary} strokeWidth={1.5} dot={false} /></ComposedChart></ResponsiveContainer></div></Section>
          </div>
          <Section title="Advanced disk metrics" description={`Device ${dev} (iostat/SAR extended statistics)`}>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              {([["avgrq-sz", d.avgrq_sz, "sectors/kB"], ["avgqu-sz", d.avgqu_sz, "requests"], ["await", d.await_avg, "ms"], ["w_await", d.w_await_avg, "ms"], ["r_await", d.r_await_avg, "ms"], ["%util (max)", d.util_max, "%"]] as const).map(([k, v, u]) => (
                <Kpi key={k} label={k} value={v == null ? "n/a" : fmtNum(v, 1)} sub={v == null ? "not in SAR output" : u} tone={k === "await" && v != null ? (v >= 40 ? "critical" : v >= 20 ? "high" : "ok") : undefined} />
              ))}
            </div>
          </Section>
        </>
      ) : <EmptyState title="No disk device statistics" description="SAR block device data was not found in this bundle." />}
    </div>
  );
}

function NetworkSection({ h }: { h: PerfHost }) {
  const ifs = Object.entries(h.interfaces);
  const [ifn, setIfn] = useState(h.sar_summary.network?.primary_iface ?? ifs[0]?.[0] ?? "");
  const n: IfaceStat | undefined = h.interfaces[ifn] ?? ifs[0]?.[1];
  if (!n) return <EmptyState title="No network statistics" />;
  const errors = n.rx_err_max + n.tx_err_max, drops = n.rx_drop_max + n.tx_drop_max;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2"><NetIcon className="size-4 text-muted-foreground" /><span className="text-sm text-muted-foreground">Interface</span><Select aria-label="Network interface" value={ifn} onChange={(e) => setIfn(e.target.value)}>{ifs.map(([k]) => <option key={k} value={k}>{k}</option>)}</Select></div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6"><Kpi label="Inbound (avg)" value={`${fmtBytes(n.rx_kBps_avg * 1024)}/s`} /><Kpi label="Outbound (avg)" value={`${fmtBytes(n.tx_kBps_avg * 1024)}/s`} /><Kpi label="Packets in" value={`${fmtNum(n.rx_pps_avg)}/s`} /><Kpi label="Packets out" value={`${fmtNum(n.tx_pps_avg)}/s`} /><Kpi label="Errors (max)" value={fmtNum(errors, 1)} tone={errors > 0 ? "high" : "ok"} /><Kpi label="Drops (max)" value={fmtNum(drops, 1)} tone={drops > 0 ? "critical" : "ok"} /></div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Section title="Throughput"><div className="h-[240px]" role="img" aria-label="Network throughput"><ResponsiveContainer><AreaChart data={n.series} margin={{ left: -6, right: 8 }}>
          <Grad id="gi" color={C.teal} /><Grad id="go" color={C.primary} /><CartesianGrid {...gridProps} /><XAxis dataKey="ts" tickFormatter={hhmm} {...axisProps} minTickGap={50} /><YAxis {...axisProps} />
          <Tooltip content={<ChartTooltip unit=" kB/s" labelFormatter={(l) => hhmm(l)} />} /><RLegend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
          <Area type="monotone" dataKey="rx_kBps" name="Inbound" stroke={C.teal} fill="url(#gi)" strokeWidth={1.5} /><Area type="monotone" dataKey="tx_kBps" name="Outbound" stroke={C.primary} fill="url(#go)" strokeWidth={1.5} /></AreaChart></ResponsiveContainer></div></Section>
        <Section title="Packets per second"><div className="h-[240px]" role="img" aria-label="Network packets"><ResponsiveContainer><LineChart data={n.series} margin={{ left: -6, right: 8 }}>
          <CartesianGrid {...gridProps} /><XAxis dataKey="ts" tickFormatter={hhmm} {...axisProps} minTickGap={50} /><YAxis {...axisProps} /><Tooltip content={<ChartTooltip unit=" pps" labelFormatter={(l) => hhmm(l)} />} /><RLegend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
          <Line type="monotone" dataKey="rx_pps" name="Packets in" stroke={C.cyan} strokeWidth={1.5} dot={false} /><Line type="monotone" dataKey="tx_pps" name="Packets out" stroke={C.violet} strokeWidth={1.5} dot={false} /></LineChart></ResponsiveContainer></div></Section>
      </div>
    </div>
  );
}

function SarSection({ h }: { h: PerfHost }) {
  const l = h.sar_summary.load, series = h.series.load ?? [], cores = h.hardware.cpus ?? 0;
  const swap = h.series.swap ?? [];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <Kpi label="Load avg (1m)" value={l ? l.avg1.toFixed(1) : "—"} sub={cores ? `${cores} cores` : undefined} tone={l && cores && l.avg1 > cores ? "critical" : undefined} icon={<Activity />} /><Kpi label="Load peak (1m)" value={l ? l.max1.toFixed(1) : "—"} /><Kpi label="Run queue max" value={l ? fmtNum(l.max_runq) : "—"} />
        <Kpi label="httpd processes" value={h.httpd_count ?? "—"} tone={h.httpd_count != null && h.httpd_count > 60 ? "high" : undefined} /><Kpi label="Swap used (avg)" value={h.sar_summary.swap ? `${h.sar_summary.swap.avg.toFixed(0)}%` : "—"} /><Kpi label="CPU / Mem avg" value={`${h.sar_summary.cpu?.avg.toFixed(0) ?? "—"}% / ${h.sar_summary.memory?.avg.toFixed(0) ?? "—"}%`} />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Section title="Load average"><div className="h-[240px]" role="img" aria-label="Load average"><ResponsiveContainer><LineChart data={series} margin={{ left: -10, right: 8 }}>
          <CartesianGrid {...gridProps} /><XAxis dataKey="ts" tickFormatter={hhmm} {...axisProps} minTickGap={50} /><YAxis {...axisProps} /><Tooltip content={<ChartTooltip labelFormatter={(x) => hhmm(x)} />} /><RLegend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
          {cores > 0 && <ReferenceLine y={cores} stroke={C.red} strokeDasharray="4 4" label={{ value: `${cores} cores`, fill: C.red, fontSize: 10, position: "right" }} />}
          <Line type="monotone" dataKey="l1" name="1 min" stroke={C.primary} strokeWidth={2} dot={false} /><Line type="monotone" dataKey="l5" name="5 min" stroke={C.violet} strokeWidth={1.5} dot={false} /><Line type="monotone" dataKey="l15" name="15 min" stroke={C.cyan} strokeWidth={1.5} dot={false} /></LineChart></ResponsiveContainer></div></Section>
        <Section title="Swap usage"><div className="h-[240px]" role="img" aria-label="Swap usage"><ResponsiveContainer><AreaChart data={swap} margin={{ left: -10, right: 8 }}>
          <Grad id="gsw" color={C.yellow} /><CartesianGrid {...gridProps} /><XAxis dataKey="ts" tickFormatter={hhmm} {...axisProps} minTickGap={50} /><YAxis {...axisProps} domain={[0, 100]} unit="%" /><Tooltip content={<ChartTooltip unit="%" labelFormatter={(x) => hhmm(x)} />} />
          <Area type="monotone" dataKey="used_pct" name="Swap used" stroke={C.yellow} fill="url(#gsw)" strokeWidth={2} /></AreaChart></ResponsiveContainer></div></Section>
      </div>
    </div>
  );
}

function AssessmentList({ items }: { items: PerfAssessment[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState("issues");
  const rows = useMemo(() => items.filter((a) => filter === "all" || a.severity !== "ok").sort((a, b) => sevRank(a.severity) - sevRank(b.severity) || a.label.localeCompare(b.label)), [items, filter]);
  return (
    <Section title="Performance AI assessment" description="Finding, risk, root cause, recommendation and priority for every metric." actions={<Segmented layoutId="pa-filter" value={filter} onChange={setFilter} items={[{ key: "issues", label: "Issues" }, { key: "all", label: "All metrics" }]} />}>
      {rows.length === 0 ? <EmptyState title="No performance issues detected" description="All evaluated metrics are within IBM sizing guidance." /> : (
        <div className="space-y-2">{rows.map((a) => (
          <Disclosure key={a.key} open={open === a.key} onToggle={() => setOpen(open === a.key ? null : a.key)}
            header={<div className="flex flex-wrap items-center gap-2.5"><SeverityBadge severity={a.severity === "ok" ? "low" : a.severity} /><PriorityBadge priority={a.priority} /><span className="text-sm font-medium">{a.label}</span><span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">{a.host}</span><span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{a.finding}</span></div>}>
            <div className="grid gap-5 lg:grid-cols-2">
              <div className="space-y-3.5"><KV label="Finding">{a.finding}</KV><KV label="Risk">{a.risk}</KV><KV label="Impact">{a.impact}</KV><KV label="Root cause">{a.root_cause}</KV></div>
              <div className="space-y-3.5"><KV label="Recommendation"><RecoList items={a.recommendation} /></KV><KV label="Threshold">{a.threshold}</KV><KV label="IBM best practice">{a.best_practice}</KV></div>
            </div>
          </Disclosure>
        ))}</div>
      )}
    </Section>
  );
}

export default function Performance() {
  const { id } = useAssessmentCtx();
  const q = usePerformance(id, true);
  const [host, setHost] = useState("");
  const [tab, setTab] = useState("cpu");
  return (
    <div>
      <PageHeader title="Performance Analysis" description="System resource utilisation from SAR, df, free, top and iostat data collected on every managed host." />
      <Async q={q} rows={3}>
        {(d) => {
          const names = Object.keys(d.hosts);
          if (!names.length) return <EmptyState title="No performance data" description="No SAR or system output was found in the get_logs package." />;
          const name = names.includes(host) ? host : names[0]!;
          const h = d.hosts[name]!;
          const hostAssess = d.assessments.filter((a) => a.host === name);
          const worst = hostAssess.reduce((m, a) => (sevRank(a.severity) < sevRank(m) ? a.severity : m), "ok" as string);
          const score = worst === "critical" ? 30 : worst === "high" ? 55 : worst === "medium" ? 72 : 92;
          return (
            <div className="space-y-6">
              <div className="grid gap-4 lg:grid-cols-[auto_1fr]">
                <div className="card-surface flex flex-col items-center gap-2 p-4">
                  <Select aria-label="Host" value={name} onChange={(e) => setHost(e.target.value)} className="w-full">{names.map((n) => <option key={n} value={n}>{n}</option>)}</Select>
                  <SemiGauge size={200} value={h.sar_summary.cpu?.avg ?? null} label="CPU utilisation" sublabel={`${h.hardware.cpus ?? "?"} cores · ${h.hardware.model ?? ""}`} warn={70} crit={90} />
                </div>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  <Kpi label="Host posture" value={<span style={{ color: scoreColor(score) }}>{worst === "ok" ? "Healthy" : worst[0]!.toUpperCase() + worst.slice(1)}</span>} icon={<GaugeIcon />} sub={`${hostAssess.filter((a) => a.severity !== "ok").length} issue(s)`} />
                  <Kpi label="Memory" value={h.hardware.memory_bytes ? fmtBytes(h.hardware.memory_bytes, 0) : "—"} sub={h.sar_summary.memory ? `${h.sar_summary.memory.avg.toFixed(0)}% avg used` : undefined} />
                  <Kpi label="Storage" value={h.hardware.disk_bytes ? fmtBytes(h.hardware.disk_bytes, 0) : "—"} sub={`${h.df.length} filesystems`} />
                  <Kpi label="SAR samples" value={fmtNum(h.samples.cpu ?? 0)} sub={h.identity.ip ?? undefined} />
                </div>
              </div>
              <Segmented layoutId="perf-tab" value={tab} onChange={setTab} items={[{ key: "cpu", label: "CPU", icon: <Cpu /> }, { key: "mem", label: "Memory", icon: <MemoryStick /> }, { key: "disk", label: "Disk", icon: <HardDrive /> }, { key: "net", label: "Network", icon: <NetIcon /> }, { key: "sar", label: "SAR metrics", icon: <Activity /> }]} />
              {tab === "cpu" && <CpuSection h={h} />}{tab === "mem" && <MemorySection h={h} />}{tab === "disk" && <DiskSection h={h} />}{tab === "net" && <NetworkSection h={h} />}{tab === "sar" && <SarSection h={h} />}
              <AssessmentList items={hostAssess} />
              <Section title="Fleet comparison" description="Average CPU and memory utilisation across hosts"><div className="h-[260px]" role="img" aria-label="Fleet comparison"><ResponsiveContainer><BarChart data={names.map((n) => ({ name: n, cpu: d.hosts[n]!.sar_summary.cpu?.avg ?? 0, memory: d.hosts[n]!.sar_summary.memory?.avg ?? 0 }))} margin={{ left: -10 }}>
                <CartesianGrid {...gridProps} /><XAxis dataKey="name" {...axisProps} /><YAxis {...axisProps} domain={[0, 100]} unit="%" /><Tooltip content={<ChartTooltip unit="%" />} cursor={{ fill: "hsl(var(--accent))" }} /><RLegend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="cpu" name="CPU" fill={C.primary} radius={[6, 6, 0, 0]}>{names.map((n, i) => <Cell key={i} fill={n === name ? C.primary : `${C.primary}88`} />)}</Bar><Bar dataKey="memory" name="Memory" fill={C.teal} radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer></div></Section>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
