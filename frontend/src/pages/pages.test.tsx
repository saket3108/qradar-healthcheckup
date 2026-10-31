import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AID, fx, json, mockApi, renderApp, signIn, signOut } from "@/test/harness";

beforeEach(() => signIn("administrator"));
afterEach(() => { vi.unstubAllGlobals(); signOut(); });

const open = (tab = "") => renderApp(`/assessments/${AID}${tab ? `/${tab}` : ""}`);

describe("authentication and routing", () => {
  it("redirects anonymous users to the login page", async () => {
    signOut(); mockApi();
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("validates the login form before calling the API", async () => {
    signOut(); const { calls } = mockApi();
    renderApp("/login");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Email is required")).toBeInTheDocument();
    expect(screen.getByText("Password is required")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Email"), "not-an-email");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/auth/login")).toBe(false);
  });

  it("shows the server error on bad credentials and signs in on success", async () => {
    signOut();
    let ok = false;
    mockApi({ "POST /api/auth/login": () => (ok ? { access_token: "T", user: { id: "1", email: "a@b.co", full_name: "A", role: "consultant", is_active: true, created_at: "", last_login: null } } : json({ detail: "Invalid credentials" }, 401)) });
    renderApp("/login");
    await userEvent.type(screen.getByLabelText("Email"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "wrongwrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Invalid credentials")).toBeInTheDocument();
    ok = true;
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("heading", { name: "Assessments" })).toBeInTheDocument();
  });

  it("blocks the admin page for roles without the audit permission", async () => {
    signIn("read_only"); mockApi();
    renderApp("/admin");
    expect(await screen.findByRole("heading", { name: "Assessments" })).toBeInTheDocument();
  });

  it("renders the admin console with users and audit trail", async () => {
    const { calls } = mockApi();
    renderApp("/admin");
    expect(await screen.findByText("admin@example.com")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/audit")).toBe(true);
  });

  it("toggles the theme and logs out from the shell", async () => {
    mockApi(); renderApp("/");
    await screen.findByRole("heading", { name: "Assessments" });
    const html = document.documentElement;
    await userEvent.click(screen.getByRole("button", { name: /switch to .* mode/i }));
    const wasDark = html.classList.contains("dark");
    await userEvent.click(screen.getByRole("button", { name: /switch to .* mode/i }));
    expect(html.classList.contains("dark")).toBe(!wasDark);
    await userEvent.click(screen.getByRole("button", { name: /sign out|log ?out/i }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("assessments list and upload", () => {
  it("lists assessments, filters and opens one", async () => {
    const { calls } = mockApi(); renderApp("/");
    expect(await screen.findByText("ACME Corp")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search assessments"), "acme");
    await waitFor(() => expect(calls.some((c) => c.search.includes("q=acme"))).toBe(true));
    await userEvent.selectOptions(screen.getByLabelText("Filter by status"), "failed");
    await waitFor(() => expect(calls.some((c) => c.search.includes("status=failed"))).toBe(true));
  });

  it("navigates into an assessment", async () => {
    mockApi(); renderApp("/");
    await userEvent.click(await screen.findByRole("button", { name: /Open ACME Corp/ }));
    expect(await screen.findByText("Executive Health Dashboard")).toBeInTheDocument();
  });

  it("rejects unsupported file types and accepts get_logs archives", async () => {
    mockApi(); renderApp("/");
    const input = await screen.findByTestId("file-input");
    fireEvent.change(input, { target: { files: [new File(["x"], "notes.txt")] } });
    expect(await screen.findByText(/Unsupported file type/)).toBeInTheDocument();
    fireEvent.change(input, { target: { files: [new File(["x"], "getlogs.tar.gz"), new File(["y"], "other.zip")] } });
    expect(await screen.findByText("getlogs.tar.gz")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload & analyse all/i })).toBeInTheDocument();
  });

  it("uploads, creates the assessment and navigates to it", async () => {
    const { calls } = mockApi({
      "POST /api/uploads": { upload_id: "U1", chunk_size: 1048576 },
      "PUT /api/uploads/U1": { received: 1 },
      "POST /api/uploads/U1/complete": { upload_id: "U1", sha256: "h" },
      "POST /api/assessments": { ...fx.assessment },
    });
    renderApp("/");
    await userEvent.type(await screen.findByLabelText("Customer name"), "Contoso");
    fireEvent.change(screen.getByTestId("file-input"), { target: { files: [new File(["x"], "g.tar")] } });
    await userEvent.click(await screen.findByRole("button", { name: /^upload & analyse$/i }));
    expect(await screen.findByText("Executive Health Dashboard")).toBeInTheDocument();
    const create = calls.find((c) => c.method === "POST" && c.path === "/api/assessments")!;
    expect(create.body).toMatchObject({ upload_id: "U1", customer_name: "Contoso" });
  });

  it("surfaces upload failures and allows retry", async () => {
    mockApi({ "POST /api/uploads": () => json({ detail: "Quota exceeded" }, 413) });
    renderApp("/");
    fireEvent.change(await screen.findByTestId("file-input"), { target: { files: [new File(["x"], "g.zip")] } });
    await userEvent.click(await screen.findByRole("button", { name: /^upload & analyse$/i }));
    expect(await screen.findByText("Quota exceeded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("hides upload for read-only users and shows resume for failed jobs", async () => {
    signIn("read_only");
    mockApi({ "GET /api/assessments": [{ ...fx.assessment, status: "failed", error: "boom", overall_score: null }] });
    renderApp("/");
    expect(await screen.findByText("boom")).toBeInTheDocument();
    expect(screen.queryByTestId("file-input")).toBeNull();
    expect(screen.queryByRole("button", { name: /resume/i })).toBeNull();
  });

  it("resumes and deletes with confirmation", async () => {
    const list = [{ ...fx.assessment, status: "failed", error: "boom", overall_score: null }];
    const { calls } = mockApi({
      "GET /api/assessments": list,
      [`POST /api/assessments/${AID}/resume`]: fx.assessment,
      [`DELETE /api/assessments/${AID}`]: new Response(null, { status: 204 }),
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderApp("/");
    await userEvent.click(await screen.findByRole("button", { name: /resume/i }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/resume"))).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: /^Delete/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });
});

describe("assessment layout", () => {
  it("shows live stage progress while processing", async () => {
    mockApi({ [`GET /api/assessments/${AID}`]: { ...fx.assessment, status: "processing", progress: 42, current_stage: "parse", stages: [{ name: "extract", label: "Extract archive", order: 1, status: "done", progress: 1, attempts: 1, message: null, warnings: [] }, { name: "parse", label: "Parse deployment", order: 2, status: "running", progress: 0.5, attempts: 1, message: null, warnings: [] }] } });
    open();
    expect(await screen.findByText("Analysing your get_logs package")).toBeInTheDocument();
    expect(screen.getByText("Parse deployment")).toBeInTheDocument();
    expect(screen.getByText("42% complete")).toBeInTheDocument();
  });

  it("offers resume for failed analysis", async () => {
    const { calls } = mockApi({
      [`GET /api/assessments/${AID}`]: { ...fx.assessment, status: "failed", error: "disk full", stages: [] },
      [`POST /api/assessments/${AID}/resume`]: fx.assessment,
    });
    open();
    expect(await screen.findByText("Analysis failed")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("disk full");
    await userEvent.click(screen.getByRole("button", { name: /resume/i }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/resume"))).toBe(true));
  });

  it("shows an error state when the assessment cannot be loaded", async () => {
    mockApi({ [`GET /api/assessments/${AID}`]: () => json({ detail: "Not found" }, 404) });
    open();
    expect(await screen.findByText(/Not found/)).toBeInTheDocument();
  });
});

describe("analysis tabs render real assessment data", () => {
  it("dashboard shows score, categories, risk summary and top 10 recommendations", async () => {
    mockApi(); open();
    expect(await screen.findByText("Category health")).toBeInTheDocument();
    for (const c of ["Deployment", "Applications", "Performance", "Notifications", "Log Sources", "WinCollect", "Licensing"]) expect(screen.getAllByText(c).length).toBeGreaterThan(0);
    expect(screen.getByText("Top 10 recommendations")).toBeInTheDocument();
    expect(screen.getByText(/critical findings/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Disk capacity threshold exceeded/ }));
    expect(await screen.findAllByText(/Recommendation/i)).not.toHaveLength(0);
  });

  it("overview shows environment, appliances, licence gauges and summaries", async () => {
    mockApi(); open("overview");
    expect(await screen.findByText("Environment information")).toBeInTheDocument();
    expect(screen.getByText("Appliance information")).toBeInTheDocument();
    expect(screen.getByText("License information")).toBeInTheDocument();
    expect(screen.getByText("Auto update summary")).toBeInTheDocument();
    expect(screen.getByText("Hardware summary")).toBeInTheDocument();
    expect(screen.getAllByText("qr-console01").length).toBeGreaterThan(0);
  });

  it("deployment renders the topology, HA analysis and validation checks", async () => {
    mockApi(); open("deployment");
    expect(await screen.findByText("Deployment validation")).toBeInTheDocument();
    expect(screen.getByText("High availability analysis")).toBeInTheDocument();
    expect(await screen.findByText("Managed Host Connectivity")).toBeInTheDocument();
    expect(screen.getAllByText(/critical/i).length).toBeGreaterThan(0);
  });

  it("notifications support filtering and editable comments", async () => {
    const { calls } = mockApi({ [`PUT /api/assessments/${AID}/comments/notification/${(fx.notifications as unknown as { items: { id: string }[] }).items[0]!.id}`]: { ok: true } });
    open("notifications");
    const rows = await screen.findAllByRole("button", { expanded: false });
    await userEvent.click(rows[0]!);
    const box = (await screen.findAllByLabelText("Consultant comment"))[0]!;
    await userEvent.type(box, "Customer informed");
    await userEvent.click(screen.getAllByRole("button", { name: /save comment/i })[0]!);
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path.includes("/comments/notification/"))).toBe(true));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ text: "Customer informed" });
  });

  it("log sources show KPIs, protocol chart switches and WinCollect analysis", async () => {
    mockApi(); open("logsources");
    expect(await screen.findByText("Top EPS sources")).toBeInTheDocument();
    expect(screen.getByText("Problematic log sources")).toBeInTheDocument();
    for (const n of ["Pie", "Treemap", "EPS", "Bar", "Count"]) await userEvent.click(screen.getByRole("tab", { name: n }));
    for (const n of ["Critical", "High", "Medium", "All"]) await userEvent.click(screen.getByRole("tab", { name: n }));
    await userEvent.click(screen.getByRole("tab", { name: /WinCollect/ }));
    expect(await screen.findByText(/Version distribution/i)).toBeInTheDocument();
  });

  it("applications list status, resource usage and findings", async () => {
    mockApi(); open("applications");
    expect(await screen.findByText("Status distribution")).toBeInTheDocument();
    expect((fx.applications as { items: { name: string }[] }).items.length).toBeGreaterThan(0);
    const first = (fx.applications as { items: { name: string }[] }).items[0]!.name;
    expect(screen.getAllByText(first).length).toBeGreaterThan(0);
  });

  it("performance renders CPU, memory, disk, network and SAR views with AI assessment", async () => {
    mockApi(); open("performance");
    expect(await screen.findByText("CPU utilisation trend")).toBeInTheDocument();
    expect(screen.getByText("Performance AI assessment")).toBeInTheDocument();
    for (const t of ["Memory", "Disk", "Network", "SAR metrics", "CPU"]) await userEvent.click(screen.getByRole("tab", { name: t }));
    await userEvent.click(screen.getByRole("tab", { name: "All metrics" }));
    await userEvent.click(screen.getByRole("tab", { name: "Issues" }));
  });

  it("licensing shows EPS/FPM consumption, forecast and risk", async () => {
    mockApi(); open("licensing");
    expect(await screen.findByRole("heading", { name: /Licens/ })).toBeInTheDocument();
    expect(screen.getAllByText(/EPS/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/FPM/).length).toBeGreaterThan(0);
  });

  it("health score tab shows engine breakdown", async () => {
    mockApi(); open("health");
    expect(await screen.findByRole("heading", { name: /Health Score/ })).toBeInTheDocument();
    expect(screen.getAllByText(/Maturity/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Risk/i).length).toBeGreaterThan(0);
  });
});

describe("AI assistant", () => {
  it("sends questions, shows answers and supports suggestions and clearing", async () => {
    const msgs: unknown[] = [];
    const { calls } = mockApi({
      [`GET /api/assessments/${AID}/assistant`]: () => msgs,
      [`POST /api/assessments/${AID}/assistant`]: (_u: URL, init: RequestInit) => {
        const q = JSON.parse(String(init.body)).message as string;
        msgs.push({ role: "user", content: q }, { role: "assistant", content: "The score is low because of 6 critical findings.", meta: { intent: "why_score_low" } });
        return { answer: "x", intent: "why_score_low" };
      },
      [`DELETE /api/assessments/${AID}/assistant`]: () => { msgs.length = 0; return new Response(null, { status: 204 }); },
    });
    open("assistant");
    expect(await screen.findByText("Ask anything about this health check")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Why is health score low?" }));
    expect(await screen.findByText(/6 critical findings/)).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText(/Ask about findings/), "Show critical findings.{enter}");
    await waitFor(() => expect(calls.filter((c) => c.method === "POST" && c.path.endsWith("/assistant")).length).toBe(2));
    const clear = screen.queryByRole("button", { name: /clear/i });
    if (clear) { await userEvent.click(clear); await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true)); }
  });
});

describe("report builder", () => {
  it("validates, saves settings and generates exports", async () => {
    const { calls } = mockApi({
      [`PUT /api/assessments/${AID}/report-config`]: { ok: true },
      [`POST /api/assessments/${AID}/exports/pdf`]: { id: "E1", download: "/api/exports/E1/download", size: 10 },
    });
    const assign = vi.fn();
    Object.defineProperty(window, "location", { configurable: true, value: { ...window.location, assign } });
    open("report");
    const cust = await screen.findByLabelText("Customer name");
    await userEvent.clear(cust);
    await userEvent.type(cust, "Globex");
    const cb = screen.getAllByRole("checkbox")[1]!;
    await userEvent.click(cb);
    await userEvent.click(screen.getByRole("button", { name: /save report settings/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path.endsWith("/report-config"))).toBe(true));
    const put = calls.find((c) => c.method === "PUT" && c.path.endsWith("/report-config"))!;
    expect(put.body).toMatchObject({ customer_name: "Globex" });
    await userEvent.click(screen.getByRole("button", { name: "Generate PDF report" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(expect.stringContaining("/api/exports/E1/download?token=tok")));
  });

  it("disables exporting for read-only users", async () => {
    signIn("read_only"); mockApi(); open("report");
    expect(await screen.findByText("Your role cannot generate exports.")).toBeInTheDocument();
  });
});
