export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Role = "administrator" | "consultant" | "manager" | "read_only";

export interface User { id: string; email: string; full_name: string | null; role: Role; is_active: boolean; last_login?: string | null; created_at?: string }

export interface StageInfo { name: string; label: string; order: number; status: "pending" | "running" | "done" | "failed" | "skipped" | string; progress: number; attempts: number; message?: string | null; warnings?: string[] | null; started_at?: string | null; finished_at?: string | null }
export interface CategoryScore { key: string; label: string; score: number; grade: string; findings: Record<"critical" | "high" | "medium" | "low", number>; weight: number; data_available: boolean }
export interface OverallScore { score: number; grade: string; risk_score: number; risk_level: string; maturity_level: string; maturity_index: number; severity_totals: Record<"critical" | "high" | "medium" | "low", number> }
export interface Scores { categories: Record<string, CategoryScore>; overall: OverallScore; available?: Record<string, boolean> }

export interface Assessment {
  id: string; name: string; customer_name: string | null; consultant_name: string | null; source_filename: string; source_size: number
  status: "queued" | "processing" | "completed" | "partial" | "failed"; progress: number; current_stage: string | null; error: string | null
  qradar_version: string | null; overall_score: number | null; created_at: string; updated_at: string
  summary?: { overall?: OverallScore; categories?: Record<string, CategoryScore> } | null
  stages?: StageInfo[]
}

export interface Environment { version: string | null; fix_pack: string | null; build: string | null; deployment_type: string | null; install_type: string | null; platform: string | null; manufacturer: string | null; software_hardware: string | null; hosts: number; console: string | null; source_files?: number; supported_line?: boolean }

export interface TopoNode {
  id: string; hostname: string; ip: string | null; role: string; status_raw: string | null; version: string | null; components: string[]
  ha_role: string | null; ha_peer: string | null; ha_status: string | null; eps: number | null; fpm: number | null; token: boolean | null
  cpu_cores: number | null; memory_bytes: number | null; disk_bytes: number | null; last_seen: string | null; perf_key?: string | null; os: string | null
  notifications: number; status: "healthy" | "warning" | "critical" | "unknown" | string; health: number
}
export interface Topology {
  nodes: TopoNode[]; edges: { source: string; target: string; kind: string }[]
  ha: { pairs: { primary: string; secondary: string; status: string | null; sync?: string | null; failover_ready?: boolean }[]; protected_hosts: string[]; unprotected: { id: string; hostname: string; role: string }[]; configured: boolean }
  role_counts: Record<string, number>
}
export interface DeploymentCheck { id: string; name: string; status: "PASS" | "WARNING" | "CRITICAL"; detail: string; recommendation: string }

export interface LogSourceSummary {
  total: number; enabled: number; disabled: number; error: number; unknown: number; total_eps: number; average_eps: number
  top_eps: { name: string; type: string; eps: number; protocol: string }[]
  protocols: { name: string; count: number; eps: number }[]; types: { name: string; count: number; eps: number }[]
  problematic: { id: string; name: string; type: string; protocol: string; status: string; eps: number; last_event: string | null; reasons: string[]; severity: Severity }[]
  silent_count: number; unparsed_types: number
}
export interface WcAgent { id: string; name: string; ip: string | null; version: string | null; managed?: boolean; mode: string; status: string; destination?: string | null; last_checkin: string | null; os?: string | null; config_error?: string | null; reason?: string | null; log_sources?: number | null }
export interface WinCollectSummary {
  total: number; managed: number; standalone: number; unmanaged: number; disconnected: number; error: number; outdated: number; connected: number; latest_seen: string | null
  versions: { version: string; count: number }[]; old_versions: WcAgent[]; communication_problems: WcAgent[]; config_issues: WcAgent[]; deployment_problems: WcAgent[]; agents: WcAgent[]
}
export interface AppIssue { code: string; observation: string; severity: Severity }
export interface AppItem {
  id: string; name: string; version: string | null; latest_version: string | null; host: string | null; status: string; cpu_pct: number | null; memory_pct: number | null
  restart_count: number | null; last_error: string | null; issues: AppIssue[]; observation: string; impact: string; recommendation: string[]; priority: string; best_practice: string; health: string; comment?: string
}
export interface AppSummary { items: AppItem[]; total: number; running: number; stopped: number; degraded: number; error: number; unknown: number; by_host: Record<string, number>; with_issues: number; restart_loops: number; outdated: number }

export interface LicMetric {
  name: string; unit: string; licensed: number | null; current: number | null; average: number | null; peak: number | null; consumption_pct: number | null; peak_pct: number | null
  trend: { slope_per_day: number; growth_pct_per_month: number; direction: string } | null; forecast: { months: number; value: number; pct: number | null }[]
  risk: string; series: { ts: string; value: number; peak?: number }[]; days_to_limit: number | null
}
export interface Licensing { eps: LicMetric; fpm: LicMetric; app_framework: { licensed: number | null }; expiry: string | null; expiry_days: number | null; license_type: string | null; utilisation_risk: string; has_data: boolean }
export interface AutoUpdate { current_version: string | null; latest_version: string | null; pending_updates: number; repo_reachable: boolean; last_run: string | null; last_status: string | null; history: { ts: string; type: string; status: string; version: string; message: string }[]; errors: unknown[] }

export interface Overview { environment: Environment; topology: Topology; logsources: LogSourceSummary; wincollect: WinCollectSummary; applications: AppSummary; licensing: Licensing; autoupdate: AutoUpdate; scores: Scores }

export interface Notification {
  id: string; severity: string; severity_raw?: string | null; timestamp: string | null; status: string; message: string; host: string | null; effective_severity: Severity; priority: string; title: string; domain: string; category: string
  kb_code: string | null; matched: boolean; technical_explanation: string; root_cause: string; business_impact: string; impact: string; risk: string; recommendation: string[]; best_practice: string; comment: string; count: number
}
export interface NotificationsResp { items: Notification[]; total: number; open: number; by_severity: Record<string, number>; by_domain: Record<string, number>; unmapped: number }

export interface Finding {
  id: string; code: string; category: string; source: string; severity: Severity; priority: string; title: string; observation: string; description: string; root_cause: string
  impact: string; business_impact: string; risk: string; recommendation: string[]; best_practice: string; hosts: string[]; evidence: Record<string, unknown>; status: string; comment: string
}
export interface TopRecommendation { code: string; title: string; category: string; severity: Severity; priority: string; count: number; recommendation: string[]; best_practice: string; impact: string; business_impact: string; observations: string[] }
export interface ExecSummary { headline: string; paragraphs: string[]; highlights: string[] }
export interface HealthResp { scores: Scores; summary: ExecSummary; top_recommendations: TopRecommendation[] }

export interface DiskStat { tps_avg: number; read_kBps_avg: number; write_kBps_avg: number; avgrq_sz: number | null; avgqu_sz: number | null; await_avg: number | null; await_max: number | null; await_p95: number | null; r_await_avg: number | null; w_await_avg: number | null; util_avg: number | null; util_max: number | null; svctm_avg: number | null; series: { ts: string; await: number; util: number; read_kBps: number; write_kBps: number; queue: number }[] }
export interface IfaceStat { rx_kBps_avg: number; rx_kBps_max: number; tx_kBps_avg: number; tx_kBps_max: number; rx_pps_avg: number; tx_pps_avg: number; rx_err_max: number; tx_err_max: number; rx_drop_max: number; tx_drop_max: number; series: { ts: string; rx_kBps: number; tx_kBps: number; rx_pps: number; tx_pps: number }[] }
export interface PerfHost {
  key: string; identity: { hostname: string; ip: string | null }; hardware: { cpus?: number; model?: string; sockets?: number; memory_bytes?: number; disk_bytes?: number; swap_bytes?: number }
  df: { filesystem: string; mount: string; size_bytes: number; used_bytes: number; avail_bytes: number; use_pct: number }[]
  memory: { total: number; used: number; free: number; available: number; swap_total: number; swap_used: number } | null
  sar_summary: { cpu?: { avg: number; max: number; p95: number; iowait_avg: number; iowait_max: number; saturation_pct: number }; memory?: { avg: number; max: number; p95: number }; swap?: { avg: number; max: number }; load?: { avg1: number; max1: number; avg5: number; max5: number; max_runq: number }; network?: { rx_kBps_avg: number; tx_kBps_avg: number; errors_max: number; drops_max: number; primary_iface: string }; disk?: { worst_device: string; await_avg: number; await_max: number; util_max: number; devices: number } }
  series: { cpu?: { ts: string; user: number; system: number; iowait: number; steal: number; used: number }[]; memory?: { ts: string; used_pct: number }[]; swap?: { ts: string; used_pct: number }[]; load?: { ts: string; l1: number; l5: number; l15: number; runq: number }[]; network?: { ts: string; rx_kBps: number; tx_kBps: number }[]; disk?: unknown[] }
  disks: Record<string, DiskStat>; interfaces: Record<string, IfaceStat>
  top_cpu: { command: string; cpu: number; mem: number; count: number; rss_kb: number }[]; top_mem: { command: string; cpu: number; mem: number; count: number; rss_kb: number }[]
  load: { avg1: number; max1: number }; httpd_count: number | null; samples: Record<string, number>
}
export interface PerfAssessment { key: string; host: string; metric: string; label: string; value: number | null; unit: string; severity: Severity | "ok"; status: string; code: string; finding: string; risk: string; impact: string; root_cause: string; recommendation: string[]; priority: string; threshold: string; best_practice: string }
export interface PerformanceResp { hosts: Record<string, PerfHost>; assessments: PerfAssessment[] }

export interface ChatMsg { id?: number; role: "user" | "assistant"; content: string; meta?: { intent?: string; references?: unknown[] } | null; created_at?: string }
export interface ReportConfig { customer_name: string | null; consultant_name: string | null; title: string; sections: string[]; notes: string; classification: string; next_steps: string[]; comments: Record<string, string> }
export interface ReportConfigResp { config: ReportConfig; has_logo: boolean; available_sections: { key: string; label: string }[] }
export interface ExportRow { id: string; format: "pdf" | "docx" | "pptx"; size: number; created_at: string; created_by: string | null; download: string }
export interface AuditRow { id: number; ts: string; user: string | null; action: string; assessment_id: string | null; target: string | null; detail: unknown; ip: string | null }
export interface CommentRow { target_type: string; target_key: string; text: string; updated_by: string | null; updated_at: string }
