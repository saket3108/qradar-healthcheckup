import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { del, get, patch, post, put } from "./api";
import type { Assessment, AuditRow, ChatMsg, CommentRow, DeploymentCheck, ExportRow, Finding, HealthResp, Licensing, NotificationsResp, Overview, PerformanceResp, ReportConfig, ReportConfigResp, Topology, User, Environment, LogSourceSummary, WinCollectSummary, AppSummary } from "@/types";

export const qk = {
  assessments: (q?: string, status?: string) => ["assessments", q ?? "", status ?? ""] as const,
  assessment: (id: string) => ["assessment", id] as const,
  data: (id: string, what: string, extra = "") => ["data", id, what, extra] as const,
};

const ACTIVE = new Set(["queued", "processing"]);

export const useAssessments = (q?: string, status?: string) =>
  useQuery({
    queryKey: qk.assessments(q, status),
    queryFn: () => get<Assessment[]>(`/api/assessments?${new URLSearchParams({ ...(q ? { q } : {}), ...(status ? { status } : {}) })}`),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => ((query.state.data as Assessment[] | undefined)?.some((a) => ACTIVE.has(a.status)) ? 2500 : false),
  });

/** Polls while the job is running so the UI shows live stage progress. */
export const useAssessment = (id: string) =>
  useQuery({
    queryKey: qk.assessment(id),
    queryFn: () => get<Assessment>(`/api/assessments/${id}`),
    refetchInterval: (query) => { const s = (query.state.data as Assessment | undefined)?.status; return s && ACTIVE.has(s) ? 1500 : false; },
  });

function useData<T>(id: string, path: string, enabled: boolean, extra = "") {
  return useQuery({ queryKey: qk.data(id, path, extra), queryFn: () => get<T>(`/api/assessments/${id}/${path}`), enabled });
}
export const useOverview = (id: string, ok: boolean) => useData<Overview>(id, "overview", ok);
export const useDeployment = (id: string, ok: boolean) => useData<{ topology: Topology; checks: DeploymentCheck[]; environment: Environment }>(id, "deployment", ok);
export const useLogSourceAnalysis = (id: string, ok: boolean) => useData<{ logsources: LogSourceSummary; wincollect: WinCollectSummary }>(id, "logsources-analysis", ok);
export const useLicensing = (id: string, ok: boolean) => useData<{ licensing: Licensing }>(id, "licensing", ok);
export const usePerformance = (id: string, ok: boolean) => useData<PerformanceResp>(id, "performance", ok);
export const useHealth = (id: string, ok: boolean) => useData<HealthResp>(id, "health", ok);
export const useApplications = (id: string, ok: boolean) => useData<AppSummary>(id, "applications", ok);
export const useNotifications = (id: string, ok: boolean, severity = "", q = "") =>
  useQuery({ queryKey: qk.data(id, "notifications", `${severity}|${q}`), enabled: ok, placeholderData: keepPreviousData,
    queryFn: () => get<NotificationsResp>(`/api/assessments/${id}/notifications?${new URLSearchParams({ ...(severity ? { severity } : {}), ...(q ? { q } : {}) })}`) });
export const useFindings = (id: string, ok: boolean) => useData<Finding[]>(id, "findings", ok);
export const useComments = (id: string, type?: string) =>
  useQuery({ queryKey: qk.data(id, "comments", type ?? ""), queryFn: () => get<CommentRow[]>(`/api/assessments/${id}/comments${type ? `?target_type=${type}` : ""}`) });

export function useSaveComment(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { type: string; key: string; text: string }) => put(`/api/assessments/${id}/comments/${v.type}/${encodeURIComponent(v.key).replace(/%2F/g, "/")}`, { text: v.text }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["data", id] }); },
  });
}
export function useUpdateFinding(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { fid: string; status?: string; severity?: string }) => patch(`/api/assessments/${id}/findings/${v.fid}`, { status: v.status, severity: v.severity }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["data", id] }); void qc.invalidateQueries({ queryKey: qk.assessment(id) }); void qc.invalidateQueries({ queryKey: ["assessments"] }); },
  });
}
export function useResume(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stage?: string) => post<Assessment>(`/api/assessments/${id}/resume${stage ? `?from_stage=${stage}` : ""}`),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: qk.assessment(id) }); void qc.invalidateQueries({ queryKey: ["assessments"] }); },
  });
}
export function useDeleteAssessment() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => del(`/api/assessments/${id}`), onSuccess: () => { void qc.invalidateQueries({ queryKey: ["assessments"] }); } });
}
export function useCreateAssessment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { upload_id: string; customer_name?: string; consultant_name?: string }) => post<Assessment>("/api/assessments", v),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["assessments"] }); },
  });
}

export const useReportConfig = (id: string, ok: boolean) => useQuery({ queryKey: qk.data(id, "report-config"), queryFn: () => get<ReportConfigResp>(`/api/assessments/${id}/report-config`), enabled: ok });
export function useSaveReportConfig(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: Partial<ReportConfig>) => put(`/api/assessments/${id}/report-config`, v),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: qk.data(id, "report-config") }); void qc.invalidateQueries({ queryKey: qk.assessment(id) }); },
  });
}
export const useExports = (id: string) => useQuery({ queryKey: qk.data(id, "exports"), queryFn: () => get<ExportRow[]>(`/api/assessments/${id}/exports`) });
export function useCreateExport(id: string) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fmt: string) => post<{ id: string; download: string; size: number }>(`/api/assessments/${id}/exports/${fmt}`), onSuccess: () => { void qc.invalidateQueries({ queryKey: qk.data(id, "exports") }); } });
}

export const useChat = (id: string) => useQuery({ queryKey: qk.data(id, "chat"), queryFn: () => get<ChatMsg[]>(`/api/assessments/${id}/assistant`) });
export function useAsk(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (message: string) => post<{ answer: string; intent: string }>(`/api/assessments/${id}/assistant`, { message }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: qk.data(id, "chat") }); },
  });
}
export function useClearChat(id: string) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => del(`/api/assessments/${id}/assistant`), onSuccess: () => { void qc.invalidateQueries({ queryKey: qk.data(id, "chat") }); } });
}

export const useUsers = () => useQuery({ queryKey: ["users"], queryFn: () => get<User[]>("/api/users") });
export function useUserMutations() {
  const qc = useQueryClient();
  const inv = () => { void qc.invalidateQueries({ queryKey: ["users"] }); };
  return {
    create: useMutation({ mutationFn: (v: { email: string; password: string; role: string; full_name?: string }) => post<User>("/api/users", v), onSuccess: inv }),
    update: useMutation({ mutationFn: (v: { id: string } & Partial<{ role: string; is_active: boolean; full_name: string; password: string }>) => { const { id, ...b } = v; return patch<User>(`/api/users/${id}`, b); }, onSuccess: inv }),
  };
}
export const useAudit = (assessmentId?: string, action?: string) =>
  useQuery({ queryKey: ["audit", assessmentId ?? "", action ?? ""], queryFn: () => get<AuditRow[]>(`/api/audit?${new URLSearchParams({ limit: "300", ...(assessmentId ? { assessment_id: assessmentId } : {}), ...(action ? { action } : {}) })}`) });
export const useKnowledgeBase = () => useQuery({ queryKey: ["kb"], queryFn: () => get<Record<string, unknown>[]>("/api/knowledge-base"), staleTime: Infinity });
