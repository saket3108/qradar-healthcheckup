import { motion } from "framer-motion";
import { useId } from "react";
import { fmtNum, scoreColor, sevColor } from "@/lib/utils";

/** Full-circle score ring used for the executive health score. */
export function ScoreRing({ score, size = 180, stroke = 14, label, sub }: { score: number; size?: number; stroke?: number; label?: string; sub?: string }) {
  const id = useId();
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const color = scoreColor(score);
  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }} role="img" aria-label={`${label ?? "Score"} ${Math.round(score)} out of 100`}>
      <svg width={size} height={size} className="-rotate-90">
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.55} />
            <stop offset="100%" stopColor={color} />
          </linearGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="hsl(var(--muted))" strokeWidth={stroke} />
        <motion.circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={`url(#${id})`} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={c} initial={{ strokeDashoffset: c }} animate={{ strokeDashoffset: c * (1 - pct) }} transition={{ duration: 1.1, ease: "easeOut" }}
          style={{ filter: `drop-shadow(0 0 8px ${color})` }} />
      </svg>
      <div className="absolute text-center">
        <div className="font-semibold tabular-nums leading-none" style={{ fontSize: size * 0.28, color }}>{Math.round(score)}</div>
        <div className="mt-1 text-[11px] uppercase tracking-wider text-muted-foreground">{sub ?? "/ 100"}</div>
        {label && <div className="mt-0.5 text-xs font-medium">{label}</div>}
      </div>
    </div>
  );
}

/** Semi-circular gauge for license consumption (0-100%+, values over 100 are clamped visually but shown numerically). */
export function SemiGauge({ value, label, sublabel, size = 220, warn = 80, crit = 100 }: { value: number | null; label: string; sublabel?: string; size?: number; warn?: number; crit?: number }) {
  const v = value ?? 0;
  const pct = Math.max(0, Math.min(1, v / 100));
  const color = value == null ? sevColor("unknown") : v >= crit ? sevColor("critical") : v >= warn ? sevColor("high") : v >= 60 ? sevColor("medium") : sevColor("ok");
  const stroke = 16, r = (size - stroke) / 2, cx = size / 2, cy = size / 2 + 4;
  const arc = Math.PI * r;
  const path = `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`;
  return (
    <div className="flex flex-col items-center" role="img" aria-label={`${label} ${value == null ? "unknown" : `${v.toFixed(0)} percent`}`}>
      <div className="relative" style={{ width: size, height: size / 2 + 22 }}>
        <svg width={size} height={size / 2 + 12} className="overflow-visible">
          <path d={path} fill="none" stroke="hsl(var(--muted))" strokeWidth={stroke} strokeLinecap="round" />
          <motion.path d={path} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeDasharray={arc} initial={{ strokeDashoffset: arc }}
            animate={{ strokeDashoffset: arc * (1 - pct) }} transition={{ duration: 1, ease: "easeOut" }} style={{ filter: `drop-shadow(0 0 6px ${color})` }} />
          {[0, 50, 80, 100].map((t) => {
            const a = Math.PI * (1 - t / 100);
            return <line key={t} x1={cx + (r - stroke) * Math.cos(a)} y1={cy - (r - stroke) * Math.sin(a)} x2={cx + (r - stroke - 6) * Math.cos(a)} y2={cy - (r - stroke - 6) * Math.sin(a)} stroke="hsl(var(--muted-foreground))" strokeWidth={1} />;
          })}
        </svg>
        <div className="absolute inset-x-0 bottom-0 text-center">
          <div className="text-3xl font-semibold tabular-nums leading-none" style={{ color }}>{value == null ? "—" : `${fmtNum(v, 1)}%`}</div>
        </div>
      </div>
      <div className="mt-1 text-sm font-medium">{label}</div>
      {sublabel && <div className="text-xs text-muted-foreground">{sublabel}</div>}
    </div>
  );
}

/** Compact horizontal progress meter. */
export function Meter({ value, max = 100, color, className }: { value: number; max?: number; color?: string; className?: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-muted ${className ?? ""}`} role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <motion.div className="h-full rounded-full" style={{ background: color ?? scoreColor(100 - pct) }} initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.7, ease: "easeOut" }} />
    </div>
  );
}
