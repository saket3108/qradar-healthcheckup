import type { ReactNode } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Treemap } from "recharts";
import { fmtCompact } from "@/lib/utils";

export const PALETTE = ["#4589ff", "#8a3ffc", "#33b1ff", "#08bdba", "#d12771", "#fa4d56", "#ff832b", "#f1c21b", "#42be65", "#be95ff", "#ee5396", "#78a9ff"];

export const axisProps = { stroke: "hsl(var(--muted-foreground))", fontSize: 11, tickLine: false, axisLine: false } as const;
export const gridProps = { stroke: "hsl(var(--border))", strokeDasharray: "3 3", vertical: false } as const;

export function ChartTooltip({ active, payload, label, unit, labelFormatter }: { active?: boolean; payload?: { name?: string; value?: number | string; color?: string; dataKey?: string }[]; label?: string | number; unit?: string; labelFormatter?: (l: string | number) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass rounded-md px-3 py-2 text-xs shadow-xl">
      {label != null && <div className="mb-1 font-medium">{labelFormatter ? labelFormatter(label) : String(label)}</div>}
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2 tabular-nums">
          <span className="size-2 rounded-full" style={{ background: p.color }} />
          <span className="text-muted-foreground">{p.name ?? p.dataKey}</span>
          <span className="ml-auto font-medium">{typeof p.value === "number" ? p.value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : p.value}{unit ?? ""}</span>
        </div>
      ))}
    </div>
  );
}

export function Donut({ data, centerLabel, centerValue, height = 220, colors }: { data: { name: string; value: number }[]; centerLabel?: string; centerValue?: ReactNode; height?: number; colors?: string[] }) {
  const pal = colors ?? PALETTE;
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <div className="relative" style={{ height }} role="img" aria-label={`${centerLabel ?? "Distribution"}: ${data.map((d) => `${d.name} ${d.value}`).join(", ")}`}>
      <ResponsiveContainer>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="88%" paddingAngle={2} stroke="none" isAnimationActive>
            {data.map((_, i) => <Cell key={i} fill={pal[i % pal.length]} />)}
          </Pie>
          <Tooltip content={<ChartTooltip />} />
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
        <div>
          <div className="text-2xl font-semibold tabular-nums">{centerValue ?? total.toLocaleString()}</div>
          {centerLabel && <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{centerLabel}</div>}
        </div>
      </div>
    </div>
  );
}

export function Legend({ items }: { items: { name: string; value: number | string; color: string }[] }) {
  return (
    <ul className="grid gap-1.5 text-xs">
      {items.map((i) => (
        <li key={i.name} className="flex items-center gap-2">
          <span className="size-2.5 rounded-sm" style={{ background: i.color }} />
          <span className="truncate text-muted-foreground">{i.name}</span>
          <span className="ml-auto font-medium tabular-nums">{typeof i.value === "number" ? i.value.toLocaleString() : i.value}</span>
        </li>
      ))}
    </ul>
  );
}

interface TreeDatum { name: string; size: number; [k: string]: unknown }
function TreeCell(props: { x?: number; y?: number; width?: number; height?: number; index?: number; name?: string; size?: number }) {
  const { x = 0, y = 0, width = 0, height = 0, index = 0, name = "", size = 0 } = props;
  if (width < 4 || height < 4) return null;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} rx={6} fill={PALETTE[index % PALETTE.length]} fillOpacity={0.82} stroke="hsl(var(--background))" strokeWidth={2} />
      {width > 70 && height > 34 && (
        <>
          <text x={x + 8} y={y + 18} fill="#fff" fontSize={12} fontWeight={600}>{name.length > width / 7 ? `${name.slice(0, Math.floor(width / 7))}…` : name}</text>
          <text x={x + 8} y={y + 33} fill="#fff" fillOpacity={0.85} fontSize={11}>{fmtCompact(size)}</text>
        </>
      )}
    </g>
  );
}
export function TreemapChart({ data, height = 260 }: { data: TreeDatum[]; height?: number }) {
  return (
    <div style={{ height }} role="img" aria-label="Treemap">
      <ResponsiveContainer>
        <Treemap data={data} dataKey="size" nameKey="name" stroke="none" content={<TreeCell />} isAnimationActive={false}>
          <Tooltip content={<ChartTooltip />} />
        </Treemap>
      </ResponsiveContainer>
    </div>
  );
}
