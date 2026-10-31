import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import type { ReactElement } from "react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import App from "@/App";
import { store } from "@/store";
import { loggedIn, logout } from "@/store/auth";
import type { Role, User } from "@/types";
import assessment from "./fixtures/assessment.json";
import assessments from "./fixtures/assessments.json";
import overview from "./fixtures/overview.json";
import deployment from "./fixtures/deployment.json";
import logsources from "./fixtures/logsources.json";
import licensing from "./fixtures/licensing.json";
import performance from "./fixtures/performance.json";
import health from "./fixtures/health.json";
import applications from "./fixtures/applications.json";
import notifications from "./fixtures/notifications.json";
import findings from "./fixtures/findings.json";
import reportconfig from "./fixtures/reportconfig.json";
import users from "./fixtures/users.json";
import audit from "./fixtures/audit.json";

export const AID = (assessment as { id: string }).id;
export const fx = { assessment, assessments, overview, deployment, logsources, licensing, performance, health, applications, notifications, findings, reportconfig, users, audit };

export const mkUser = (role: Role): User => ({ id: "u1", email: `${role}@example.com`, full_name: `Test ${role}`, role, is_active: true, created_at: "2026-01-01T00:00:00", last_login: null });
export const signIn = (role: Role = "administrator") => { act(() => { store.dispatch(loggedIn({ token: "tok", user: mkUser(role) })); }); };
export const signOut = () => { act(() => { store.dispatch(logout()); }); };

type Handler = (url: URL, init: RequestInit & { json?: unknown }) => unknown | Response | Promise<unknown | Response>;
export type Routes = Record<string, Handler | unknown>;

const A = `/api/assessments/${AID}`;
export const defaultRoutes = (): Routes => ({
  "GET /api/assessments": assessments,
  [`GET ${A}`]: assessment,
  [`GET ${A}/overview`]: overview,
  [`GET ${A}/deployment`]: deployment,
  [`GET ${A}/logsources-analysis`]: logsources,
  [`GET ${A}/licensing`]: licensing,
  [`GET ${A}/performance`]: performance,
  [`GET ${A}/health`]: health,
  [`GET ${A}/applications`]: applications,
  [`GET ${A}/notifications`]: notifications,
  [`GET ${A}/findings`]: findings,
  [`GET ${A}/comments`]: [],
  [`GET ${A}/report-config`]: reportconfig,
  [`GET ${A}/exports`]: [],
  [`GET ${A}/assistant`]: [],
  "GET /api/users": users,
  "GET /api/audit": audit,
});

export const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

export interface Call { method: string; path: string; search: string; body: unknown }

/** Installs a routed fetch mock. Route keys are "METHOD /path" (exact match, query ignored). */
export function mockApi(overrides: Routes = {}) {
  const routes = { ...defaultRoutes(), ...overrides };
  const calls: Call[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    let body: unknown = init.body;
    if (typeof body === "string") { try { body = JSON.parse(body); } catch { /* keep */ } }
    calls.push({ method, path: url.pathname, search: url.search, body });
    const h = routes[`${method} ${url.pathname}`];
    if (h === undefined) return json({ detail: `no mock for ${method} ${url.pathname}` }, 404);
    const out = typeof h === "function" ? await (h as Handler)(url, init) : h;
    return out instanceof Response ? out : json(out);
  });
  vi.stubGlobal("fetch", fn);
  return { calls, fn };
}

export function renderApp(route: string, ui: ReactElement = <App />) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  return render(
    <Provider store={store}><QueryClientProvider client={qc}><MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter></QueryClientProvider></Provider>,
  );
}
