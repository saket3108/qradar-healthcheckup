import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Check, ChevronDown, Loader2, Save } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardDescription, CardHeader, CardTitle, Skeleton, Textarea } from "@/components/ui/primitives";
import { SeverityBadge } from "@/components/ui/badges";
import { cn, errMsg } from "@/lib/utils";

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-0.5 max-w-3xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Section({ title, description, actions, children, className, bodyClassName }: { title?: ReactNode; description?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string }) {
  return (
    <Card className={className}>
      {(title || actions) && (
        <CardHeader>
          <div><CardTitle>{title}</CardTitle>{description && <CardDescription className="mt-0.5">{description}</CardDescription>}</div>
          {actions}
        </CardHeader>
      )}
      <CardBody className={bodyClassName}>{children}</CardBody>
    </Card>
  );
}

export function Kpi({ label, value, sub, tone, icon, onClick }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string; icon?: ReactNode; onClick?: () => void }) {
  const color = tone ? `hsl(var(--${tone}))` : undefined;
  const Body = (
    <>
      <div className="flex items-center justify-between"><span className="label-caps">{label}</span><span className="text-muted-foreground [&_svg]:size-4">{icon}</span></div>
      <div className="mt-2 text-2xl font-semibold tabular-nums leading-none" style={{ color }}>{value}</div>
      {sub && <div className="mt-1.5 text-xs text-muted-foreground">{sub}</div>}
    </>
  );
  const cls = "card-surface block w-full p-4 text-left transition-all hover:-translate-y-0.5 hover:border-primary/40";
  return onClick ? <button onClick={onClick} className={cls}>{Body}</button> : <div className={cls}>{Body}</div>;
}

export function EmptyState({ title, description, action, icon }: { title: string; description?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="grid place-items-center rounded-lg border border-dashed py-14 text-center">
      <div className="max-w-sm">
        {icon && <div className="mx-auto mb-3 grid size-11 place-items-center rounded-full bg-muted text-muted-foreground [&_svg]:size-5">{icon}</div>}
        <div className="font-medium">{title}</div>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
        {action && <div className="mt-4">{action}</div>}
      </div>
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-sev-critical/40 bg-sev-critical/10 p-4 text-sm">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-sev-critical" />
      <div className="flex-1"><div className="font-medium">Something went wrong</div><div className="text-muted-foreground">{errMsg(error)}</div></div>
      {retry && <Button size="sm" variant="outline" onClick={retry}>Retry</Button>}
    </div>
  );
}

export function LoadingGrid({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-24" />)}</div>
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-56" />)}
    </div>
  );
}

/** Wraps a react-query result with loading / error handling. */
export function Async<T>({ q, children, rows }: { q: { data?: T; isLoading: boolean; error: unknown; refetch: () => unknown }; children: (d: T) => ReactNode; rows?: number }) {
  if (q.isLoading) return <LoadingGrid rows={rows} />;
  if (q.error) return <ErrorState error={q.error} retry={() => void q.refetch()} />;
  if (q.data === undefined) return null;
  return <>{children(q.data)}</>;
}

/** Collapsible detail block used for notification / finding cards. */
export function Disclosure({ open, onToggle, header, children }: { open: boolean; onToggle: () => void; header: ReactNode; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-lg border bg-card/60">
      <button onClick={onToggle} aria-expanded={open} className="flex w-full items-center gap-3 p-3 text-left hover:bg-accent/50">
        <div className="min-w-0 flex-1">{header}</div>
        <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }} className="overflow-hidden">
            <div className="border-t p-4">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function KV({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="label-caps">{label}</div>
      <div className="text-sm leading-relaxed">{children}</div>
    </div>
  );
}

export function RecoList({ items }: { items: string[] }) {
  return (
    <ul className="space-y-1.5">
      {items.map((r, i) => (
        <li key={i} className="flex gap-2 text-sm"><span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" /><span>{r}</span></li>
      ))}
    </ul>
  );
}

/** Auto-saving editable comment box ("Editable Comment Box" requirement). */
export function CommentBox({ value, onSave, readOnly, placeholder = "Add consultant comment…", label = "Consultant comment" }: { value: string; onSave: (v: string) => Promise<unknown>; readOnly?: boolean; placeholder?: string; label?: string }) {
  const [text, setText] = useState(value);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [err, setErr] = useState<string>("");
  const saved = useRef(value);
  useEffect(() => { setText(value); saved.current = value; }, [value]);
  const dirty = text !== saved.current;
  async function save() {
    setState("saving");
    try { await onSave(text); saved.current = text; setState("saved"); setTimeout(() => setState("idle"), 1800); }
    catch (e) { setErr(errMsg(e)); setState("error"); }
  }
  return (
    <div className="space-y-1.5">
      <div className="label-caps">{label}</div>
      <Textarea value={text} onChange={(e) => setText(e.target.value)} readOnly={readOnly} placeholder={readOnly ? "No comment" : placeholder} aria-label={label} maxLength={20000}
        onBlur={() => { if (dirty && !readOnly) void save(); }} />
      {!readOnly && (
        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" disabled={!dirty || state === "saving"} onClick={() => void save()}>
            {state === "saving" ? <Loader2 className="animate-spin" /> : <Save />}Save comment
          </Button>
          {state === "saved" && <span className="flex items-center gap-1 text-xs text-sev-ok"><Check className="size-3.5" />Saved</span>}
          {state === "error" && <span role="alert" className="text-xs text-sev-critical">{err}</span>}
          {dirty && state === "idle" && <span className="text-xs text-muted-foreground">Unsaved changes</span>}
        </div>
      )}
    </div>
  );
}

export function FindingMini({ severity, title, sub, right }: { severity: string; title: string; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <SeverityBadge severity={severity} />
      <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{title}</div>{sub && <div className="truncate text-xs text-muted-foreground">{sub}</div>}</div>
      {right}
    </div>
  );
}
