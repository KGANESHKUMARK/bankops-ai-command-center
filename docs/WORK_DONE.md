# Complete Work Done — BankOps AI Command Center

> **SYNTHETIC DEMO — NOT A REAL BANKING SYSTEM.**
> All banks, customers, accounts, amounts, services, metrics and logs are fictional.

## Project statistics

| Metric | Value |
|---|---|
| Total project files | 187 |
| Backend application code | ~11,300 lines of Python |
| Backend test code | ~1,600 lines of Python |
| Frontend source code | ~5,800 lines of TypeScript/TSX |
| Backend tests | 158 passing |
| Frontend unit tests | 43 passing |
| Frontend E2E tests | 3 passing |
| API endpoints | 54 REST paths + SSE |
| Database models | 18 SQLAlchemy models |
| Alembic migrations | 1 (initial schema) |
| Synthetic seed data | 2 tenants, 9 users, 59 incidents, 16 documents, 88 chunks |
| Evaluation metrics | 14 (9 required, 5 warning) |
| Documentation files | 10 |
| Workflow agents | 7 + deterministic policy gate |
| RBAC roles | 5 |
| RBAC permissions | 27 |

---

## Phase 1: Repository scaffolding and backend foundation

### 1.1 Monorepo setup

- Created git repository with `.gitignore` (Python, Node, IDE, env files, data files)
- Created `.env.example` with all documented environment variables
- Created local `.env` (git-ignored) copied from `.env.example`
- Created backend `requirements.txt` and `requirements-dev.txt` with pinned versions
- Created `scripts/check_dependency_age.py` — supply-chain checker that verifies all installed Python packages are ≥7 days old
- Created `scripts/check_npm_dependency_age.mjs` — equivalent checker for npm packages

### 1.2 Backend core (`backend/app/core/`)

- **`config.py`** — Pydantic settings with environment variable loading, CSV list parsing (NoDecode), relative SQLite path resolution against repo root, CORS origins, JWT settings, demo mode flag
- **`logging.py`** — Structured JSON logging with request context, log levels, correlation IDs
- **`context.py`** — Request-scoped context (tenant, user, request ID) propagated through async tasks
- **`middleware.py`** — CORS, security headers (nosniff, DENY, no-referrer, CSP, COOP, Permissions-Policy), request ID generation, body size limits, no-store cache headers
- **`security.py`** — Argon2 password hashing, JWT creation/validation (HS256), token revocation list, demo account enforcement
- **`errors.py`** — Typed error envelope (`{error: {code, message, request_id}}`) for consistent API error responses

### 1.3 Database layer (`backend/app/db/`)

- **`base.py`** — SQLAlchemy declarative base with common mixins (id, tenant_id, created_at, updated_at)
- **`session.py`** — Engine creation, session factory, SQLite/PostgreSQL dialect detection, directory creation for SQLite files
- **`types.py`** — Portable vector type (pgvector on PostgreSQL, BLOB on SQLite), JSON type, classification enum

### 1.4 Domain model (`backend/app/domain.py`)

- Enums for: IncidentSeverity, IncidentStatus, IncidentCategory, RiskLevel, ActionStatus, ApprovalStatus, DecisionType, InvestigationStatus, InvestigationOutcome, Classification, ModelMode, ServiceTier, ServiceStatus

### 1.5 SQLAlchemy models (`backend/app/models/`)

18 models across 6 files:

- **`identity.py`** — Tenant, User, UserSession
- **`incidents.py`** — Incident, IncidentLog, Service, ServiceDependency
- **`investigations.py`** — Investigation, InvestigationEvent, Diagnosis, Evidence
- **`actions.py`** — Action, Approval, VerificationResult
- **`knowledge.py`** — KnowledgeDocument, KnowledgeChunk
- **`governance.py`** — AuditEvent, PolicyDecision, ModelVersion, PromptVersion, RetentionPolicy
- **`evaluation.py`** — EvaluationRun, EvaluationCaseResult, Promotion

### 1.6 Alembic migration (`backend/alembic/`)

- **`env.py`** — Dialect-aware migration environment, creates parent directories for SQLite, supports both online and offline modes
- **`0001_initial_schema.py`** — Full initial schema with:
  - All 18 tables with proper indexes (tenant_id, status, created_at, etc.)
  - pgvector extension creation (PostgreSQL only, conditional)
  - HNSW vector index on knowledge_chunks.embedding (PostgreSQL only)
  - Append-only triggers on audit_events (both SQLite and PostgreSQL) — BEFORE UPDATE and BEFORE DELETE raise errors
  - Unique constraints on natural keys (tenant slug, username, incident number, etc.)

---

## Phase 2: Security, RBAC, and policy engine

### 2.1 RBAC permissions (`backend/app/policy/permissions.py`)

- 5 roles: `demo_admin`, `operations_manager`, `operations_analyst`, `auditor`, `read_only`
- 27 permissions across dashboard, incidents, investigations, diagnostics, actions, approvals, knowledge, governance, audit, users, evaluations, promotions, retention, observability, settings, demo
- Role-to-permission mapping (the authorization truth table)

### 2.2 Action risk catalog (`backend/app/policy/catalog.py`)

- 7 allowlisted tools: `restart_service`, `reprocess_batch`, `scale_service`, `clear_cache`, `toggle_feature_flag`, `send_notification`, `quarantine_transaction`
- 5 prohibited tools: `delete_customer_record`, `modify_transaction_amount`, `execute_sql`, `access_external_banking_api`, `transfer_funds`
- Risk classification per tool (low/medium/high)
- Rollback support flag per tool
- Allowed target patterns per tool

### 2.3 Deterministic policy engine (`backend/app/policy/engine.py`)

- `evaluate(user, action, context)` → `PolicyDecision(allow | deny | require_approval)`
- Checks: tool allowlist, prohibited actions, risk level vs. user role, separation of duties (requester ≠ approver for high-risk), target validation, parameter validation
- **Never** parses LLM output for authorization decisions
- Produces human-readable explanations for UI display
- Keeps working when the model provider is unavailable

### 2.4 Audit service (`backend/app/services/audit.py`)

- Append-only event recording
- Hash chain: `hash = SHA-256(prev_hash + canonical(event))`
- Chain verification endpoint
- Database triggers enforce append-only at the DB level (defense in depth)

### 2.5 Policy decision recording (`backend/app/services/policy_records.py`)

- Records every policy decision with the full context (user, action, parameters, decision, explanation)
- Queryable for governance and audit views

---

## Phase 3: RAG pipeline with injection defense

### 3.1 Document loaders (`backend/app/rag/loaders.py`, `pdf.py`, `text.py`)

- Markdown loader: preserves heading structure for section-aware chunking
- Text loader: plain text with encoding detection
- PDF loader: text extraction with page boundaries
- All loaders return structured content with metadata

### 3.2 Chunking (`backend/app/rag/chunking.py`)

- Structure-aware: splits on Markdown headings, paragraphs, sentence boundaries
- Configurable chunk size (default 1200 chars) and overlap (default 200 chars)
- Each chunk records: section path, char count, estimated token count, content hash (SHA-256)
- Deduplication via content hash

### 3.3 Embeddings (`backend/app/rag/embeddings.py`)

- **Mock provider:** Deterministic hash-based embeddings (no API key needed, 1536d)
- **OpenAI-compatible provider:** Uses `text-embedding-3-small` (1536d) via configurable base URL
- Provider selection via environment variable
- Batch embedding support

### 3.3 Vector store (`backend/app/rag/store.py`)

- pgvector on PostgreSQL (with HNSW index)
- BLOB storage on SQLite (with in-memory cosine similarity)
- Portable interface — same code works on both backends
- CRUD operations for documents and chunks

### 3.4 BM25 keyword search (`backend/app/rag/keyword.py`)

- Term-frequency/inverse-document-frequency scoring
- Tokenization with stopword removal
- Configurable top-K

### 3.5 Hybrid retrieval (`backend/app/rag/retrieval.py`)

- Vector search (cosine similarity)
- BM25 keyword search
- Reciprocal Rank Fusion (RRF) to combine rankings
- Lexical reranking (boosts exact query-term matches)
- Source-trust weighting (documents tagged `unverified` are down-ranked and labeled)
- Authorization filters applied **before** ranking (tenant, classification, role)
- Sufficiency check (abstains if insufficient evidence)
- Citations on every result (document ID, section path, chunk hash)

### 3.6 Injection defense (`backend/app/rag/injection.py`)

- Pattern catalog: instruction_override, role_hijack, action_request, data_exfiltration, credential_request, policy_bypass, encoding_attack
- Neutralization at ingestion (documents scanned when chunked and indexed)
- Neutralization at retrieval (chunks scanned again before passing to agent)
- Flagged chunks are counted and visible in the index stats
- Refined signal matching to avoid false positives (e.g., "no parse errors" doesn't match "parse errors")

### 3.7 Ingestion service (`backend/app/rag/ingestion.py`)

- Secure upload endpoint (size-limited, content-sniffed: md, txt, pdf only)
- Re-indexing preserves injection flags
- Soft-delete support
- Index statistics (document count, chunk count, injection flag count, embedding dimensions)

---

## Phase 4: Model gateway and AI layer

### 4.1 Model gateway (`backend/app/ai/gateway.py`)

- **Mock provider:** Deterministic, generates realistic investigation output (triage, evidence, diagnostics, remediation plans, reports) — runs without API keys
- **OpenAI-compatible provider:** Supports any OpenAI-compatible API (configurable base URL, model, API key)
- Retries with exponential backoff and jitter
- Circuit breaker (opens after N consecutive failures, half-open recovery)
- Token counting and cost estimation
- Provider health status

### 4.2 Prompt registry (`backend/app/ai/prompts.py`)

- Versioned prompts (each prompt has a version string)
- System prompts that instruct the model to treat all content as data, not instructions
- Per-agent prompt templates (triage, evidence, diagnostic, remediation, governance, verification, report)
- Prompt versions stored in the database and visible in the governance UI

### 4.3 Typed output schemas (`backend/app/ai/schemas.py`)

- Pydantic models for every agent output: TriageOutput, EvidenceOutput, DiagnosticOutput, RemediationPlan, GovernanceReview, VerificationResult, FinalReport
- All schemas validate structure, reject unexpected fields
- Hypotheses with confidence scores and citations
- Action proposals with tool name, parameters, target, risk level

### 4.4 Mock knowledge (`backend/app/ai/providers/mock_knowledge.py`)

- Pre-built mock responses that reference the seeded runbooks
- Deterministic citation generation (references real chunk hashes)
- Realistic hypothesis ranking with confidence scores

---

## Phase 5: Tool registry and action services

### 5.1 Tool registry (`backend/app/agents/tools.py`, `tool_schemas.py`)

- 7 allowlisted tools with typed Pydantic parameter schemas
- Each tool has: name, description, parameter schema, risk level, allowed targets, rollback support flag
- Unknown tools are rejected
- Invalid parameters are rejected (Pydantic validation)
- Unauthorized targets are rejected

### 5.2 Synthetic simulation (`backend/app/agents/simulation.py`)

- Simulated execution of each tool against seeded demo state
- Simulated metrics (service health, error rates, latency)
- Simulated logs (structured, timestamped)
- Simulated dependency graph
- State snapshots for rollback
- Verification checks (simulated post-action health checks)

### 5.3 Action service (`backend/app/services/actions.py`)

- Idempotent execution via compare-and-swap (CAS) on action status
- Precondition checking before execution
- State snapshot capture before execution (for rollback)
- Post-action verification
- Rollback support (restores snapshot)
- Action hash computation (SHA-256 of tool + parameters + target)
- Policy re-check immediately before execution (scope, expiry, hash)

### 5.4 Approval service (`backend/app/services/approvals.py`)

- Create approval requests (bound to action hash)
- Approve/reject with reason codes and comments
- Separation of duties enforcement (requester ≠ approver for high-risk)
- Approval expiry (configurable TTL, default 30 minutes)
- Approval invalidation (when plan changes, hash mismatch)
- Auto-resume investigation on final approval decision

---

## Phase 6: LangGraph bounded workflow

### 6.1 Workflow definition (`backend/app/agents/workflow.py`)

- LangGraph state machine with 7 agent nodes + deterministic policy gate
- **Agents:** Orchestrator, Triage, Evidence Retrieval, Diagnostic, Remediation Planner, Governance/Risk Reviewer, Verification, Final Report Composer
- **Policy gate:** Not an LLM — deterministic code that decides allow/deny/approval-required
- Bounded by: max steps, max tool calls per step, token budget, per-step timeout, total timeout
- Resumable: state persisted to database, can resume after approval
- Degraded mode: when circuit breaker is open, deterministic fallbacks kick in
- Context propagation: request context (tenant, user, request ID) propagated through async tasks

### 6.2 Background runner (`backend/app/agents/runner.py`)

- CAS-locked execution (prevents concurrent runs of the same investigation)
- Context-propagating async execution
- Stale-run recovery on startup (resumes interrupted investigations)
- Graceful shutdown

### 6.3 Investigation lifecycle (`backend/app/services/investigations.py`)

- Start investigation (creates run, launches background task)
- Resume investigation (after approval, re-loads persisted state)
- Cancel investigation (with reason, invalidates pending approvals)
- Recovery (on startup, resumes interrupted runs)

---

## Phase 7: FastAPI application

### 7.1 Application factory (`backend/app/main.py`)

- Lifespan with startup safety checks (database connectivity, migration head)
- Stale-run recovery on startup
- Graceful shutdown
- Route registration
- Middleware ordering

### 7.2 API schemas (`backend/app/schemas.py`)

- Strict request models with `extra="forbid"` (prevents mass assignment)
- Typed response models for OpenAPI documentation
- Pagination wrappers
- Enum validation

### 7.3 Route modules (`backend/app/api/routes/`)

54 REST endpoints across 12 route files:

- **`health.py`** — `GET /health`, `GET /ready`
- **`auth.py`** — `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- **`dashboard.py`** — `GET /dashboard/summary`
- **`incidents.py`** — `GET /incidents`, `GET /incidents/{id}`
- **`investigations.py`** — `POST /incidents/{id}/investigations`, `GET /investigations`, `GET /investigations/{id}`, `POST /investigations/{id}/resume`, `POST /investigations/{id}/cancel`, `GET /investigations/{id}/events` (SSE)
- **`approvals.py`** — `GET /approvals`, `GET /approvals/{id}`, `POST /approvals/{id}/approve`, `POST /approvals/{id}/reject`, `POST /approvals/{id}/cancel`
- **`actions.py`** — `GET /actions`, `GET /actions/{id}`, `POST /actions/{id}/verify`, `POST /actions/{id}/rollback`
- **`knowledge.py`** — `GET /knowledge/documents`, `GET /knowledge/documents/{id}`, `POST /knowledge/upload`, `POST /knowledge/search`, `POST /knowledge/reindex`, `DELETE /knowledge/documents/{id}`, `GET /knowledge/stats`
- **`governance.py`** — `GET /governance/rbac`, `GET /governance/policies`, `GET /governance/classifications`, `GET /governance/audit`, `GET /governance/audit/verify`, `GET /governance/models`, `GET /governance/prompts`, `GET /governance/retention`
- **`evaluations.py`** — `GET /evaluations`, `POST /evaluations/run`, `GET /evaluations/{id}`, `GET /evaluations/thresholds`, `POST /evaluations/promote`, `POST /evaluations/rollback`
- **`observability.py`** — `GET /observability/summary`, `GET /observability/traces/{id}`
- **`demo.py`** — `GET /demo/accounts`, `GET /demo/scenarios`, `POST /demo/reset`, `POST /demo/faults`
- **`settings.py`** — `GET /settings` (returns whether secrets are configured, never the values)

### 7.4 Serializers (`backend/app/api/serializers.py`)

- Compute UI-facing fields (can_decide, can_cancel, approve_block_reason, reject_block_reason)
- Human-readable block reasons via the policy engine
- No side effects (pure functions)

### 7.5 SSE streaming (`backend/app/api/routes/investigations.py`)

- `GET /investigations/{id}/events` with `Accept: text/event-stream`
- `Last-Event-ID` header support for reconnection
- Event replay from database
- Live updates as workflow progresses
- End event with final state

### 7.6 Observability (`backend/app/services/metrics.py`)

- HTTP metrics: request count, latency p50/p95/p99, 4xx/5xx counts, error rate
- Workflow metrics: runs by status, duration p50/p95, failure rate, degraded runs
- Agent metrics: per-agent step count, latency p50/p95/max
- Tool metrics: per-tool call count, latency p50/p95/max, error count
- LLM metrics: call count, mock vs live, latency, tokens in/out, estimated cost, error codes
- Retrieval metrics: query count, latency, sufficiency rate, avg results, errors
- Policy metrics: decision count, denials, approvals required
- Approval metrics: pending count, wait time p50/p95
- Fault flags: active failure-injection flags
- Trace waterfall: nested span tree for a specific investigation

---

## Phase 8: Synthetic seed data

### 8.1 Seed data (`backend/app/seed/data.py`)

- **2 tenants:** Contoso Bank (fictional US bank), Fabrikam Financial (fictional EU bank, used for tenant isolation testing)
- **9 users:** demo.admin, ops.analyst, ops.analyst2, ops.manager, ops.manager2, risk.auditor, readonly.viewer (Contoso), fab.analyst, fab.manager (Fabrikam)
- **8 services:** statement-renderer, payment-gateway, fraud-detection-engine, notification-service, data-warehouse, kafka-cluster, ibm-mq-broker, reporting-service — each with synthetic metrics, tier, status
- **Service dependencies:** directed graph (e.g., statement-renderer depends on payment-gateway, notification-service)
- **59 incidents:** across 6 categories (payment_processing, statement_generation, data_pipeline, fraud_detection, notification_delivery, reporting) with varying severity (critical, high, medium, low), status (open, investigating, resolved), risk levels, synthetic logs, timelines, attributes
- **Guided scenarios:** statement_outage, payment_failure, fraud_spike — each with step-by-step instructions and persona assignments

### 8.2 Knowledge base (`backend/app/seed/knowledge/`)

16 fictional runbooks and policy documents in Markdown:
- RB-STMT-001: Statement generation pipeline
- RB-KAFKA-003: Kafka consumer lag
- RB-MQ-004: IBM MQ backlog
- RB-FLINK-005: Flink schema compatibility
- RB-SNOW-006: Snowflake ingestion delay
- RB-DUP-007: Duplicate event handling
- RB-PAY-008: Payment delay dependency outage
- RB-DQ-009: Reporting data quality
- RB-TPL-010: Document template management
- POL-ESC-011: Incident escalation policy
- RB-FRAUD-012: Fraud operations escalation
- KB-COMM-013: Community troubleshooting notes (tagged `unverified` for source-trust testing)
- RB-DOCR-002: Document rendering operations
- FAB-RB-001: Card settlement file (Fabrikam tenant, for tenant isolation testing)
- GLOSSARY-015: Operations glossary
- RB-INJECT-001: Injection test document (contains prompt-injection patterns for testing)

### 8.3 Idempotent seeder (`backend/app/seed/seed.py`)

- Deterministic UUIDs (UUID5 from namespace + natural key) — re-running creates 0 new records
- Creates tenants, users, services, dependencies, incidents, logs, knowledge documents, chunks, embeddings
- Registers model and prompt versions
- CLI entry point: `python -m app.cli seed`

### 8.4 Demo reset (`backend/app/cli.py`)

- `python -m app.cli reset-demo` — resets all synthetic data to the seeded baseline
- Admin-only (requires demo_admin role)
- Returns summary: users_created, incidents_created, documents_ingested, tenants

---

## Phase 9: Evaluation harness

### 9.1 Versioned dataset (`backend/app/evaluation/datasets/bankops-eval-1.0.0.json`)

- Test cases across 9 types: retrieval, citation, tool_validation, injection_resistance, root_cause, abstention, policy_compliance, unsupported_claims, workflow
- Each case has: id, type, input, expected output, metadata
- Versioned (changes create a new version)

### 9.2 Metrics (`backend/app/evaluation/metrics.py`)

14 metrics computed from test case results:
- `retrieval.recall_at_5` (required, ≥0.90)
- `retrieval.mrr` (required, ≥0.80)
- `retrieval.unauthorized_leaks` (required, ==0)
- `tool.validation_accuracy` (required, ≥0.95)
- `injection.resistance` (required, ≥0.95)
- `diagnosis.root_cause_accuracy` (required, ≥0.85)
- `abstention.accuracy` (required, ≥0.90)
- `safety.policy_compliance` (required, ==1.0)
- `citation.coverage` (required, ≥0.90)
- `citation.correctness` (required, ≥0.95)
- `claims.unsupported_rate` (required, ≤0.05)
- `workflow.completion_rate` (required, ≥0.95)
- `workflow.prohibited_executions` (required, ==0)
- `workflow.failure_rate` (warning, ≤0.05)
- `workflow.latency_ms_p95` (warning, ≤30000)

### 9.3 Release gate (`backend/app/evaluation/harness.py`)

- Loads thresholds from `thresholds-1.0.0.json`
- Required metrics block promotion on failure
- Warning metrics are reported but don't block
- Gate warnings stored in the evaluation run metrics

### 9.4 Promotion workflow (`backend/app/services/promotions.py`)

- Environments: development → staging → production_ready (sequential)
- Bundle hash (prompts + model + embeddings + retrieval + index + workflow + policy + dataset)
- Promote: records bundle hash, gate failures, timestamp
- Rollback: reverts an environment to its previously active bundle

### 9.5 Retention service (`backend/app/services/retention.py`)

- Configurable retention policies per data type
- Admin-only management

---

## Phase 10: Backend tests (158 passing)

### 10.1 Test files (`backend/tests/`)

- **`test_policy.py`** — Policy engine: allow/deny/approval-required, SoD, prohibited actions, risk classification, target validation
- **`test_rag.py`** — Chunking, embeddings, hybrid retrieval, RRF, authz filters, injection defense, citations, sufficiency check
- **`test_injection.py`** — Injection pattern detection, neutralization, false-positive avoidance
- **`test_model_gateway.py`** — Mock provider, retries, circuit breaker, typed outputs, prompt registry
- **`test_workflow.py`** — 7-agent workflow, bounds, degraded mode, resumable approval, step/tool/token limits
- **`test_actions_approvals.py`** — Idempotency (CAS), rollback, verification, SoD, expiry, hash binding, invalidation, auto-resume
- **`test_api.py`** — All route groups: auth, dashboard, incidents, investigations, approvals, actions, knowledge, governance, evaluations, observability, demo, settings
- **`test_e2e.py`** — Full statement-outage scenario over HTTP: login, start, poll, approve, verify, audit chain
- **`test_evaluation.py`** — Metrics computation, release gate, promotion workflow
- **`test_seed_migrations.py`** — Idempotent seeding, alembic up/down/up round-trip

### 10.2 Bugs found and fixed during testing

- **Approved actions could never run:** `evaluate_execution` rejected actions already marked `executing` (the CAS had moved them). Fixed to accept the expected transitional state.
- **Config parsing:** comma-separated `.env` lists didn't parse (needed `NoDecode`). Relative SQLite paths depended on CWD. Both fixed.
- **Re-indexing lost injection flags:** Fixed. Unverified sources now also labeled and ranked lower.
- **15 type errors:** Fixed unsafe `None` handling across simulation, actions, workflow, seed, harness, promotions, observability, and dashboard modules.

### 10.3 Quality checks

- **ruff:** clean (line-length 145, per-file ignores for data/seed files)
- **mypy:** clean (89 source files, strict)
- **Dependency age:** 0 packages younger than 7 days (Python and npm)

---

## Phase 11: Frontend (React/TypeScript dashboard)

### 11.1 Frontend stack

- React 19.3, React DOM 19.3, React Router 7.18
- TanStack React Query 5.104 (server state management)
- Recharts 3.10 (charts)
- lucide-react 1.48 (icons — updated to current names: CircleAlert, LoaderCircle, etc.)
- Vite 8.3 (build tool)
- TypeScript 5.9 (strict mode)
- Tailwind CSS 4.3 (utility-first styling)
- Vitest 5.0 + Testing Library (unit tests)
- Playwright 1.55 (E2E tests)
- ESLint 10 + typescript-eslint (linting)

### 11.2 API layer (`frontend/src/api/`)

- **`client.ts`** — Typed API client: same-origin `/api` requests, optional `VITE_API_BASE_URL`, bearer token from sessionStorage, typed `ApiError`, request ID extraction, consistent error-envelope parsing, unauthorized callback, query parameter construction, JSON and FormData support
- **`endpoints.ts`** — Typed endpoint functions for all 54 API paths
- **`types.ts`** — TypeScript interfaces matching all backend response models
- **`sse.ts`** — Authenticated SSE stream reader with reconnection and Last-Event-ID support

### 11.3 Authentication (`frontend/src/auth/`)

- **`AuthContext.tsx`** — Revalidates saved sessions through `/auth/me`, clears revoked/expired sessions, exposes `login`, `logout`, `can(permission)`, clears React Query state on logout/unauthorized
- **`RequireAuth.tsx`** — Route guard: redirects to `/login` if not authenticated, preserves redirect target

### 11.4 Shared components (`frontend/src/components/`)

- **`Layout.tsx`** — Sidebar navigation (permission-aware, locked items show why), header with mode/health status, persistent synthetic-data banner, sign-out button
- **`ui.tsx`** — Accessible UI primitives: Button (with disabledReason), Input, Field, Card, Badge, Notice, JsonBlock, ErrorState, EmptyState, inputClass
- **`badges.tsx`** — RiskBadge, SeverityBadge, StatusBadge, RunStatusBadge, OutcomeBadge, ActionStatusBadge, ApprovalStatusBadge, DecisionBadge, ClassificationBadge, SyntheticBadge, ModeBadge
- **`Modal.tsx`** — Accessible modal dialog with focus management
- **`Toast.tsx`** — Toast notification system with auto-dismiss
- **`ApprovalControls.tsx`** — Approval UI: Approve/Reject/Cancel buttons, confirmation modal with checkbox, reason code selector, comment field, policy explanation display, disabled state with reason

### 11.5 Pages (`frontend/src/pages/`)

14 pages:

1. **`LoginPage.tsx`** — Synthetic banner, username/password fields, sign-in button, demo account quick-login buttons, error alerts, session expiration notice
2. **`OverviewPage.tsx`** — KPI cards (open incidents, critical/high, MTTR, pending approvals), 30-day trend chart, severity/status/category breakdowns, high-risk incidents list, measured AI-quality panel (recall, MRR, citation coverage, injection resistance, policy compliance, unsupported claims), recent investigation activity
3. **`IncidentsPage.tsx`** — Incident explorer with URL-synced filters (severity, status, category, search), pagination, sortable columns
4. **`IncidentDetailsPage.tsx`** — Incident timeline, synthetic logs viewer, dependency map, start-investigation control, related investigations
5. **`InvestigationsPage.tsx`** — Investigation list with status/outcome filters, pagination
6. **`InvestigationPage.tsx`** — Investigation workspace: live timeline (SSE), ranked hypotheses with confidence scores and citations, evidence panel, tool call log, agent step tracker, policy decisions with explanations, approval status, cancel/resume controls, degraded mode indicator
7. **`ApprovalsPage.tsx`** — Approval Center: pending approvals list, policy explanation per approval, action parameters (validated by tool registry), action hash display, approve/reject/cancel with confirmation modal, separation-of-duties enforcement
8. **`ActionsPage.tsx`** — Remediation Center: action list with status, tool name, target, risk level, verification results, rollback controls (manager only)
9. **`KnowledgePage.tsx`** — Knowledge Center: document list with classification and injection flags, upload form (manager only), retrieval test box, index statistics
10. **`DocumentPage.tsx`** — Document inspector: full document content, chunk list with section paths and content hashes, embedding status
11. **`GovernancePage.tsx`** — Governance Center with tabs: RBAC matrix, policy catalog, data classification, policy decisions log, audit log with hash-chain verification, model versions, prompt versions, retention policies
12. **`EvaluationsPage.tsx`** — Evaluation & Releases: evaluation run history, metrics with threshold indicators, release gate status (pass/fail with warnings), promotion controls (manager only), environment status (dev/staging/production_ready), rollback
13. **`ObservabilityPage.tsx`** — Observability: HTTP/workflow/agent/tool/LLM/retrieval/policy/approval metrics with p50/p95/p99, estimated cost, circuit breaker state, fault flags, trace waterfall (Gantt-style)
14. **`SettingsPage.tsx`** — Settings: safe configuration view (secrets shown as configured/not-configured), readiness check, admin-only demo reset and failure injection controls
15. **`DemoPage.tsx`** — Guided Demo: scenario cards with step-by-step instructions, start-scenario buttons (permission-gated), persona assignments
16. **`NotFoundPage.tsx`** — 404 page

### 11.6 App shell (`frontend/src/App.tsx`, `main.tsx`)

- React Router with lazy-loaded routes
- AuthContext provider
- TanStack QueryClient provider
- Route guards (RequireAuth)
- Permission-aware navigation

### 11.7 Frontend tests (43 passing)

- **`format.test.ts`** (12 tests) — humanize, formatDuration, formatSeconds, formatNumber, formatUsd, pct, formatMetric
- **`client.test.ts`** (12 tests) — API client: URL construction, bearer auth, error parsing, session round-trip, expired session clearing, query params, FormData
- **`badges.test.tsx`** (6 tests) — Risk, classification, synthetic, mode, incident/run/action/approval/decision/verification badges
- **`LoginPage.test.tsx`** (4 tests) — Submit disabled until filled, error on invalid credentials, clears error and navigates on success
- **`OverviewPage.test.tsx`** (2 tests) — Renders KPIs/severity/AI quality from dashboard endpoint, shows error state on failure

### 11.8 Frontend E2E tests (3 passing)

- **Statement outage end-to-end:** Analyst starts scenario → investigation runs → manager approves with confirmation → workflow resumes → actions execute and verify → investigation resolves → audit chain valid
- **Read-only viewer RBAC:** Cannot start investigations (button disabled)
- **Analyst SoD:** Cannot approve actions (approve button disabled)

### 11.9 Frontend quality

- **TypeScript:** clean (strict mode, 0 errors)
- **ESLint:** clean (0 errors)
- **Build:** OK (2536 modules, 868.72 KB / 250.12 KB gzip)
- **Dependency age:** 0 packages younger than 7 days

---

## Phase 12: Deployment artifacts

### 12.1 Docker (`docker/`)

- **`backend.Dockerfile`** — Multi-stage build: Python 3.12-slim, installs deps, creates non-root user, healthcheck, uvicorn with proxy headers
- **`frontend.Dockerfile`** — Multi-stage build: Node 22-slim builds Vite, Nginx 1.27-slim serves SPA
- **`nginx.conf`** — Security headers, /api proxy to backend, SSE support (proxy_buffering off), SPA fallback, no-cache for index.html
- **`docker-compose.yml`** — Three services: pgvector/pgvector:pg16 (db), backend (FastAPI), frontend (Nginx). Backend runs migrations + seeds on startup. Compose syntax validated.

### 12.2 Vercel (`vercel.json`)

- Build command: `cd frontend && npm ci && npm run build`
- Output: `frontend/dist`
- API redirect: `/api/*` → `${VITE_API_BASE_URL}/*`
- SPA fallback: `/*` → `/index.html`

### 12.3 Makefile

- `make install` — Install backend + frontend deps
- `make seed` — Migrate + seed
- `make run-backend` / `make run-frontend` — Start dev servers
- `make test-all` — Backend + frontend tests
- `make test-e2e` — Playwright E2E
- `make lint` — ruff + eslint
- `make typecheck` — tsc --noEmit
- `make check-deps` — Dependency age checks
- `make docker-up` / `make docker-down` — Docker Compose
- `make clean` — Remove build artifacts

### 12.4 Start/stop scripts

- **`start.bat`** — One-click Windows script: checks prerequisites, installs deps if missing, migrates, seeds, starts both servers in separate windows, opens browser
- **`stop.bat`** — Stops both servers by killing processes on ports 8000 and 5173

---

## Phase 13: Documentation (10 files)

1. **`README.md`** — Project overview, quick start, demo credentials, 5-minute walkthrough, Makefile shortcuts, project structure, verification status, documentation index
2. **`docs/ARCHITECTURE.md`** — System diagram, key design principles, workflow architecture, data flow, technology choices
3. **`docs/DIAGRAMS.md`** — 10 Mermaid diagrams: system architecture, request flow, workflow state machine, RAG pipeline, action execution, audit hash chain, auth/RBAC, evaluation gate, data model ERD, deployment topology
4. **`docs/SECURITY.md`** — Security principles, authentication, authorization, tenant isolation, data classification, input validation, prompt injection defense, action safety, audit, API security, secrets management, threat model, limitations
5. **`docs/RBAC_POLICY_MATRIX.md`** — 5 roles, 27 permissions, full permission matrix, 10 policy rules, action risk catalog, prohibited actions
6. **`docs/RAG_INJECTION_DEFENSE.md`** — RAG architecture, chunking, embeddings, hybrid retrieval, authorization filters, sufficiency check, citations, injection defense layers, pattern catalog, testing
7. **`docs/EVALUATION_LLMOPS.md`** — Evaluation harness, dataset, 14 metrics, release gate, promotion workflow, observability, trace waterfall, cost estimation, limitations
8. **`docs/DEPLOYMENT.md`** — Local development, Docker Compose, Vercel, production hardening checklist, Docker daemon availability note
9. **`docs/INTERVIEW_GUIDE.md`** — Elevator pitch, 6 key talking points with Q&A, 5-minute demo walkthrough, expected questions
10. **`docs/DECISIONS.md`** — 10 design decisions with rationale and trade-offs
11. **`docs/VERIFICATION_REPORT.md`** — Full verification matrix with exact commands and results

---

## Verification summary

| Check | Command | Result |
|---|---|---|
| Backend tests | `pytest` | 158 passed |
| Backend lint | `ruff check app tests` | clean |
| Backend types | `mypy app` | clean (89 files) |
| Backend dep age | `check_dependency_age.py` | 0 < 7 days |
| Frontend types | `tsc --noEmit` | clean |
| Frontend lint | `eslint .` | clean |
| Frontend build | `vite build` | OK (250 KB gzip) |
| Frontend tests | `vitest run` | 43 passed |
| Frontend E2E | `playwright test` | 3 passed |
| Frontend dep age | `check_npm_dependency_age.mjs` | 0 < 7 days |
| Docker Compose | `docker compose config` | valid |
| Docker build | — | not verified (daemon unavailable) |
| PostgreSQL | — | not verified (daemon unavailable) |
| Live backend | `curl /health` | OK |
| Live frontend | `curl /` | OK |
| Live login | `POST /api/auth/login` | OK |
| Security headers | `curl -I` | OK (nosniff, DENY, CSP, no-store) |
| E2E scenario | Playwright | OK (full flow verified) |

---

## What this project does NOT do (honest limitations)

- Does not connect to real banking systems
- Does not handle real customer data
- Does not execute real transactions
- Does not perform destructive actions
- Does not use HSM-backed key management
- Does not implement mTLS between services
- Does not have a SIEM integration
- Does not implement field-level encryption for PII
- Does not have a formal penetration test certification
- Docker images were not built (daemon unavailable)
- PostgreSQL + pgvector path was not verified (daemon unavailable)
- Evaluation scores in MOCK MODE verify pipeline logic, not model quality
- The promotion workflow is a simulation (no actual deployment occurs)
- Observability metrics are in-process (no Prometheus/Grafana)
