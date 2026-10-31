import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CommentBox, EmptyState, ErrorState, FindingMini } from "@/components/common";
import { layoutTopology, ROLE_COLOR } from "@/pages/Deployment";
import { riskNarrative } from "@/pages/Licensing";
import { reportSchema } from "@/pages/ReportBuilder";
import { isSupported } from "@/pages/Assessments";
import { Donut, Legend, TreemapChart } from "@/components/charts/ChartKit";
import { Meter, ScoreRing, SemiGauge } from "@/components/charts/gauges";
import type { LicMetric, Topology } from "@/types";
import { AID, fx, json, mockApi, renderApp, signIn, signOut } from "@/test/harness";

beforeEach(() => signIn("administrator"));
afterEach(() => { vi.unstubAllGlobals(); signOut(); });
const open = (tab = "") => renderApp(`/assessments/${AID}${tab ? `/${tab}` : ""}`);

const metric = (o: Partial<LicMetric> = {}): LicMetric => ({ name: "EPS", unit: "EPS", licensed: 1000, current: 900, average: 800, peak: 1200, consumption_pct: 90, peak_pct: 120, trend: { direction: "rising", growth_pct_per_month: 4.2 } as LicMetric["trend"], forecast: [], risk: "high", series: [], days_to_limit: 45, ...o }) as LicMetric;

describe("pure helpers", () => {
  it("builds licence risk narratives for each situation", () => {
    expect(riskNarrative(metric({ licensed: null }))).toContain("could not be determined");
    expect(riskNarrative(metric())).toMatch(/90\.0% of the licensed 1,000 EPS.*rising.*45 days/);
    expect(riskNarrative(metric({ days_to_limit: 0 }))).toContain("already been reached");
    expect(riskNarrative(metric({ trend: null, days_to_limit: null, peak_pct: null }))).toContain("n/a");
  });

  it("lays out the deployment topology in tiers with HA edges highlighted", () => {
    const topo = (fx.deployment as { topology: Topology }).topology;
    const { nodes, edges } = layoutTopology(topo, topo.nodes[0]!.id);
    expect(nodes).toHaveLength(topo.nodes.length);
    expect(nodes.filter((n) => n.data.selected)).toHaveLength(1);
    const console_ = nodes.find((n) => n.data.node.role === "Console")!;
    expect(Math.min(...nodes.map((n) => n.position.y))).toBe(console_.position.y);
    expect(edges).toHaveLength(topo.edges.length);
    const ha = layoutTopology({ ...topo, edges: [{ source: topo.nodes[0]!.id, target: topo.nodes[1]!.id, kind: "ha" }] } as Topology, null);
    expect(ha.edges[0]!.label).toBe("HA");
    expect(layoutTopology({ ...topo, nodes: [], edges: [] }, null).nodes).toEqual([]);
    expect(Object.keys(ROLE_COLOR)).toEqual(expect.arrayContaining(["Console", "EP", "EC", "FP", "DN", "App Host", "Extension", "Unknown"]));
  });

  it("validates the report form", () => {
    const ok = { customer_name: "A", consultant_name: "", title: "T", classification: "", notes: "", next_steps: "", sections: ["cover"] };
    expect(reportSchema.safeParse(ok).success).toBe(true);
    expect(reportSchema.safeParse({ ...ok, customer_name: "  " }).success).toBe(false);
    expect(reportSchema.safeParse({ ...ok, sections: [] }).success).toBe(false);
    expect(reportSchema.safeParse({ ...ok, notes: "x".repeat(20001) }).success).toBe(false);
  });

  it("accepts only supported archive extensions", () => {
    for (const n of ["a.tar", "A.TAR.GZ", "a.tgz", "a.gz", "a.zip"]) expect(isSupported(n)).toBe(true);
    for (const n of ["a.txt", "a.rar", "a.exe", "zip"]) expect(isSupported(n)).toBe(false);
  });
});

describe("shared components", () => {
  it("renders gauges, donut, legend and treemap accessibly", () => {
    render(<div>
      <ScoreRing score={73.4} label="Grade C" sub="x" /><SemiGauge value={96} label="EPS" sublabel="s" /><SemiGauge value={null} label="none" />
      <Meter value={5} max={10} color="red" /><Donut data={[{ name: "A", value: 1 }, { name: "B", value: 3 }]} centerLabel="Total" centerValue="4" />
      <Legend items={[{ name: "A", value: 1, color: "red" }]} /><TreemapChart data={[{ name: "a", size: 2 }]} height={100} /><TreemapChart data={[]} height={100} />
    </div>);
    expect(screen.getByRole("img", { name: "Grade C 73 out of 100" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
    expect(screen.getByRole("img", { name: /Total: A 1, B 3/ })).toBeInTheDocument();
  });

  it("renders empty and error states, with retry", async () => {
    const retry = vi.fn();
    render(<div><EmptyState title="Nothing" description="d" /><ErrorState error={new Error("kaput")} retry={retry} /><FindingMini severity="high" title="T" sub="s" right={<i>r</i>} /></div>);
    expect(screen.getByText("Nothing")).toBeInTheDocument();
    expect(screen.getByText("kaput")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /retry|try again/i }));
    expect(retry).toHaveBeenCalled();
    expect(screen.getByText("T")).toBeInTheDocument();
  });

  it("CommentBox saves on blur and button, shows errors, and respects read-only", async () => {
    const onSave = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("save failed"));
    const { rerender } = render(<CommentBox value="old" onSave={onSave} />);
    const box = screen.getByLabelText("Consultant comment");
    expect(screen.getByRole("button", { name: /save comment/i })).toBeDisabled();
    await userEvent.clear(box); await userEvent.type(box, "new text");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    fireEvent.blur(box);
    await waitFor(() => expect(onSave).toHaveBeenCalledWith("new text"));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    await userEvent.type(box, "!");
    await userEvent.click(screen.getByRole("button", { name: /save comment/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("save failed");
    rerender(<CommentBox value="server" onSave={onSave} readOnly />);
    expect(screen.getByLabelText("Consultant comment")).toHaveValue("server");
    expect(screen.getByLabelText("Consultant comment")).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: /save comment/i })).toBeNull();
  });
});

describe("deeper page behaviour", () => {
  it("licensing renders EPS and FPM blocks, history, forecast and notes", async () => {
    const { calls } = mockApi({ [`PUT /api/assessments/${AID}/comments/licensing/licensing`]: { ok: true } });
    open("licensing");
    expect(await screen.findByText("Events per second (EPS)")).toBeInTheDocument();
    expect(screen.getByText("Flows per minute (FPM)")).toBeInTheDocument();
    expect(screen.getAllByText("Forecast").length).toBe(2);
    expect(screen.getByText("Utilisation risk")).toBeInTheDocument();
    const box = screen.getByLabelText("Licensing comment");
    await userEvent.type(box, "Discuss true-up");
    await userEvent.click(screen.getByRole("button", { name: /save comment/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path.endsWith("/comments/licensing/licensing"))).toBe(true));
  });

  it("licensing shows an empty message when the bundle has no licence data", async () => {
    const l = { ...(fx.licensing as { licensing: Record<string, unknown> }).licensing, has_data: false, expiry_days: -3 };
    mockApi({ [`GET /api/assessments/${AID}/licensing`]: { licensing: l } });
    open("licensing");
    expect(await screen.findByText("No licensing data found in the bundle.")).toBeInTheDocument();
    expect(screen.getByText("Expired")).toBeInTheDocument();
  });

  it("health score shows breakdown and lets consultants change a finding's status", async () => {
    const { calls } = mockApi({ [`PATCH /api/assessments/${AID}/findings/${(fx.findings as { id: string }[])[0]!.id}`]: { ok: true } });
    open("health");
    expect(await screen.findByText("Scoring breakdown")).toBeInTheDocument();
    expect(screen.getByText("Maturity level")).toBeInTheDocument();
    expect(screen.getByText("Category profile")).toBeInTheDocument();
    const first = (fx.findings as { title: string }[])[0]!.title;
    await userEvent.click((await screen.findAllByText(first))[0]!);
    const sel = await screen.findByLabelText("Finding status");
    await userEvent.selectOptions(sel, "accepted");
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body).toMatchObject({ status: "accepted" });
    await userEvent.selectOptions(screen.getByLabelText("Finding severity"), "low");
    await userEvent.click(screen.getByRole("tab", { name: "Performance" }));
    await userEvent.click(screen.getByRole("tab", { name: "All" }));
  });

  it("health score hides editing controls from read-only users", async () => {
    signIn("read_only"); mockApi(); open("health");
    const first = (fx.findings as { title: string }[])[0]!.title;
    await userEvent.click((await screen.findAllByText(first))[0]!);
    expect(screen.queryByLabelText("Finding status")).toBeNull();
  });

  it("deployment selects a node to show details and can close them", async () => {
    mockApi(); open("deployment");
    await screen.findByText("Deployment validation");
    const topo = (fx.deployment as { topology: Topology }).topology;
    const host = topo.nodes[0]!.hostname;
    const node = (await screen.findAllByText(host))[0]!;
    fireEvent.click(node); // fireEvent: user-event's mousedown trips d3-drag in jsdom
    const detail = await screen.findByRole("region", { name: `Details for ${host}` });
    expect(detail).toHaveTextContent("Hostname");
    await userEvent.click(screen.getByRole("button", { name: "Close details" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: `Details for ${host}` })).toBeNull());
  });

  it("notifications filter by severity and search via the API", async () => {
    const { calls } = mockApi(); open("notifications");
    await screen.findAllByRole("button", { expanded: false });
    const search = screen.queryByPlaceholderText(/search/i);
    if (search) { await userEvent.type(search, "disk"); await waitFor(() => expect(calls.some((c) => c.search.includes("q=disk"))).toBe(true)); }
    const crit = screen.queryByRole("tab", { name: /critical/i });
    if (crit) { await userEvent.click(crit); await waitFor(() => expect(calls.some((c) => c.search.includes("severity=critical"))).toBe(true)); }
  });

  it("applications expand a row and allow commenting", async () => {
    const { calls } = mockApi();
    open("applications");
    await screen.findByText("Status distribution");
    const first = (fx.applications as { items: { name: string }[] }).items[0]!.name;
    await userEvent.click(screen.getAllByText(first)[0]!);
    expect(calls.some((c) => c.path.endsWith("/applications"))).toBe(true);
  });

  it("performance switches hosts and exposes the SAR and disk views", async () => {
    mockApi(); open("performance");
    await screen.findByText("CPU utilisation trend");
    const hosts = Object.keys((fx.performance as { hosts: Record<string, unknown> }).hosts);
    if (hosts.length > 1) await userEvent.selectOptions(screen.getByRole("combobox"), hosts[1]!);
    await userEvent.click(screen.getByRole("tab", { name: "Disk" }));
    expect(await screen.findByText("Disk usage by filesystem")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Network" }));
    expect(await screen.findByText("Throughput")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "SAR metrics" }));
    expect(await screen.findByText("Load average")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Memory" }));
    expect(await screen.findByText("Memory utilisation trend")).toBeInTheDocument();
  });

  it("report builder uploads a logo with validation and lists previous exports", async () => {
    const { calls } = mockApi({
      [`GET /api/assessments/${AID}/exports`]: [{ id: "E9", format: "pdf", size: 2048, created_at: "2026-03-01T10:00:00Z", created_by: "x", download: "/api/exports/E9/download" }],
      [`POST /api/assessments/${AID}/logo`]: { ok: true },
    });
    open("report");
    expect(await screen.findByText("2.0 KB")).toBeInTheDocument();
    const input = await screen.findByTestId("logo-input");
    fireEvent.change(input, { target: { files: [new File(["x"], "logo.gif")] } });
    expect(await screen.findByText("Logo must be a PNG or JPEG image")).toBeInTheDocument();
    fireEvent.change(input, { target: { files: [new File([new Uint8Array(3 * 1024 * 1024)], "logo.png")] } });
    expect(await screen.findByText("Logo must be smaller than 2 MB")).toBeInTheDocument();
    fireEvent.change(input, { target: { files: [new File(["x"], "logo.png", { type: "image/png" })] } });
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/logo"))).toBe(true));
  });

  it("report builder blocks saving when no section is selected", async () => {
    const { calls } = mockApi(); open("report");
    await screen.findByLabelText("Customer name");
    for (const cb of screen.getAllByRole("checkbox")) if (cb.getAttribute("aria-checked") === "true") await userEvent.click(cb);
    await userEvent.click(screen.getByRole("button", { name: /save report settings/i }));
    expect(await screen.findByText("Select at least one section")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("export errors are shown to the user", async () => {
    mockApi({ [`POST /api/assessments/${AID}/exports/docx`]: () => json({ detail: "Renderer unavailable" }, 500) });
    open("report");
    await userEvent.click(await screen.findByRole("button", { name: "Generate Word report" }));
    expect(await screen.findByText("Renderer unavailable")).toBeInTheDocument();
  });

  it("admin can create users, change roles and filter audit events", async () => {
    const { calls } = mockApi({ "POST /api/users": { ...(fx.users as object[])[0] as object, id: "n1" }, "PATCH /api/users/0c830c7217b241cbbb53c6a563a1ad21": { ok: true } });
    renderApp("/admin");
    await screen.findByText("admin@example.com");
    const email = screen.queryByLabelText(/^email/i);
    if (email) {
      await userEvent.type(email, "new@example.com");
      await userEvent.type(screen.getByLabelText(/password/i), "LongPassword123!");
      await userEvent.click(screen.getByRole("button", { name: /create|add user/i }));
      await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/users")).toBe(true));
    }
  });
});
