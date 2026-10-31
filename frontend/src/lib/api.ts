import { store } from "@/store";
import { logout } from "@/store/auth";

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) { super(message); }
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

function token(): string | null { return store.getState().auth.token; }

function detailOf(body: unknown, fallback: string): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? "").filter(Boolean).join("; ") || fallback;
  if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
  return fallback;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown; raw?: boolean } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const t = token();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  let body = init.body;
  if (init.json !== undefined) { headers.set("Content-Type", "application/json"); body = JSON.stringify(init.json); }
  const res = await fetch(`${BASE}${path}`, { ...init, headers, body });
  if (res.status === 401 && t && !path.startsWith("/api/auth/login")) store.dispatch(logout());
  if (!res.ok) {
    let parsed: unknown = null;
    try { parsed = await res.json(); } catch { /* not json */ }
    throw new ApiError(res.status, detailOf(parsed, `${res.status} ${res.statusText}`), parsed);
  }
  if (init.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const get = <T,>(p: string) => api<T>(p);
export const post = <T,>(p: string, json?: unknown) => api<T>(p, { method: "POST", json });
export const put = <T,>(p: string, json?: unknown) => api<T>(p, { method: "PUT", json });
export const patch = <T,>(p: string, json?: unknown) => api<T>(p, { method: "PATCH", json });
export const del = <T,>(p: string) => api<T>(p, { method: "DELETE" });

/** Authenticated file download (adds the token as a query parameter so the browser can stream it). */
export function downloadUrl(path: string): string {
  const t = token();
  return `${BASE}${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(t ?? "")}`;
}

export interface UploadProgress { loaded: number; total: number; speed: number; phase: "uploading" | "finalising" | "done" }

/** Resumable chunked upload. Survives interruptions: on offset mismatch it re-syncs from the server. */
export async function uploadFile(file: File, onProgress: (p: UploadProgress) => void, signal?: AbortSignal): Promise<{ upload_id: string; sha256: string }> {
  const init = await post<{ upload_id: string; chunk_size: number }>("/api/uploads", { filename: file.name, size: file.size });
  const chunk = Math.max(init.chunk_size, 1024 * 1024);
  let offset = 0;
  const started = performance.now();
  while (offset < file.size) {
    if (signal?.aborted) throw new DOMException("Upload cancelled", "AbortError");
    const end = Math.min(offset + chunk, file.size);
    let attempt = 0;
    for (;;) {
      try {
        const r = await api<{ received: number }>(`/api/uploads/${init.upload_id}?offset=${offset}`, { method: "PUT", body: file.slice(offset, end), headers: { "Content-Type": "application/octet-stream" }, signal });
        offset = r.received;
        break;
      } catch (e) {
        if ((e as Error).name === "AbortError") throw e;
        if (e instanceof ApiError && e.status === 409) {                    // server is ahead/behind: resync
          const st = await get<{ received: number }>(`/api/uploads/${init.upload_id}`);
          offset = st.received;
          break;
        }
        if (e instanceof ApiError && e.status < 500) throw e;
        if (++attempt > 5) throw e;
        await new Promise((r) => setTimeout(r, 800 * 2 ** attempt));       // network/5xx: exponential back-off, then retry same chunk
      }
    }
    const secs = Math.max((performance.now() - started) / 1000, 0.001);
    onProgress({ loaded: offset, total: file.size, speed: offset / secs, phase: "uploading" });
  }
  onProgress({ loaded: file.size, total: file.size, speed: 0, phase: "finalising" });
  const done = await post<{ upload_id: string; sha256: string }>(`/api/uploads/${init.upload_id}/complete`);
  onProgress({ loaded: file.size, total: file.size, speed: 0, phase: "done" });
  return done;
}
