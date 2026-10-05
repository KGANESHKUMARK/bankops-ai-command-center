import { API_BASE, api } from "./client";
import type {
  Action,
  ActionCatalog,
  ApprovalDetail,
  AuditEvent,
  ChainVerification,
  ClassificationLevels,
  DashboardSummary,
  DemoAccount,
  EvaluationDetail,
  EvaluationRun,
  EventsPage,
  FaultsView,
  Health,
  IncidentDetail,
  IncidentSummary,
  KnowledgeDocument,
  KnowledgeDocumentDetail,
  KnowledgeStats,
  ModelVersions,
  ObservabilitySummary,
  Page,
  Policies,
  PolicyDecisionRow,
  Promotion,
  PromotionsView,
  Readiness,
  RetentionReport,
  RunDetail,
  RunSummary,
  SafeSettings,
  Scenario,
  SearchResponse,
  ServiceInfo,
  TenantUser,
  TokenResponse,
  Trace,
  User,
} from "./types";

type Query = Record<string, string | number | boolean | null | undefined>;

export const endpoints = {
  // health & auth
  health: () => api<Health>("/health"),
  // /ready answers 503 *with* a JSON body when not ready; return that body instead of throwing.
  ready: async (): Promise<Readiness> => {
    const res = await fetch(`${API_BASE}/ready`, { headers: { Accept: "application/json" } });
    const body = (await res.json().catch(() => null)) as Readiness | null;
    return body ?? { status: "not_ready", checks: {} };
  },
  login: (username: string, password: string) =>
    api<TokenResponse>("/auth/login", { body: { username, password } }),
  logout: () => api<{ message: string }>("/auth/logout", { method: "POST" }),
  me: () => api<User>("/auth/me"),

  // dashboard & incidents
  dashboard: () => api<DashboardSummary>("/dashboard/summary"),
  services: () => api<ServiceInfo[]>("/services"),
  incidents: (query: Query) => api<Page<IncidentSummary> & { synthetic: boolean }>("/incidents", { query }),
  incident: (id: string) => api<IncidentDetail>(`/incidents/${encodeURIComponent(id)}`),
  startInvestigation: (incidentId: string, notes: string | null) =>
    api<RunDetail>(`/incidents/${encodeURIComponent(incidentId)}/investigations`, { body: { notes: notes || null } }),

  // investigations
  investigations: (query: Query) => api<Page<RunSummary>>("/investigations", { query }),
  investigation: (id: string) => api<RunDetail>(`/investigations/${encodeURIComponent(id)}`),
  investigationEvents: (id: string, after = 0) =>
    api<EventsPage>(`/investigations/${encodeURIComponent(id)}/events`, { query: { after } }),
  resumeInvestigation: (id: string) => api<RunDetail>(`/investigations/${encodeURIComponent(id)}/resume`, { method: "POST" }),
  cancelInvestigation: (id: string, reason: string) =>
    api<RunDetail>(`/investigations/${encodeURIComponent(id)}/cancel`, { body: { reason } }),

  // approvals
  approvals: (query: Query) => api<Page<ApprovalDetail>>("/approvals", { query }),
  approval: (id: string) => api<ApprovalDetail>(`/approvals/${encodeURIComponent(id)}`),
  approve: (id: string, reasonCode: string, comment: string | null) =>
    api<ApprovalDetail>(`/approvals/${encodeURIComponent(id)}/approve`, {
      body: { confirm: true, reason_code: reasonCode, comment: comment || null },
    }),
  reject: (id: string, reasonCode: string, comment: string | null) =>
    api<ApprovalDetail>(`/approvals/${encodeURIComponent(id)}/reject`, { body: { reason_code: reasonCode, comment: comment || null } }),
  cancelApproval: (id: string, reasonCode: string, comment: string | null) =>
    api<ApprovalDetail>(`/approvals/${encodeURIComponent(id)}/cancel`, { body: { reason_code: reasonCode, comment: comment || null } }),

  // actions
  actions: (query: Query) => api<Page<Action>>("/actions", { query }),
  action: (id: string) => api<Action>(`/actions/${encodeURIComponent(id)}`),
  actionCatalog: () => api<ActionCatalog>("/actions/catalog"),
  verifyAction: (id: string) =>
    api<{ verification: Record<string, unknown>; action: Action }>(`/actions/${encodeURIComponent(id)}/verify`, { method: "POST" }),
  rollbackAction: (id: string, reason: string) =>
    api<Action>(`/actions/${encodeURIComponent(id)}/rollback`, { body: { confirm: true, reason } }),

  // knowledge
  documents: (query: Query) => api<Page<KnowledgeDocument> & { synthetic: boolean }>("/knowledge/documents", { query }),
  document: (id: string) => api<KnowledgeDocumentDetail>(`/knowledge/documents/${encodeURIComponent(id)}`),
  knowledgeStats: () => api<KnowledgeStats>("/knowledge/stats"),
  ingest: (form: FormData) => api<KnowledgeDocument>("/knowledge/ingest", { form }),
  search: (body: { query: string; top_k: number; mode: string; classifications: string[]; tags: string[] }) =>
    api<SearchResponse>("/knowledge/search", { body }),
  reindex: (id: string) => api<KnowledgeDocument>(`/knowledge/documents/${encodeURIComponent(id)}/reindex`, { method: "POST" }),
  reindexStale: () => api<{ reindexed: number; index_version: string }>("/knowledge/reindex-stale", { method: "POST" }),
  deleteDocument: (id: string) => api<KnowledgeDocument>(`/knowledge/documents/${encodeURIComponent(id)}`, { method: "DELETE" }),

  // governance
  audit: (query: Query) => api<Page<AuditEvent>>("/governance/audit", { query }),
  auditVerify: () => api<ChainVerification>("/governance/audit/verify"),
  policies: () => api<Policies>("/governance/policies"),
  classifications: () => api<ClassificationLevels>("/governance/classifications"),
  policyDecisions: (query: Query) => api<Page<PolicyDecisionRow>>("/governance/policy-decisions", { query }),
  modelVersions: () => api<ModelVersions>("/governance/model-versions"),
  users: () => api<TenantUser[]>("/governance/users"),
  promotions: () => api<PromotionsView>("/governance/promotions"),
  promote: (toEnv: string, evaluationRunId: string, notes: string | null) =>
    api<Promotion>("/governance/promotions", { body: { to_env: toEnv, evaluation_run_id: evaluationRunId, notes } }),
  rollbackPromotion: (id: string, reason: string) =>
    api<Promotion>(`/governance/promotions/${encodeURIComponent(id)}/rollback`, { body: { reason } }),
  retention: () => api<RetentionReport>("/governance/retention"),
  applyRetention: (dryRun: boolean) => api<RetentionReport>("/governance/retention/apply", { body: { dry_run: dryRun } }),

  // evaluations
  evaluations: (query: Query) => api<Page<EvaluationRun>>("/evaluations", { query }),
  evaluation: (id: string) => api<EvaluationDetail>(`/evaluations/${encodeURIComponent(id)}`),
  runEvaluation: (includeWorkflow: boolean) =>
    api<EvaluationRun>("/evaluations/run", { body: { include_workflow: includeWorkflow } }),

  // observability
  observability: () => api<ObservabilitySummary>("/observability/summary"),
  trace: (id: string) => api<Trace>(`/observability/traces/${encodeURIComponent(id)}`),

  // demo & settings
  scenarios: () => api<Scenario[]>("/demo/scenarios"),
  demoAccounts: () => api<DemoAccount[]>("/demo/accounts"),
  resetDemo: () => api<{ message: string; summary: Record<string, unknown> }>("/demo/reset", { method: "POST" }),
  faults: () => api<FaultsView>("/demo/faults"),
  setFault: (name: string, enabled: boolean) =>
    api<FaultsView>(`/demo/faults/${encodeURIComponent(name)}`, { method: "PUT", body: { enabled } }),
  settings: () => api<SafeSettings>("/settings"),
};
