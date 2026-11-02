import { FileSearch, Package } from "lucide-react";
import { Badge } from "@/components/ui/badges";
import { ErrorState, LoadingGrid } from "@/components/common";
import { useDiagnostics } from "@/lib/queries";
import { fmtBytes, fmtNum } from "@/lib/utils";

export const UNSUPPORTED_MESSAGE = "Archive extracted successfully but no supported QRadar artifacts were detected. See diagnostics.";

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md border bg-card/60 p-3"><div className="text-xs text-muted-foreground">{label}</div><div className="mt-0.5 text-sm font-semibold">{value}</div></div>;
}

/** Shown when an archive was extracted but contains no recognisable QRadar get_logs artifacts. */
export function DiagnosticsPanel({ id }: { id: string }) {
  const q = useDiagnostics(id, true);
  if (q.isLoading) return <LoadingGrid />;
  if (q.error) return <ErrorState error={q.error} retry={() => void q.refetch()} />;
  const d = q.data ?? {};
  const indicators = Object.keys(d.indicators ?? {});
  return (
    <div className="mx-auto mt-6 max-w-4xl space-y-4">
      <div className="card-surface p-6">
        <div className="flex items-start gap-3">
          <FileSearch className="mt-0.5 size-6 text-sev-medium" />
          <div>
            <h2 className="font-semibold">No supported QRadar artifacts detected</h2>
            <p role="status" className="mt-1 text-sm text-muted-foreground">{UNSUPPORTED_MESSAGE}</p>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Detected as" value={d.detected_kind?.split(" (")[0] ?? "Unknown"} />
          <Stat label="Files in archive" value={fmtNum(d.total_members ?? 0)} />
          <Stat label="Archive type" value={d.archive_type ?? "—"} />
          <Stat label="Uncompressed size" value={fmtBytes(d.total_bytes)} />
        </div>
        {d.identifier && <p className="mt-3 text-sm">Identifier found in the package: <Badge tone="info">{d.identifier}</Badge></p>}
        {d.detected_kind && d.detected_kind.includes("(") && <p className="mt-2 text-sm text-muted-foreground">{d.detected_kind}</p>}
        <p className="mt-3 text-sm">QRadar indicators found: {indicators.length ? indicators.join(", ") : <strong>none</strong>}</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="card-surface p-5" aria-label="Root folders">
          <h3 className="mb-2 text-sm font-semibold">Root folders</h3>
          {(d.root_folders?.length ?? 0) === 0 ? <p className="text-sm text-muted-foreground">No folders - files are at the archive root.</p> : (
            <ul className="space-y-1 text-sm">{d.root_folders!.map((r) => <li key={r.name} className="flex justify-between gap-3"><span className="truncate font-mono text-xs">{r.name}/</span><span className="text-muted-foreground">{fmtNum(r.files)} files</span></li>)}</ul>
          )}
          {(d.top_level_files?.length ?? 0) > 0 && <p className="mt-2 break-all text-xs text-muted-foreground">Top-level files: {d.top_level_files!.join(", ")}</p>}
        </section>
        <section className="card-surface p-5" aria-label="Contents by type">
          <h3 className="mb-2 text-sm font-semibold">Contents by extension</h3>
          <div className="flex flex-wrap gap-1.5">{Object.entries(d.extensions ?? {}).map(([k, v]) => <Badge key={k} tone="neutral">{k} · {v}</Badge>)}</div>
          {(d.nested_archives?.length ?? 0) > 0 && (<>
            <h3 className="mb-1 mt-4 flex items-center gap-1.5 text-sm font-semibold"><Package className="size-4" />Nested archives (extracted)</h3>
            <ul className="space-y-0.5 text-xs font-mono">{d.nested_archives!.map((n) => <li key={n} className="break-all">{n}</li>)}</ul>
          </>)}
        </section>
      </div>

      <section className="card-surface p-5" aria-label="Sample files">
        <h3 className="mb-2 text-sm font-semibold">Sample files ({d.sample_files?.length ?? 0} of {fmtNum(d.total_members ?? 0)})</h3>
        <ul className="max-h-72 space-y-0.5 overflow-auto font-mono text-xs">{(d.sample_files ?? []).map((f) => <li key={f} className="break-all">{f}</li>)}</ul>
      </section>

      <section className="card-surface p-5" aria-label="What to do next">
        <h3 className="mb-2 text-sm font-semibold">What to do next</h3>
        <ul className="list-disc space-y-1 pl-5 text-sm">{(d.guidance ?? []).map((g) => <li key={g}>{g}</li>)}</ul>
      </section>
    </div>
  );
}
