/** Response contracts of the BankOps FastAPI backend (see backend/app/api). */

export type Role = "demo_admin" | "operations_analyst" | "operations_manager" | "auditor" | "read_only";
export type Severity = "critical" | "high" | "medium" | "low";
export type Classification = "public" | "internal" | "confidential" | "restricted";
export type RiskLevel = "read_only" | "low" | "medium" | "high" | "prohibited";
export type Decision = "allow" | "deny" | "require_approval";
export type InvestigationStatus =
  | "queued" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled" | "interrupted";
export type ApprovalStatus = "pending" | "approved" | "rejected" | "cancelled" | "expired" | "invalidated";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface User {
  id: string;
  username: string;
  display_name: string;
  email: string;
  role: Role;
  tenant_id: string;
  tenant_name: string;
  permissions: string[];
  is_demo_account: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  expires_at: string;
  user: User;
}

export interface Health {
  status: string;
  version: string;
  environment: string;
  synthetic_data: boolean;
}

export interface ReadyCheck {
  ok: boolean;
  [key: string]: unknown;
}

export interface Readiness {
  status: "ready" | "degraded" | "not_ready";
  checks: Record<string, ReadyCheck>;
}

// ------------------------------------------------------------------ incidents
export interface IncidentSummary {
  id: string;
  number: string;
  title: string;
  category: string;
  severity: Severity;
  status: string;
  classification: Classification;
  primary_service: string | null;
  affected_services: string[];
  owner_team: string;
  detected_at: string;
  updated_at: string;
  resolved_at: string | null;
  scenario_key: string | null;
  is_synthetic: boolean;
}

export interface TimelineEvent {
  id: string;
  occurred_at: string;
  event_type: string;
  source: string;
  summary: string;
  details: Record<string, unknown> | null;
}

export interface LogLine {
  id: string;
  ts: string;
  level: string;
  service: string;
  message: string;
  neutralized: boolean;
}

export interface DependencyMap {
  nodes: { key: string; name: string; status: string; focus: boolean }[];
  edges: { from: string; to: string; type: string }[];
}

export interface IncidentDetail extends IncidentSummary {
  description: string;
  impact: string;
  customer_impact: string | null;
  attributes: Record<string, unknown> | null;
  resolution_criteria: Record<string, unknown> | null;
  resolution_summary: string | null;
  tags: string[];
  timeline: TimelineEvent[];
  logs: LogLine[];
  dependency_map: DependencyMap;
  related_incidents: IncidentSummary[];
  investigations: RunSummary[];
  can_investigate: boolean;
}

export interface ServiceInfo {
  key: string;
  name: string;
  status: string;
  tier: string;
  owner_team: string;
}

// -------------------------------------------------------------- investigations
export interface RunSummary {
  id: string;
  incident_id: string;
  incident_number: string | null;
  incident_title: string | null;
  status: InvestigationStatus;
  outcome: string | null;
  phase: string | null;
  current_node: string | null;
  requested_by: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
  step_count: number;
  tool_call_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  provider: string | null;
  model: string | null;
  model_mode: string | null;
  prompt_versions: Record<string, string> | null;
  workflow_version: string | null;
  index_version: string | null;
  policy_version: string | null;
  degraded: boolean;
  confidence: number | null;
  risk_level: RiskLevel | null;
  error_code: string | null;
  execution_mode: string;
  is_evaluation: boolean;
  event_seq: number;
}

export interface Triage {
  summary: string;
  severity_assessment: Severity;
  severity_rationale: string;
  affected_systems: string[];
  key_facts: string[];
  missing_information: string[];
  search_queries: string[];
}

export interface Evidence {
  label: string;
  kind: "runbook" | "incident_history" | "metric" | "log" | "tool_result" | string;
  title: string;
  excerpt: string;
  citation?: string;
  version?: string;
  section?: string;
  chunk_ref?: string;
  score?: number;
  classification?: string;
  injection_detected?: boolean;
  source_ref?: string;
  document_id?: string;
}

export interface Hypothesis {
  id: string;
  title: string;
  description: string;
  root_cause_category: string;
  confidence: number;
  confidence_rationale: string;
  supporting_evidence: string[];
  contradicting_evidence: string[];
  further_checks: string[];
  unsupported?: boolean;
}

export interface Diagnosis {
  summary: string;
  hypotheses: Hypothesis[];
  abstained: boolean;
  abstention_reason: string | null;
  conflicting_evidence: boolean;
  unavailable?: boolean;
  invalid_citations_removed?: number;
}

export interface PlannedAction {
  step: number;
  tool_name: string;
  target_resource: string;
  parameters: Record<string, unknown>;
  rationale: string;
  expected_effect: string;
  risks: string;
  prerequisites: string[];
  rollback_option: string;
  depends_on_step: number | null;
  evidence_refs: string[];
}

export interface Plan {
  summary: string;
  actions: PlannedAction[];
  manual_steps: string[];
  not_recommended: { tool_name: string; reason: string }[];
  evidence_refs: string[];
}

export interface PolicyDecision {
  decision: Decision;
  risk_level: RiskLevel;
  rule_ids: string[];
  reasons: string[];
  explanation: string;
  required_approver_roles: string[];
  policy_version: string;
}

export interface PolicyOutcome {
  step: number;
  tool_name: string;
  target_resource: string;
  parameters: Record<string, unknown>;
  decision: PolicyDecision;
  action_id: string | null;
  approval_id: string | null;
  depends_on_step: number | null;
}

export interface PolicyGate {
  decisions: PolicyOutcome[];
  alternatives: { tool_name: string; reason: string; decision: Decision; explanation: string }[];
  counts: Record<Decision, number>;
  policy_version: string;
}

export interface GovernanceReview {
  summary: string;
  policy_constraints: string[];
  data_exposure_concerns: string[];
  approval_recommendations: { step: number; recommendation: string }[];
  prohibited_actions_detected: string[];
  advisory_only: boolean;
}

export interface Verification {
  status: string;
  checks: { name: string; passed: boolean; detail?: string }[];
  passed?: number;
  total?: number;
  summary?: string;
  residual_risks?: string[];
}

export interface FinalReport {
  title: string;
  executive_summary: string;
  findings: string[];
  root_cause: string | null;
  actions_taken: string[];
  evidence_citations: string[];
  limitations: string[];
  next_steps: string[];
  generated_by?: string;
}

export interface InvestigationState {
  triage: Triage | null;
  retrieval: {
    sufficient: boolean;
    reason: string;
    queries: string[];
    excluded_unauthorized: number;
    top_score: number | null;
    runbook_evidence: number;
    retrieval_failed: boolean;
  } | null;
  diagnosis: Diagnosis | null;
  plan: Plan | null;
  governance: GovernanceReview | null;
  policy: PolicyGate | null;
  execution: Record<string, string[]> | null;
  verification: Verification | null;
  report: FinalReport | null;
  outcome: string | null;
  degraded_reasons: string[] | null;
  sources: Record<string, string> | null;
  abort_reason: string | null;
  phase: string | null;
  notes: string | null;
  completed: string[] | null;
  evidence: Evidence[];
}

export interface ApprovalBrief {
  id: string;
  status: ApprovalStatus;
  decided_by: string | null;
  decided_at: string | null;
  reason_code: string | null;
  expires_at: string;
}

export interface Action {
  id: string;
  investigation_id: string | null;
  incident_id: string;
  step_index: number;
  tool_name: string;
  target_resource: string;
  parameters: Record<string, unknown>;
  risk_level: RiskLevel;
  status: string;
  requires_approval: boolean;
  policy_decision: PolicyDecision | null;
  requested_by: string | null;
  idempotency_key: string;
  action_hash: string;
  preconditions: { name: string; passed: boolean; detail: string }[] | null;
  result: Record<string, unknown> | null;
  error_code: string | null;
  verification_status: string | null;
  verification_detail: Record<string, unknown> | null;
  rollback_supported: boolean;
  rollback_status: string | null;
  rollback_note: string | null;
  rationale: string | null;
  expected_effect: string | null;
  depends_on_step: number | null;
  attempt_count: number;
  created_at: string;
  executed_at: string | null;
  verified_at: string | null;
  rolled_back_at: string | null;
  simulated: true;
  approval: ApprovalBrief | null;
  incident_number?: string;
  incident_title?: string;
}

export interface RunDetail extends RunSummary {
  limits?: { max_steps: number; max_tool_calls: number; token_budget: number; step_timeout_seconds: number; total_timeout_seconds: number };
  state: InvestigationState;
  actions: Action[];
}

export interface InvestigationEvent {
  seq: number;
  created_at: string;
  event_type: string;
  agent: string | null;
  tool: string | null;
  status: string;
  message: string;
  payload: Record<string, unknown> | null;
  duration_ms: number | null;
}

export interface EventsPage {
  investigation_id: string;
  status: InvestigationStatus;
  events: InvestigationEvent[];
  last_seq: number;
}

// ------------------------------------------------------------------ approvals
export interface ApprovalDetail {
  id: string;
  action_id: string;
  investigation_id: string | null;
  incident_id: string;
  incident_number: string | null;
  incident_title: string | null;
  requested_by: string | null;
  requested_by_role: string | null;
  required_roles: string[];
  risk_level: RiskLevel;
  status: ApprovalStatus;
  expires_at: string;
  decided_by: string | null;
  decided_at: string | null;
  reason_code: string | null;
  comment: string | null;
  created_at: string;
  action_hash: string;
  target_resource: string;
  action: Action | null;
  evidence: { label: string; kind: string; title: string; citation?: string; excerpt: string }[];
  can_approve: boolean;
  approve_block_reason: string | null;
  can_reject: boolean;
  reject_block_reason: string | null;
  investigation_resumed?: boolean;
}

export interface CatalogTool {
  name: string;
  risk_level: RiskLevel;
  description: string;
  allowed_targets: string[];
  rollback_supported: boolean;
  rollback_note: string;
  approver_roles: string[];
}

export interface ActionCatalog {
  tools: CatalogTool[];
  prohibited: { name: string; reason: string }[];
}

// ------------------------------------------------------------------ dashboard
export interface DashboardSummary {
  synthetic: boolean;
  kpis: {
    open_incidents: number;
    critical_high_open: number;
    awaiting_approval: number;
    pending_approvals: number;
    resolved_incidents: number;
    mttr_minutes_synthetic: number | null;
    investigations_total: number;
    investigations_running: number;
  };
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  trend: { date: string; critical: number; high: number; medium: number; low: number; total: number }[];
  trend_note: string;
  high_risk_incidents: IncidentSummary[];
  ai_quality: {
    source: "measured" | "none";
    note: string;
    evaluation_run_id: string | null;
    evaluated_at: string | null;
    gate_passed: boolean | null;
    metrics: Record<string, number | null>;
    investigations: { completed: number; failed: number; degraded: number; median_duration_seconds: number | null };
  };
  recent_activity: {
    at: string;
    investigation_id: string;
    incident_number: string | null;
    event_type: string;
    status: string;
    message: string;
  }[];
  classification_scope: string[];
}

// ------------------------------------------------------------------ knowledge
export interface KnowledgeDocument {
  id: string;
  doc_key: string;
  title: string;
  version: string;
  source: string;
  source_type: string;
  classification: Classification;
  allowed_roles: string[];
  tags: string[];
  status: string;
  status_detail: string | null;
  chunk_count: number;
  injection_flag_count: number;
  index_version: string | null;
  index_current: boolean;
  content_hash: string;
  byte_size: number;
  is_synthetic: boolean;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  retention_until: string | null;
}

export interface KnowledgeChunk {
  id: string;
  chunk_index: number;
  section: string;
  content: string;
  char_count: number;
  token_estimate: number;
  embedding_model: string;
  index_version: string;
  injection_detected: boolean;
  injection_patterns: string[];
  chunk_ref: string;
}

export interface KnowledgeDocumentDetail extends KnowledgeDocument {
  chunks: KnowledgeChunk[];
}

export interface KnowledgeStats {
  index_version: string;
  vector_backend: string;
  embedding: { provider: string; model: string; dim: number };
  chunking: { chunk_size: number; chunk_overlap: number };
  retrieval: { mode: string; top_k: number; min_score: number; reranker: string; fusion: string };
  documents: number;
  chunks: number;
  stale_documents: number;
  failed_documents: number;
  injection_flagged_documents: number;
  injection_patterns: Record<string, string>;
  retrieval_metrics: {
    source: string;
    queries: number;
    latency_ms_p50: number | null;
    latency_ms_p95: number | null;
    sufficiency_rate: number | null;
    errors: number;
    avg_excluded_unauthorized: number | null;
  };
}

export interface SearchResult {
  chunk_id: string;
  document_id: string;
  doc_key: string;
  title: string;
  version: string;
  section: string;
  chunk_index: number;
  classification: Classification;
  content: string;
  semantic_score: number;
  keyword_score: number;
  fused_score: number;
  rerank_score: number;
  injection_detected: boolean;
  injection_patterns: string[];
  trust: "approved" | "unverified";
  chunk_ref: string;
  citation: string;
}

export interface SearchResponse {
  query: string;
  mode: string;
  sufficient: boolean;
  reason: string;
  top_score: number | null;
  excluded_unauthorized: number;
  candidate_count: number;
  latency_ms: number;
  index_version: string;
  results: SearchResult[];
}

// ----------------------------------------------------------------- governance
export interface AuditEvent {
  id: number;
  event_id: string;
  occurred_at: string;
  actor: string | null;
  actor_role: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  outcome: string;
  request_id: string | null;
  investigation_id: string | null;
  details: Record<string, unknown> | null;
  hash: string;
  prev_hash: string;
}

export interface ChainVerification {
  valid: boolean;
  checked: number;
  first_invalid_event_id: string | number | null;
  head_hash: string | null;
}

export interface Policies {
  policy_version: string;
  rules: { id: string; description: string }[];
  roles: { role: Role; description: string; clearance: Classification; permissions: string[] }[];
  permissions: string[];
  action_catalog: {
    tool: string;
    risk_level: RiskLevel;
    description: string;
    allowed_targets: string[];
    approver_roles: string[];
    rollback_supported: boolean;
    rollback_note: string;
  }[];
  prohibited_actions: { tool: string; reason: string }[];
  configuration: Record<string, boolean | number>;
  injection_patterns: Record<string, string>;
}

export interface ClassificationLevels {
  levels: { classification: Classification; rank: number; roles_with_clearance: string[] }[];
  note: string;
}

export interface PolicyDecisionRow {
  id: string;
  created_at: string;
  investigation_id: string | null;
  action_id: string | null;
  subject_role: string;
  action_name: string;
  resource: string | null;
  risk_level: RiskLevel;
  decision: Decision;
  rule_ids: string[];
  explanation: string;
  policy_version: string;
}

export interface GatewayStatus {
  provider: string;
  model: string;
  mode: string;
  circuit_breaker: string;
  [key: string]: unknown;
}

export interface ModelVersions {
  active_bundle: { hash: string; components: Record<string, unknown> };
  prompts: { prompt_id: string; version: string; description: string; template_hash: string; registered: boolean }[];
  model_configs: {
    id: string;
    provider: string;
    model: string;
    embedding_provider: string;
    embedding_model: string;
    embedding_dim: number;
    config_hash: string;
    created_at: string;
  }[];
  gateway: GatewayStatus;
  workflow: { version: string; agents: Record<string, string> };
  dataset: { dataset_id: string; version: string; description: string };
  thresholds_version: string;
}

export interface TenantUser {
  id: string;
  username: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  is_demo_account: boolean;
  last_login_at: string | null;
}

export interface Promotion {
  id: string;
  bundle_hash: string;
  components: Record<string, unknown>;
  from_env: string | null;
  to_env: string;
  status: "promoted" | "blocked" | "rolled_back";
  evaluation_run_id: string | null;
  gate_passed: boolean;
  gate_failures: string[];
  promoted_by: string;
  previous_promotion_id: string | null;
  rollback_of_id: string | null;
  notes: string | null;
  created_at: string;
  simulated: true;
}

export interface PromotionsView {
  environments: Record<string, Promotion | null>;
  history: Promotion[];
  current_bundle_hash: string;
  note: string;
}

export type RetentionReport = Record<string, unknown>;

// ---------------------------------------------------------------- evaluations
export interface EvaluationRun {
  id: string;
  status: string;
  created_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  dataset_id: string;
  dataset_version: string;
  provider: string;
  model: string;
  model_mode: string;
  prompt_versions: Record<string, string> | null;
  retrieval_config: Record<string, unknown> | null;
  index_version: string | null;
  workflow_version: string | null;
  policy_version: string | null;
  bundle_hash: string | null;
  metrics: Record<string, unknown>;
  thresholds: Record<string, unknown> | null;
  gate_passed: boolean | null;
  gate_failures: string[] | null;
  is_model_assisted: boolean;
  judge_metrics: Record<string, unknown> | null;
  error_code: string | null;
  measurement_note: string;
}

export interface EvaluationDetail extends EvaluationRun {
  cases: { case_id: string; case_type: string; passed: boolean; metrics: Record<string, unknown>; details: Record<string, unknown> }[];
}

// -------------------------------------------------------------- observability
export interface Stats {
  count: number;
  p50: number | null;
  p95: number | null;
  max: number | null;
}

export interface ObservabilitySummary {
  http: {
    scope: string;
    uptime_seconds: number;
    requests_total: number;
    window_size: number;
    errors_5xx: number;
    errors_4xx: number;
    error_rate_5xx: number;
    latency_ms: { p50: number | null; p95: number | null; p99: number | null };
    routes: { route: string; p95_ms: number | null; count: number }[];
  };
  workflow: {
    runs: number;
    by_status: Record<string, number>;
    degraded_runs: number;
    duration_seconds: Stats;
    failure_rate: number | null;
  };
  agents: Record<string, Stats>;
  tools: Record<string, Stats & { errors: number }>;
  tool_errors: Record<string, number>;
  llm: {
    calls: number;
    errors: number;
    skipped: number;
    latency_ms: Stats;
    input_tokens: number;
    output_tokens: number;
    tokens_estimated: boolean;
    estimated_cost_usd: number;
    cost_note: string;
    error_codes: Record<string, number>;
    mock_calls: number;
  };
  retrieval: { queries: number; latency_ms: Stats; sufficiency_rate: number | null; errors: number; avg_results: number | null };
  policy: { decisions: number; denials: number; approvals_required: number };
  approvals: { pending: number; wait_seconds: Stats };
  recent_errors: {
    investigation_id: string;
    seq: number;
    at: string;
    type: string;
    agent: string | null;
    tool: string | null;
    status: string;
    message: string;
  }[];
  faults: Record<string, boolean>;
  gateway: GatewayStatus;
}

export interface TraceSpan {
  name: string | null;
  kind: string;
  start_ms: number;
  duration_ms: number | null;
  status: string;
  message?: string;
  children?: TraceSpan[];
}

export interface Trace {
  investigation_id: string;
  correlation_id: string | null;
  status: string;
  workflow_version: string | null;
  model_mode: string | null;
  spans: TraceSpan[];
  totals: { steps: number; tool_calls: number; input_tokens: number; output_tokens: number; estimated_cost_usd: number };
}

// ----------------------------------------------------------------------- demo
export interface Scenario {
  key: string;
  title: string;
  incident_number: string;
  summary: string;
  personas: { investigator: string; approver: string };
  steps: string[];
  expected_outcome: string;
  incident_id: string | null;
  incident_status: string | null;
  available: boolean;
}

export interface DemoAccount {
  username: string;
  role: Role;
  tenant_id: string;
  display_name: string;
}

export interface FaultsView {
  faults: Record<string, boolean>;
  descriptions: Record<string, string>;
}

export interface SafeSettings {
  version: string;
  environment: string;
  demo_mode: boolean;
  synthetic_data: boolean;
  model: GatewayStatus & {
    mock_mode: boolean;
    configured_provider: string;
    configured_model: string;
    approved_models: string[];
    base_url_configured: boolean;
    api_key: string;
    timeout_seconds: number;
    max_retries: number;
    judge_enabled: boolean;
  };
  embedding: { provider: string; model: string; dim: number; api_key: string };
  storage: { database: string; vector_backend: string; index_version: string };
  security: Record<string, string | number | string[]>;
  workflow: Record<string, string | number>;
  policy: Record<string, boolean | number>;
  can_reset_demo: boolean;
  can_toggle_faults: boolean;
}
