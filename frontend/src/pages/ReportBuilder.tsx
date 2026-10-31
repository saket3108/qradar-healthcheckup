import { zodResolver } from "@hookform/resolvers/zod";
import { Download, FileText, FileType2, Image as ImageIcon, Loader2, Presentation, Save, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import { Async, EmptyState, PageHeader, Section } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Checkbox, Input, Label, Textarea } from "@/components/ui/primitives";
import { useAssessmentCtx } from "@/pages/AssessmentLayout";
import { api, downloadUrl } from "@/lib/api";
import { useCreateExport, useExports, useReportConfig, useSaveReportConfig } from "@/lib/queries";
import { errMsg, fmtBytes, fmtDate } from "@/lib/utils";
import type { ExportRow, ReportConfigResp } from "@/types";

export const reportSchema = z.object({
  customer_name: z.string().trim().min(1, "Customer name is required").max(255),
  consultant_name: z.string().trim().max(255),
  title: z.string().trim().min(1, "Title is required").max(255),
  classification: z.string().trim().max(64),
  notes: z.string().max(20000),
  next_steps: z.string().max(20000),
  sections: z.array(z.string()).min(1, "Select at least one section"),
});
export type ReportForm = z.infer<typeof reportSchema>;

const FORMATS = [
  { key: "pdf", label: "PDF report", desc: "Consulting-style customer deliverable", icon: FileText },
  { key: "docx", label: "Word report", desc: "Editable DOCX with tables and charts", icon: FileType2 },
  { key: "pptx", label: "PowerPoint", desc: "13-slide executive presentation", icon: Presentation },
] as const;

function LogoCard({ id, has, canEdit }: { id: string; has: boolean; canEdit: boolean }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [ver, setVer] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let revoked: string | null = null;
    if (!has) { setUrl(null); return; }
    api<Response>(`/api/assessments/${id}/logo`, { raw: true }).then((r) => r.blob()).then((b) => { revoked = URL.createObjectURL(b); setUrl(revoked); }).catch(() => setUrl(null));
    return () => { if (revoked) URL.revokeObjectURL(revoked); };
  }, [id, has, ver]);

  async function upload(f: File) {
    setErr(null);
    if (f.size > 2 * 1024 * 1024) { setErr("Logo must be smaller than 2 MB"); return; }
    if (!/\.(png|jpe?g)$/i.test(f.name)) { setErr("Logo must be a PNG or JPEG image"); return; }
    setBusy(true);
    try { const fd = new FormData(); fd.append("file", f); await api(`/api/assessments/${id}/logo`, { method: "POST", body: fd }); setVer((v) => v + 1); window.dispatchEvent(new Event("qhc-logo")); }
    catch (e) { setErr(errMsg(e)); } finally { setBusy(false); }
  }
  return (
    <div className="space-y-2">
      <Label>Company logo</Label>
      <div className="flex items-center gap-3">
        <div className="grid size-16 place-items-center overflow-hidden rounded-lg border bg-white">{url ? <img src={url} alt="Company logo preview" className="max-h-full max-w-full object-contain" /> : <ImageIcon className="size-6 text-muted-foreground" />}</div>
        {canEdit && <><Button type="button" variant="secondary" size="sm" disabled={busy} onClick={() => input.current?.click()}>{busy && <Loader2 className="animate-spin" />}{has ? "Replace logo" : "Upload logo"}</Button>
          <input ref={input} data-testid="logo-input" hidden type="file" accept="image/png,image/jpeg" onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} /></>}
        <span className="text-xs text-muted-foreground">PNG or JPEG, up to 2 MB</span>
      </div>
      {err && <p role="alert" className="text-xs text-sev-critical">{err}</p>}
    </div>
  );
}

function ExportsPanel({ id, canExport }: { id: string; canExport: boolean }) {
  const list = useExports(id);
  const create = useCreateExport(id);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function gen(fmt: string) {
    setErr(null); setBusy(fmt);
    try { const r = await create.mutateAsync(fmt); window.location.assign(downloadUrl(r.download)); } catch (e) { setErr(errMsg(e)); } finally { setBusy(null); }
  }
  return (
    <Section title="Export" description="Generated from the saved report settings. Save your changes first.">
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
        {FORMATS.map((f) => (
          <button key={f.key} onClick={() => void gen(f.key)} disabled={!canExport || busy !== null} aria-label={`Generate ${f.label}`}
            className="group rounded-lg border bg-background/40 p-4 text-left transition-all hover:-translate-y-0.5 hover:border-primary/50 disabled:opacity-50 disabled:hover:translate-y-0">
            <f.icon className="mb-2 size-6 text-primary" /><div className="text-sm font-semibold">{f.label}</div><div className="text-xs text-muted-foreground">{f.desc}</div>
            <div className="mt-3 flex items-center gap-1.5 text-xs font-medium text-primary">{busy === f.key ? <><Loader2 className="size-3.5 animate-spin" />Generating…</> : <><Download className="size-3.5" />Generate &amp; download</>}</div>
          </button>
        ))}
      </div>
      {!canExport && <p className="mt-3 text-xs text-muted-foreground">Your role cannot generate exports.</p>}
      {err && <p role="alert" className="mt-3 text-sm text-sev-critical">{err}</p>}
      <div className="mt-5"><div className="label-caps mb-2">Previous exports</div>
        {list.data && list.data.length === 0 ? <p className="text-sm text-muted-foreground">No exports generated yet.</p> : (
          <ul className="divide-y rounded-lg border">{(list.data ?? []).map((e: ExportRow) => (
            <li key={e.id} className="flex items-center gap-3 px-3 py-2 text-sm"><span className="w-12 font-mono text-xs font-semibold uppercase">{e.format}</span><span className="text-muted-foreground">{fmtBytes(e.size)}</span><span className="text-xs text-muted-foreground">{fmtDate(e.created_at)} · {e.created_by}</span>
              {canExport && <a className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline" href={downloadUrl(e.download)} download><Download className="size-3.5" />Download</a>}</li>
          ))}</ul>
        )}
      </div>
    </Section>
  );
}

function Editor({ id, data, canEdit }: { id: string; data: ReportConfigResp; canEdit: boolean }) {
  const save = useSaveReportConfig(id);
  const c = data.config;
  const defaults: ReportForm = { customer_name: c.customer_name ?? "", consultant_name: c.consultant_name ?? "", title: c.title, classification: c.classification, notes: c.notes, next_steps: c.next_steps.join("\n"), sections: c.sections };
  const { register, handleSubmit, control, reset, formState: { errors, isDirty, isSubmitting } } = useForm<ReportForm>({ resolver: zodResolver(reportSchema), defaultValues: defaults });
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { reset(defaults); }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  const onSubmit = handleSubmit(async (v) => {
    setErr(null); setSaved(false);
    try {
      await save.mutateAsync({ customer_name: v.customer_name, consultant_name: v.consultant_name, title: v.title, classification: v.classification, notes: v.notes, sections: v.sections, next_steps: v.next_steps.split("\n").map((s) => s.trim()).filter(Boolean) });
      setSaved(true); setTimeout(() => setSaved(false), 2200);
    } catch (e) { setErr(errMsg(e)); }
  });

  return (
    <form onSubmit={onSubmit} noValidate aria-label="Report settings" className="space-y-6">
      <Section title="Report details">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5"><Label htmlFor="rc-cust">Customer name</Label><Input id="rc-cust" disabled={!canEdit} aria-invalid={!!errors.customer_name} {...register("customer_name")} />{errors.customer_name && <p role="alert" className="text-xs text-sev-critical">{errors.customer_name.message}</p>}</div>
          <div className="space-y-1.5"><Label htmlFor="rc-cons">Consultant name</Label><Input id="rc-cons" disabled={!canEdit} {...register("consultant_name")} /></div>
          <div className="space-y-1.5"><Label htmlFor="rc-title">Report title</Label><Input id="rc-title" disabled={!canEdit} aria-invalid={!!errors.title} {...register("title")} />{errors.title && <p role="alert" className="text-xs text-sev-critical">{errors.title.message}</p>}</div>
          <div className="space-y-1.5"><Label htmlFor="rc-class">Classification</Label><Input id="rc-class" disabled={!canEdit} {...register("classification")} /></div>
        </div>
        <div className="mt-4"><LogoCard id={id} has={data.has_logo} canEdit={canEdit} /></div>
      </Section>
      <Section title="Sections" description="Choose which sections appear in the PDF, Word and PowerPoint exports.">
        <Controller control={control} name="sections" render={({ field }) => (
          <fieldset className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3" disabled={!canEdit}>
            <legend className="sr-only">Report sections</legend>
            {data.available_sections.map((s) => { const on = field.value.includes(s.key); return (
              <label key={s.key} className="flex cursor-pointer items-center gap-2.5 rounded-md border bg-background/40 px-3 py-2 text-sm hover:border-primary/40">
                <Checkbox aria-label={s.label} checked={on} onCheckedChange={(v) => field.onChange(v ? data.available_sections.map((x) => x.key).filter((k) => k === s.key || field.value.includes(k)) : field.value.filter((k) => k !== s.key))} />{s.label}</label>); })}
          </fieldset>)} />
        {errors.sections && <p role="alert" className="mt-2 text-xs text-sev-critical">{errors.sections.message}</p>}
      </Section>
      <Section title="Notes and next steps" description="Notes appear in the executive summary; next steps replace the generated action plan (one per line).">
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-1.5"><Label htmlFor="rc-notes">Consultant notes</Label><Textarea id="rc-notes" rows={7} disabled={!canEdit} {...register("notes")} /></div>
          <div className="space-y-1.5"><Label htmlFor="rc-next">Next steps (one per line)</Label><Textarea id="rc-next" rows={7} disabled={!canEdit} {...register("next_steps")} /></div>
        </div>
      </Section>
      {canEdit && (
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={isSubmitting || !isDirty}>{isSubmitting ? <Loader2 className="animate-spin" /> : <Save />}Save report settings</Button>
          <Button type="button" variant="ghost" disabled={!isDirty} onClick={() => reset(defaults)}><Trash2 />Discard changes</Button>
          {saved && <span role="status" className="text-sm text-sev-ok">Saved</span>}{err && <span role="alert" className="text-sm text-sev-critical">{err}</span>}
          {isDirty && <span className="text-xs text-muted-foreground">Unsaved changes</span>}
        </div>
      )}
    </form>
  );
}

export default function ReportBuilder() {
  const { id, canEdit, canExport } = useAssessmentCtx();
  const q = useReportConfig(id, true);
  return (
    <div>
      <PageHeader title="Report Builder" description="Configure the customer-ready report, then export it as PDF, Word or PowerPoint. Consultant comments added on other tabs are included automatically." />
      <Async q={q} rows={2}>
        {(d) => d.available_sections.length === 0 ? <EmptyState title="Report sections unavailable" /> : (
          <div className="grid gap-6 xl:grid-cols-[1fr_440px]"><Editor id={id} data={d} canEdit={canEdit} /><div className="xl:sticky xl:top-32 xl:self-start"><ExportsPanel id={id} canExport={canExport} /></div></div>
        )}
      </Async>
    </div>
  );
}
