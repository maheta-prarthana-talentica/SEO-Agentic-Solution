export type Severity = "critical" | "high" | "medium" | "low";
export type FixType = "auto-fixable" | "assisted" | "manual";
export type Category =
  | "technical"
  | "on-page"
  | "content"
  | "structured-data"
  | "performance";

export interface Finding {
  id: string;
  category: Category;
  severity: Severity;
  title: string;
  description: string;
  evidence: string;
  recommendation: string;
  fix_type: FixType;
  affected_pages: string[];
  impact_score: number;
  effort_score: number;
  mapped_file?: string | null;
  status: string;
  is_assumed: boolean;
}

export interface CategoryScore {
  category: Category;
  score: number;
  findings_count: number;
}

export interface AuditRun {
  run_id: string;
  target_url: string;
  overall_score: number;
  findings: Finding[];
  category_scores: CategoryScore[];
  pages_crawled: string[];
  completed_at?: string | null;
  errors: string[];
  pr_url?: string | null;
  branch_name?: string | null;
  phase2_status?: string;
  phase2_message?: string | null;
}

export interface AuditListItem {
  run_id: string;
  target_url: string;
  overall_score: number;
  findings_count: number;
  completed_at?: string | null;
}

export interface FindingBrief {
  id: string;
  title: string;
  severity: string;
  category: string;
  fix_type: string;
  recommendation: string;
  priority_score: number;
}

export interface StructuredReport {
  overall_score: number;
  key_strengths: string[];
  key_weaknesses: string[];
  quick_wins: FindingBrief[];
  high_impact_high_effort: FindingBrief[];
  low_impact: FindingBrief[];
  top_recommendations: FindingBrief[];
  phase2_auto_fixable: FindingBrief[];
  phase2_assisted: FindingBrief[];
  phase2_manual: FindingBrief[];
  phase2_cta: string;
}

export interface AuditResponse {
  run_id: string;
  overall_score: number;
  findings_count: number;
  report_markdown: string;
  structured_report: StructuredReport;
  run: AuditRun;
  pr_url?: string | null;
  branch_name?: string | null;
  phase2_status?: string;
  phase2_message?: string | null;
}

export interface TraceEntry {
  timestamp: string;
  agent: string;
  action: string;
  finding_id?: string | null;
  detail: Record<string, unknown>;
  level: string;
}

const BASE = "";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      detail = await res.text();
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  listAudits: () => json<AuditListItem[]>("/api/audits"),
  getAudit: (runId: string) => json<AuditResponse>(`/api/audit/${runId}`),
  runAudit: (body: {
    url: string;
    use_fixture?: boolean;
    enable_phase2?: boolean;
    enable_remediation?: boolean;
    page_limit?: number;
    repo_url?: string;
    github_repo_url?: string;
    github_token?: string;
  }) =>
    json<AuditResponse>("/api/audit", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  runPhase2: (
    runId: string,
    body: { github_repo_url: string; github_token: string; page_limit?: number }
  ) =>
    json<AuditResponse>(`/api/audit/${runId}/phase2`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getTrace: (runId: string) =>
    json<{ run_id: string; entries: TraceEntry[] }>(`/api/traces/${runId}`),
  getReport: (runId: string) =>
    json<{ run_id: string; markdown: string }>(`/api/reports/${runId}`),
};
