import { type ReactNode } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

export interface TabItem { key: string; label: string; icon?: ReactNode; badge?: ReactNode }
export function Segmented({ items, value, onChange, layoutId = "seg", className }: { items: TabItem[]; value: string; onChange: (k: string) => void; layoutId?: string; className?: string }) {
  return (
    <div role="tablist" className={cn("inline-flex gap-0.5 rounded-lg border bg-muted/50 p-0.5", className)}>
      {items.map((it) => (
        <button key={it.key} role="tab" aria-selected={value === it.key} onClick={() => onChange(it.key)}
          className={cn("relative flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors", value === it.key ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>
          {value === it.key && <motion.span layoutId={layoutId} className="absolute inset-0 rounded-md border bg-card shadow-sm" transition={{ type: "spring", duration: 0.35 }} />}
          <span className="relative flex items-center gap-1.5 [&_svg]:size-3.5">{it.icon}{it.label}{it.badge}</span>
        </button>
      ))}
    </div>
  );
}
