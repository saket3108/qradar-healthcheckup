import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, del, downloadUrl, get, patch, post, put, uploadFile } from "./api";
import { cn, errMsg, fmtBytes, fmtCompact, fmtDate, fmtNum, fmtPct, scoreColor, scoreTone, sevColor, sevRank, timeAgo } from "./utils";
import { can, loggedIn, logout, ROLE_LABEL, userUpdated } from "@/store/auth";
import { store } from "@/store";
import { setTheme, toggleSidebar, toggleTheme, initialTheme } from "@/store/ui";
import { json, mkUser, signIn, signOut } from "@/test/harness";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); signOut(); });

describe("formatters", () => {
  it("formats bytes", () => {
    expect(fmtBytes(null)).toBe("—");
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(1536)).toBe("1.5 KB");
    expect(fmtBytes(10 * 1024 ** 3)).toBe("10.0 GB");
    expect(fmtBytes(-2048)).toBe("-2.0 KB");
    expect(fmtBytes(Infinity)).toBe("—");
  });
  it("formats numbers, percentages and compact values", () => {
    expect(fmtNum(undefined)).toBe("—");
    expect(fmtNum(12345.678, 1)).toMatch(/12,345\.7|12\.345,7|12 345,7/);
    expect(fmtPct(41.256, 1)).toBe("41.3%");
    expect(fmtPct(null)).toBe("—");
    expect(fmtCompact(1500)).toBe("1.5K");
    expect(fmtCompact(null)).toBe("—");
  });
  it("formats dates and relative time", () => {
    expect(fmtDate(null)).toBe("—");
    expect(fmtDate("not a date")).toBe("not a date");
    expect(fmtDate("2026-03-01T10:00:00Z")).toContain("2026");
    expect(fmtDate("2026-03-01T10:00:00Z", false)).toContain("2026");
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-03-10T12:00:00Z"));
    expect(timeAgo("2026-03-10T11:59:59Z")).toBe("just now");
    expect(timeAgo("2026-03-10T11:30:00Z")).toBe("30m ago");
    expect(timeAgo("2026-03-10T07:00:00Z")).toBe("5h ago");
    expect(timeAgo("2026-03-07T12:00:00Z")).toBe("3d ago");
    expect(timeAgo(undefined)).toBe("—");
    expect(timeAgo("junk")).toBe("junk");
  });
  it("ranks severities and maps scores to tones", () => {
    expect(sevRank("critical")).toBeLessThan(sevRank("low"));
    expect(sevRank("bogus")).toBe(9);
    expect([90, 75, 60, 45, 10].map(scoreTone)).toEqual(["ok", "low", "medium", "high", "critical"]);
    expect(scoreTone(null)).toBe("low");
    expect(sevColor("critical")).toContain("--critical");
    expect(sevColor("zzz")).toContain("muted-foreground");
    expect(scoreColor(95)).toContain("--ok");
  });
  it("merges class names and extracts error messages", () => {
    expect(cn("p-2", "p-4", false && "x")).toBe("p-4");
    expect(errMsg(new Error("boom"))).toBe("boom");
    expect(errMsg("text")).toBe("text");
    expect(errMsg(42)).toBe("Unexpected error");
  });
});

describe("RBAC permissions (mirror of backend)", () => {
  it("grants per role", () => {
    expect(can("administrator", "manage_users")).toBe(true);
    expect(can("consultant", "upload")).toBe(true);
    expect(can("consultant", "delete")).toBe(false);
    expect(can("manager", "export")).toBe(true);
    expect(can("manager", "edit")).toBe(false);
    expect(can("read_only", "view")).toBe(true);
    expect(can("read_only", "export")).toBe(false);
    expect(can(null, "view")).toBe(false);
    expect(ROLE_LABEL.consultant).toBe("IBM Consultant");
  });
});

describe("stores", () => {
  it("persists auth and clears it on logout", () => {
    store.dispatch(loggedIn({ token: "abc", user: mkUser("manager") }));
    expect(JSON.parse(localStorage.getItem("qhc.auth")!).token).toBe("abc");
    store.dispatch(userUpdated({ ...mkUser("manager"), full_name: "Renamed" }));
    expect(store.getState().auth.user?.full_name).toBe("Renamed");
    store.dispatch(logout());
    expect(store.getState().auth.token).toBeNull();
    expect(JSON.parse(localStorage.getItem("qhc.auth")!).user).toBeNull();
  });
  it("defaults to the dark theme and toggles", () => {
    localStorage.clear();
    expect(initialTheme()).toBe("dark");
    store.dispatch(setTheme("light"));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem("qhc.theme")).toBe("light");
    expect(initialTheme()).toBe("light");
    store.dispatch(toggleTheme());
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    const before = store.getState().ui.sidebarCollapsed;
    store.dispatch(toggleSidebar());
    expect(store.getState().ui.sidebarCollapsed).toBe(!before);
  });
});

describe("api client", () => {
  it("sends the bearer token and JSON bodies", async () => {
    signIn();
    const f = vi.fn(async () => json({ ok: 1 })); vi.stubGlobal("fetch", f);
    await expect(post("/api/x", { a: 1 })).resolves.toEqual({ ok: 1 });
    await put("/api/x", { a: 1 }); await patch("/api/x", { a: 1 }); await del("/api/x"); await get("/api/x");
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer tok");
    expect((init.headers as Headers).get("Content-Type")).toBe("application/json");
    expect(init.body).toBe('{"a":1}');
    expect(f).toHaveBeenCalledTimes(5);
  });
  it("returns undefined for 204 and the raw response when asked", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
    await expect(del("/api/x")).resolves.toBeUndefined();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("hi")));
    const r = await api<Response>("/api/x", { raw: true });
    expect(await r.text()).toBe("hi");
  });
  it("turns error payloads into ApiError messages", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Nope" }, 403)));
    await expect(get("/api/x")).rejects.toMatchObject({ status: 403, message: "Nope" });
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: [{ msg: "bad a" }, { msg: "bad b" }] }, 422)));
    await expect(get("/api/x")).rejects.toThrow("bad a; bad b");
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: { message: "structured" } }, 400)));
    await expect(get("/api/x")).rejects.toThrow("structured");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>", { status: 502, statusText: "Bad Gateway" })));
    const e = (await get("/api/x").catch((x: unknown) => x)) as Error;
    expect(e).toBeInstanceOf(ApiError);
    expect(e.message).toContain("502");
  });
  it("logs out on 401 except for the login endpoint", async () => {
    signIn();
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "expired" }, 401)));
    await get("/api/auth/login").catch(() => {});
    expect(store.getState().auth.token).toBe("tok");
    await get("/api/assessments").catch(() => {});
    expect(store.getState().auth.token).toBeNull();
  });
  it("builds authenticated download URLs", () => {
    signIn();
    expect(downloadUrl("/api/exports/1/download")).toBe("/api/exports/1/download?token=tok");
    expect(downloadUrl("/a?x=1")).toBe("/a?x=1&token=tok");
  });
});

describe("resumable chunked upload", () => {
  const mkFile = (n: number) => new File([new Uint8Array(n)], "x.tar.gz");
  const MB = 1024 * 1024;

  it("uploads in chunks, reports progress and finalises", async () => {
    signIn();
    const offsets: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (u: string, init: RequestInit) => {
      if (u === "/api/uploads") return json({ upload_id: "U1", chunk_size: MB });
      if (u.includes("/complete")) return json({ upload_id: "U1", sha256: "abc" });
      const off = Number(new URL(u, "http://x").searchParams.get("offset")); offsets.push(String(off));
      expect(init.method).toBe("PUT");
      return json({ received: Math.min(off + MB, 2.5 * MB) });
    }));
    const phases: string[] = [];
    const r = await uploadFile(mkFile(2.5 * MB), (p) => phases.push(p.phase));
    expect(r.sha256).toBe("abc");
    expect(offsets).toEqual(["0", String(MB), String(2 * MB)]);
    expect(phases.at(-1)).toBe("done");
    expect(phases).toContain("finalising");
  });

  it("re-syncs from the server on an offset conflict (resume)", async () => {
    signIn();
    let conflicted = false;
    const seen: number[] = [];
    vi.stubGlobal("fetch", vi.fn(async (u: string, init: RequestInit) => {
      if (u === "/api/uploads") return json({ upload_id: "U2", chunk_size: MB });
      if (u.endsWith("/complete")) return json({ upload_id: "U2", sha256: "z" });
      if (init.method === "GET" || init.method === undefined) return json({ received: 2 * MB });
      const off = Number(new URL(u, "http://x").searchParams.get("offset")); seen.push(off);
      if (!conflicted) { conflicted = true; return json({ detail: "offset mismatch" }, 409); }
      return json({ received: Math.min(off + MB, 3 * MB) });
    }));
    await uploadFile(mkFile(3 * MB), () => {});
    expect(seen).toEqual([0, 2 * MB]);
  });

  it("retries transient failures with back-off, then gives up", async () => {
    signIn(); vi.useFakeTimers();
    let n = 0;
    vi.stubGlobal("fetch", vi.fn(async (u: string) => {
      if (u === "/api/uploads") return json({ upload_id: "U3", chunk_size: MB });
      if (u.endsWith("/complete")) return json({ upload_id: "U3", sha256: "ok" });
      n++; return n < 3 ? json({ detail: "busy" }, 503) : json({ received: MB });
    }));
    const p = uploadFile(mkFile(MB), () => {});
    await vi.runAllTimersAsync();
    await expect(p).resolves.toMatchObject({ sha256: "ok" });
    expect(n).toBe(3);

    vi.stubGlobal("fetch", vi.fn(async (u: string) => (u === "/api/uploads" ? json({ upload_id: "U4", chunk_size: MB }) : json({ detail: "down" }, 503))));
    const q = uploadFile(mkFile(MB), () => {}).catch((e) => e);
    await vi.runAllTimersAsync();
    expect(await q).toMatchObject({ status: 503 });
  });

  it("does not retry client errors and honours abort", async () => {
    signIn();
    vi.stubGlobal("fetch", vi.fn(async (u: string) => (u === "/api/uploads" ? json({ upload_id: "U5", chunk_size: MB }) : json({ detail: "too large" }, 413))));
    await expect(uploadFile(mkFile(MB), () => {})).rejects.toMatchObject({ status: 413 });
    vi.stubGlobal("fetch", vi.fn(async () => json({ upload_id: "U6", chunk_size: MB })));
    const ac = new AbortController(); ac.abort();
    await expect(uploadFile(mkFile(MB), () => {}, ac.signal)).rejects.toMatchObject({ name: "AbortError" });
  });
});
