import { Background, BackgroundVariant, Controls, MarkerType, MiniMap, Position, ReactFlow, Handle, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { CheckCircle2, AlertTriangle, XCircle, ShieldCheck, ShieldOff, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Async, Kpi, PageHeader, RecoList, Section } from "@/components/common";
import { Badge, StatusBadge } from "@/components/ui/badges";
import { Button } from "@/components/ui/button";
import { Meter } from "@/components/charts/gauges";
import { useAssessmentCtx } from "@/pages/AssessmentLayout";
import { useDeployment } from "@/lib/queries";
import { cn, fmtBytes, fmtNum, scoreColor, sevColor } from "@/lib/utils";
import type { DeploymentCheck, TopoNode, Topology } from "@/types";

export const ROLE_COLOR: Record<string, string> = { Console: "#4589ff", EP: "#8a3ffc", EC: "#33b1ff", FP: "#08bdba", DN: "#d12771", "App Host": "#ff832b", Extension: "#f1c21b", Unknown: "#8d8d8d" };
const ROLE_ORDER = ["Console", "EP", "EC", "FP", "DN", "App Host", "Extension", "Unknown"];
const NODE_W = 260, NODE_H = 168, GAP_X = 40, GAP_Y = 90;

const statusTone = (s: string) => (s === "healthy" ? "ok" : s === "warning" ? "medium" : s === "critical" ? "critical" : "unknown");

type NodeData = { node: TopoNode; selected: boolean } & Record<string, unknown>;

function HostNode({ data }: NodeProps<Node<NodeData>>) {
  const n = data.node;
  const color = ROLE_COLOR[n.role] ?? ROLE_COLOR.Unknown;
  return (
    <div className={cn("glass w-[260px] rounded-xl p-3 shadow-lg transition-all", data.selected && "ring-2 ring-primary")} style={{ borderColor: `${color}66`, boxShadow: `0 0 0 1px ${color}33, 0 10px 30px -12px ${color}66` }}
      data-testid={`node-${n.hostname}`}>
      <Handle type="target" position={Position.Top} className="!size-2 !border-0" style={{ background: color }} />
      <div className="flex items-center gap-2">
        <span className="rounded-md px-2 py-0.5 text-[11px] font-bold text-white" style={{ background: color }}>{n.role}</span>
        {n.ha_role && <Badge tone="info" className="!py-0">{n.ha_role}</Badge>}
        <span className="ml-auto flex items-center gap-1.5 text-[11px] text-muted-foreground"><span className="size-2 rounded-full" style={{ background: sevColor(statusTone(n.status)), boxShadow: `0 0 8px ${sevColor(statusTone(n.status))}` }} />{n.status}</span>
      </div>
      <div className="mt-2 truncate text-sm font-semibold" title={n.hostname}>{n.hostname}</div>
      <div className="font-mono text-[11px] text-muted-foreground">{n.ip ?? "no ip"}</div>
      <div className="mt-2.5 grid grid-cols-3 gap-2 text-center">
        <div><div className="text-[10px] uppercase text-muted-foreground">EPS</div><div className="text-xs font-semibold tabular-nums">{n.eps != null ? fmtNum(n.eps) : "—"}</div></div>
        <div><div className="text-[10px] uppercase text-muted-foreground">FPM</div><div className="text-xs font-semibold tabular-nums">{n.fpm != null ? fmtNum(n.fpm) : "—"}</div></div>
        <div><div className="text-[10px] uppercase text-muted-foreground">Health</div><div className="text-xs font-semibold tabular-nums" style={{ color: scoreColor(n.health) }}>{Math.round(n.health)}</div></div>
      </div>
      <Meter className="mt-2" value={n.health} color={scoreColor(n.health)} />
      <Handle type="source" position={Position.Bottom} className="!size-2 !border-0" style={{ background: color }} />
    </div>
  );
}
const nodeTypes = { host: HostNode };

export function layoutTopology(topo: Topology, selected: string | null): { nodes: Node<NodeData>[]; edges: Edge[] } {
  const rows = new Map<string, TopoNode[]>();
  for (const n of topo.nodes) {
    const key = n.role === "Console" ? "Console" : ["EP", "EC", "FP"].includes(n.role) ? "Processors" : "Other";
    rows.set(key, [...(rows.get(key) ?? []), n]);
  }
  const tiers = ["Console", "Processors", "Other"].map((k) => (rows.get(k) ?? []).sort((a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role) || a.hostname.localeCompare(b.hostname))).filter((t) => t.length);
  const widest = Math.max(1, ...tiers.map((t) => t.length));
  const nodes: Node<NodeData>[] = [];
  tiers.forEach((tier, r) => {
    const rowW = tier.length * NODE_W + (tier.length - 1) * GAP_X;
    const fullW = widest * NODE_W + (widest - 1) * GAP_X;
    tier.forEach((n, i) => nodes.push({ id: n.id, type: "host", position: { x: (fullW - rowW) / 2 + i * (NODE_W + GAP_X), y: r * (NODE_H + GAP_Y) }, data: { node: n, selected: selected === n.id }, draggable: true }));
  });
  const edges: Edge[] = topo.edges.map((e, i) => ({
    id: `e${i}`, source: e.source, target: e.target, animated: e.kind === "managed", type: "smoothstep",
    style: { stroke: e.kind === "ha" ? "#f1c21b" : "hsl(var(--muted-foreground) / .55)", strokeWidth: e.kind === "ha" ? 2.5 : 1.5, strokeDasharray: e.kind === "ha" ? "6 4" : undefined },
    markerEnd: { type: MarkerType.ArrowClosed, color: "hsl(var(--muted-foreground))" }, label: e.kind === "ha" ? "HA" : undefined,
    labelStyle: { fill: "hsl(var(--foreground))", fontSize: 10 }, labelBgStyle: { fill: "hsl(var(--card))" },
  }));
  return { nodes, edges };
}

const CHECK_ICON = { PASS: <CheckCircle2 className="size-4 text-sev-ok" />, WARNING: <AlertTriangle className="size-4 text-sev-medium" />, CRITICAL: <XCircle className="size-4 text-sev-critical" /> } as const;
const CHECK_TONE = { PASS: "ok", WARNING: "medium", CRITICAL: "critical" } as const;

function Detail({ n, onClose }: { n: TopoNode; onClose: () => void }) {
  const rows: [string, React.ReactNode][] = [["Hostname", n.hostname], ["IP", n.ip], ["Role", n.role], ["Components", n.components.join(", ") || "—"], ["Version", n.version], ["Raw status", n.status_raw],
    ["EPS / FPM", `${n.eps != null ? fmtNum(n.eps) : "—"} / ${n.fpm != null ? fmtNum(n.fpm) : "—"}`], ["CPU / RAM / Disk", `${n.cpu_cores ?? "—"} cores / ${fmtBytes(n.memory_bytes, 0)} / ${fmtBytes(n.disk_bytes, 0)}`],
    ["Encryption token", n.token == null ? "—" : n.token ? "Present" : "Missing"], ["HA", n.ha_role ? `${n.ha_role}${n.ha_peer ? ` ↔ ${n.ha_peer}` : ""} (${n.ha_status ?? "unknown"})` : "Not in an HA pair"], ["Open notifications", n.notifications], ["Last seen", n.last_seen]];
  return (
    <div className="card-surface p-4" role="region" aria-label={`Details for ${n.hostname}`}>
      <div className="mb-2 flex items-center justify-between"><div className="flex items-center gap-2 font-semibold">{n.hostname}<StatusBadge status={n.status} /></div><Button variant="ghost" size="icon" className="size-7" aria-label="Close details" onClick={onClose}><X /></Button></div>
      {rows.map(([k, v]) => <div key={k} className="flex justify-between gap-3 border-b py-1.5 text-sm last:border-0"><span className="text-muted-foreground">{k}</span><span className="text-right font-medium">{v ?? "—"}</span></div>)}
    </div>
  );
}

export default function Deployment() {
  const { id } = useAssessmentCtx();
  const q = useDeployment(id, true);
  const [sel, setSel] = useState<string | null>(null);
  const topo = q.data?.topology;
  const graph = useMemo(() => (topo ? layoutTopology(topo, sel) : { nodes: [], edges: [] }), [topo, sel]);
  const selected = topo?.nodes.find((n) => n.id === sel) ?? null;

  return (
    <div>
      <PageHeader title="Deployment" description="Managed host topology, high-availability analysis and automated deployment validation." />
      <Async q={q} rows={2}>
        {({ topology, checks }) => {
          const counts = { PASS: 0, WARNING: 0, CRITICAL: 0 };
          checks.forEach((c) => { counts[c.status]++; });
          const ha = topology.ha;
          return (
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
                {ROLE_ORDER.map((r) => <Kpi key={r} label={r} value={topology.role_counts[r] ?? 0} tone={undefined} icon={<span className="size-2.5 rounded-sm" style={{ background: ROLE_COLOR[r] }} />} />)}
              </div>
              <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
                <div className="card-surface overflow-hidden">
                  <div className="h-[620px] w-full" data-testid="topology-canvas">
                    <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.2 }} minZoom={0.3} maxZoom={1.6} nodesConnectable={false}
                      onNodeClick={(_, n) => setSel(n.id === sel ? null : n.id)} onPaneClick={() => setSel(null)} proOptions={{ hideAttribution: true }} colorMode="system">
                      <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="hsl(var(--muted-foreground) / .3)" />
                      <Controls showInteractive={false} />
                      <MiniMap pannable zoomable nodeColor={(n) => ROLE_COLOR[(n.data as NodeData).node.role] ?? "#888"} maskColor="hsl(var(--background) / .7)" />
                    </ReactFlow>
                  </div>
                </div>
                <div className="space-y-4">
                  {selected ? <Detail n={selected} onClose={() => setSel(null)} /> : <div className="card-surface p-4 text-sm text-muted-foreground">Select a host in the diagram to see its details. Drag nodes to rearrange; scroll to zoom.</div>}
                  <Section title="High availability analysis">
                    <div className="flex items-center gap-2">{ha.configured ? <ShieldCheck className="size-5 text-sev-ok" /> : <ShieldOff className="size-5 text-sev-high" />}<span className="font-medium">{ha.configured ? "HA configured" : "No HA pairs configured"}</span></div>
                    {ha.pairs.map((p, i) => (
                      <div key={i} className="mt-3 rounded-md border p-3 text-sm">
                        <div className="flex justify-between"><span className="text-muted-foreground">Primary</span><span className="font-medium">{p.primary}</span></div>
                        <div className="flex justify-between"><span className="text-muted-foreground">Secondary</span><span className="font-medium">{p.secondary}</span></div>
                        <div className="flex justify-between"><span className="text-muted-foreground">Synchronization</span><span className="font-medium">{p.sync ?? p.status ?? "unknown"}</span></div>
                        <div className="flex justify-between"><span className="text-muted-foreground">Failover readiness</span><Badge tone={p.failover_ready ? "ok" : "high"}>{p.failover_ready ? "Ready" : "Not ready"}</Badge></div>
                      </div>
                    ))}
                    {ha.unprotected.length > 0 && <div className="mt-3"><div className="label-caps mb-1.5">Hosts without HA protection</div><div className="flex flex-wrap gap-1.5">{ha.unprotected.map((u) => <Badge key={u.id} tone="neutral">{u.hostname} · {u.role}</Badge>)}</div></div>}
                  </Section>
                </div>
              </div>

              <Section title="Deployment validation" description="Automated consistency checks run against deployment.xml, managed host data and tunnel configuration."
                actions={<div className="flex gap-1.5"><Badge tone="ok">{counts.PASS} pass</Badge><Badge tone="medium">{counts.WARNING} warning</Badge><Badge tone="critical">{counts.CRITICAL} critical</Badge></div>}>
                <ul className="divide-y">
                  {checks.map((c: DeploymentCheck) => (
                    <li key={c.id} className="flex gap-3 py-3">
                      <span className="mt-0.5">{CHECK_ICON[c.status]}</span>
                      <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><span className="text-sm font-medium">{c.name}</span><Badge tone={CHECK_TONE[c.status]}>{c.status}</Badge></div>
                        <p className="mt-0.5 text-sm text-muted-foreground">{c.detail}</p>
                        {c.recommendation && c.status !== "PASS" && <div className="mt-2"><RecoList items={[c.recommendation]} /></div>}</div>
                    </li>
                  ))}
                </ul>
              </Section>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
