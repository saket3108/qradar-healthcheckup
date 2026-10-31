import { motion } from "framer-motion";
import { AlertCircle, CheckCircle2, CloudUpload, FileArchive, Loader2, RotateCw, Search, Trash2, X } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, Input, Label, Select, Skeleton } from "@/components/ui/primitives";
import { StatusBadge } from "@/components/ui/badges";
import { EmptyState, ErrorState, PageHeader } from "@/components/common";
import { Meter } from "@/components/charts/gauges";
import { uploadFile, type UploadProgress } from "@/lib/api";
import { useAssessments, useCreateAssessment, useDeleteAssessment } from "@/lib/queries";
import { cn, errMsg, fmtBytes, fmtDate, scoreColor, timeAgo } from "@/lib/utils";
import { useAppSelector } from "@/store/hooks";
import { can } from "@/store/auth";
import { useResume } from "@/lib/queries";
import type { Assessment } from "@/types";

const ACCEPT = [".tar", ".tar.gz", ".tgz", ".gz", ".zip"];
export const isSupported = (name: string) => ACCEPT.some((e) => name.toLowerCase().endsWith(e));

interface QueueItem { id: number; file: File; customer: string; consultant: string; progress?: UploadProgress; state: "ready" | "uploading" | "analysing" | "error"; error?: string }

function UploadPanel({ onCreated }: { onCreated: (id: string) => void }) {
  const user = useAppSelector((s) => s.auth.user);
  const create = useCreateAssessment();
  const [items, setItems] = useState<QueueItem[]>([]);
  const [drag, setDrag] = useState(false);
  const [defaults, setDefaults] = useState({ customer: "", consultant: user?.full_name ?? "" });
  const seq = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const aborts = useRef(new Map<number, AbortController>());

  const patch = (id: number, p: Partial<QueueItem>) => setItems((xs) => xs.map((x) => (x.id === id ? { ...x, ...p } : x)));

  const add = useCallback((files: FileList | File[]) => {
    const next: QueueItem[] = [];
    for (const f of Array.from(files)) {
      const ok = isSupported(f.name);
      next.push({ id: ++seq.current, file: f, customer: defaults.customer, consultant: defaults.consultant, state: ok ? "ready" : "error", error: ok ? undefined : `Unsupported file type. Allowed: ${ACCEPT.join(", ")}` });
    }
    setItems((xs) => [...xs, ...next]);
  }, [defaults]);

  async function start(it: QueueItem) {
    const ac = new AbortController();
    aborts.current.set(it.id, ac);
    patch(it.id, { state: "uploading", error: undefined });
    try {
      const up = await uploadFile(it.file, (p) => patch(it.id, { progress: p }), ac.signal);
      patch(it.id, { state: "analysing" });
      const a = await create.mutateAsync({ upload_id: up.upload_id, customer_name: it.customer || undefined, consultant_name: it.consultant || undefined });
      setItems((xs) => xs.filter((x) => x.id !== it.id));
      onCreated(a.id);
    } catch (e) {
      patch(it.id, { state: "error", error: (e as Error).name === "AbortError" ? "Upload cancelled" : errMsg(e) });
    } finally { aborts.current.delete(it.id); }
  }
  const startAll = () => items.filter((i) => i.state === "ready").forEach((i) => void start(i));
  const cancel = (id: number) => { aborts.current.get(id)?.abort(); setItems((xs) => xs.filter((x) => x.id !== id)); };

  return (
    <Card className="p-5">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1.5"><Label htmlFor="cust">Customer name</Label><Input id="cust" placeholder="e.g. Contoso Bank" value={defaults.customer} onChange={(e) => setDefaults({ ...defaults, customer: e.target.value })} /></div>
        <div className="space-y-1.5"><Label htmlFor="cons">Consultant name</Label><Input id="cons" placeholder="Your name" value={defaults.consultant} onChange={(e) => setDefaults({ ...defaults, consultant: e.target.value })} /></div>
      </div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files.length) add(e.dataTransfer.files); }}
        className={cn("mt-4 grid place-items-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors", drag ? "border-primary bg-primary/10" : "hover:border-primary/50")}
      >
        <div>
          <motion.div animate={{ y: drag ? -4 : 0 }} className="mx-auto mb-3 grid size-12 place-items-center rounded-full bg-primary/15 text-primary"><CloudUpload className="size-6" /></motion.div>
          <p className="font-medium">Drop one or more get_logs packages here</p>
          <p className="mt-1 text-sm text-muted-foreground">.tar · .tar.gz · .gz · .zip — large bundles (10 GB+) are uploaded in resumable chunks</p>
          <Button className="mt-4" variant="secondary" onClick={() => inputRef.current?.click()}>Browse files</Button>
          <input ref={inputRef} data-testid="file-input" type="file" multiple hidden accept={ACCEPT.join(",")} onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = ""; }} />
        </div>
      </div>

      {items.length > 0 && (
        <div className="mt-4 space-y-2">
          {items.map((it) => (
            <div key={it.id} className="rounded-lg border bg-background/40 p-3">
              <div className="flex items-center gap-3">
                <FileArchive className="size-5 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{it.file.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {fmtBytes(it.file.size)}
                    {it.state === "uploading" && it.progress && ` · ${fmtBytes(it.progress.loaded)} sent · ${fmtBytes(it.progress.speed)}/s`}
                    {it.state === "analysing" && " · starting analysis…"}
                  </div>
                </div>
                {it.state === "ready" && <Button size="sm" onClick={() => void start(it)}>Upload &amp; analyse</Button>}
                {(it.state === "uploading" || it.state === "analysing") && <Loader2 className="size-4 animate-spin text-primary" />}
                <Button size="icon" variant="ghost" className="size-8" aria-label={`Remove ${it.file.name}`} onClick={() => cancel(it.id)}><X /></Button>
              </div>
              {it.state === "uploading" && it.progress && <Meter className="mt-2" value={it.progress.loaded} max={it.progress.total} color="hsl(var(--primary))" />}
              {it.error && <p role="alert" className="mt-2 flex items-center gap-1.5 text-xs text-sev-critical"><AlertCircle className="size-3.5" />{it.error}</p>}
              {it.state === "error" && isSupported(it.file.name) && <Button size="sm" variant="outline" className="mt-2" onClick={() => void start(it)}>Retry (resumes from server)</Button>}
            </div>
          ))}
          {items.filter((i) => i.state === "ready").length > 1 && <Button onClick={startAll}>Upload &amp; analyse all</Button>}
        </div>
      )}
    </Card>
  );
}

function AssessmentRow({ a, canUpload, canDelete, onOpen }: { a: Assessment; canUpload: boolean; canDelete: boolean; onOpen: () => void }) {
  const del = useDeleteAssessment();
  const resume = useResume(a.id);
  const active = a.status === "queued" || a.status === "processing";
  return (
    <motion.div layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="card-surface group flex flex-wrap items-center gap-4 p-4 transition-colors hover:border-primary/40">
      <button onClick={onOpen} className="flex min-w-0 flex-1 items-center gap-4 text-left" aria-label={`Open ${a.customer_name || a.name}`}>
        <div className="grid size-14 shrink-0 place-items-center rounded-xl border bg-background/50 tabular-nums" style={{ color: a.overall_score != null ? scoreColor(a.overall_score) : undefined }}>
          {a.overall_score != null ? <span className="text-xl font-semibold">{Math.round(a.overall_score)}</span> : active ? <Loader2 className="size-5 animate-spin text-primary" /> : <AlertCircle className="size-5 text-sev-critical" />}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2"><span className="truncate font-medium">{a.customer_name || a.name}</span><StatusBadge status={a.status} /></div>
          <div className="mt-0.5 truncate text-xs text-muted-foreground">
            {a.source_filename} · {fmtBytes(a.source_size)} · {a.qradar_version ? `QRadar ${a.qradar_version} · ` : ""}{fmtDate(a.created_at)} ({timeAgo(a.created_at)})
          </div>
          {active && <div className="mt-2 max-w-sm"><Meter value={a.progress} color="hsl(var(--primary))" /><div className="mt-1 text-[11px] text-muted-foreground">{Math.round(a.progress)}% · {a.current_stage ?? "queued"}</div></div>}
          {a.status === "failed" && a.error && <div className="mt-1 max-w-xl truncate text-xs text-sev-critical" title={a.error}>{a.error}</div>}
        </div>
      </button>
      <div className="flex items-center gap-1">
        {(a.status === "failed" || a.status === "partial") && canUpload && (
          <Button size="sm" variant="outline" onClick={() => resume.mutate(undefined)} disabled={resume.isPending}><RotateCw className={cn(resume.isPending && "animate-spin")} />Resume</Button>
        )}
        {canDelete && !active && (
          <Button size="icon" variant="ghost" aria-label={`Delete ${a.customer_name || a.name}`} onClick={() => { if (window.confirm(`Delete "${a.customer_name || a.name}" and all of its data?`)) del.mutate(a.id); }}><Trash2 /></Button>
        )}
      </div>
    </motion.div>
  );
}

export default function Assessments() {
  const nav = useNavigate();
  const user = useAppSelector((s) => s.auth.user);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const list = useAssessments(q.trim() || undefined, status || undefined);
  const canUpload = can(user?.role, "upload");

  return (
    <div>
      <PageHeader title="Assessments" description="Upload a QRadar get_logs package to generate a complete health assessment, or open a previous one." />
      {canUpload && <div className="mb-8"><UploadPanel onCreated={(id) => nav(`/assessments/${id}`)} /></div>}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative max-w-xs flex-1"><Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" /><Input aria-label="Search assessments" className="pl-9" placeholder="Search customer or file…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>{["completed", "processing", "queued", "partial", "failed"].map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
        <span className="ml-auto text-xs text-muted-foreground">{list.data ? `${list.data.length} assessment${list.data.length === 1 ? "" : "s"}` : ""}</span>
      </div>
      {list.isLoading && <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-20" />)}</div>}
      {list.error && <ErrorState error={list.error} retry={() => void list.refetch()} />}
      {list.data && list.data.length === 0 && (
        <EmptyState icon={<CheckCircle2 />} title={q || status ? "No assessments match your filters" : "No assessments yet"} description={canUpload ? "Drop a get_logs package above to run your first health check." : "Ask an administrator or consultant to upload a package."} />
      )}
      <div className="space-y-3">
        {list.data?.map((a) => <AssessmentRow key={a.id} a={a} canUpload={canUpload} canDelete={can(user?.role, "delete")} onOpen={() => nav(`/assessments/${a.id}`)} />)}
      </div>
    </div>
  );
}
