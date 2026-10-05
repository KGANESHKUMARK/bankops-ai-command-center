# Architecture

## Overview

BankOps AI Command Center is a monorepo with a FastAPI backend and a React/TypeScript frontend.
The backend implements governed AI investigation of synthetic banking operations incidents;
the frontend provides a role-aware operations dashboard.

## System diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Browser (SPA)                            │
│  React 19 + Vite + Tailwind + TanStack Query + React Router     │
│  14 pages: Overview, Incidents, Investigations, Approvals,      │
│  Actions, Knowledge, Governance, Evaluations, Observability,     │
│  Settings, Demo, Login, Document detail, Investigation detail    │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTPS / SSE
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend                             │
│                                                                  │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  ┌───────────────┐   │
│  │  Auth   │  │ Incidents │  │ Knowledge │  │  Governance   │   │
│  │  (JWT)  │  │  + Inv.   │  │  (RAG)    │  │  (Audit, RBAC)│   │
│  └────┬────┘  └─────┬─────┘  └─────┬─────┘  └───────┬───────┘   │
│       │             │              │                │            │
│  ┌────▼─────────────▼──────────────▼────────────────▼──────┐    │
│  │              Deterministic Policy Engine                 │    │
│  │  (allow / deny / require_approval — never in a prompt)   │    │
│  └────┬─────────────┬──────────────┬────────────────┬──────┘    │
│       │             │              │                │            │
│  ┌────▼────┐  ┌─────▼─────┐  ┌─────▼─────┐  ┌──────▼──────┐    │
│  │  Model  │  │  Tool     │  │  Action   │  │  Audit      │    │
│  │ Gateway │  │ Registry  │  │  Service  │  │  (hash-chain)│   │
│  │(mock/   │  │(typed,    │  │(idempotent│  │(append-only)│    │
│  │ OpenAI) │  │ allowlist)│  │ + verify) │  │             │    │
│  └─────────┘  └───────────┘  └───────────┘  └─────────────┘    │
│       │                                                        │
│  ┌────▼──────────────────────────────────────────────────┐     │
│  │         LangGraph Bounded Workflow (7 agents)          │     │
│  │  Orchestrator → Triage → Evidence → Diagnostic →       │     │
│  │  Remediation Planner → Governance Review →             │     │
│  │  Policy Engine → Simulated Executor → Verification →   │     │
│  │  Final Report                                          │     │
│  └───────────────────────────────────────────────────────┘     │
│                                                                  │
│  Database: SQLite (local) / PostgreSQL + pgvector (Docker)      │
└─────────────────────────────────────────────────────────────────┘
```

## Key design principles

1. **The LLM is never the authorization boundary.** The deterministic policy engine
   decides what actions are allowed, denied or require approval. The model can only
   propose; the policy engine disposes.

2. **All LLM output is untrusted.** Agent outputs are validated through Pydantic schemas.
   Retrieved documents, tool results, logs and analyst notes are treated as data, not
   instructions. Prompt-injection patterns are neutralized at ingestion and at retrieval.

3. **Everything is simulated.** Actions mutate seeded demo state only. There are no real
   banking connections, no real transactions, no real money movement. Every action has
   an idempotency key, preconditions, a state snapshot for rollback and post-action
   verification.

4. **The system is auditable.** Every decision and action is recorded in a hash-chained
   audit log. UPDATE/DELETE are blocked by database triggers. The chain can be verified
   at any time.

5. **The system degrades safely.** When the model provider is unavailable, the circuit
   breaker opens and the workflow runs in degraded mode (deterministic fallbacks). The
   policy engine, audit log and all authorization checks keep working.

## Workflow architecture

The investigation workflow (`investigation-wf-1.4.0`) is a LangGraph state machine with
7 agent nodes plus a deterministic policy gate:

1. **Orchestrator** — routes the investigation, tracks step count and budget
2. **Triage Agent** — classifies the incident and determines the investigation approach
3. **Evidence Retrieval Agent** — runs governed RAG queries with authorization filters
4. **Diagnostic Agent** — calls typed diagnostic tools (read-only) to gather signals
5. **Remediation Planner Agent** — proposes allowlisted actions with parameters
6. **Governance/Risk Reviewer** — reviews the plan against policy rules
7. **Deterministic Policy Engine** — decides allow/deny/approval-required (not an LLM)
8. **Simulated Executor** — executes approved actions against demo state with CAS locking
9. **Verification Agent** — verifies the simulated effect
10. **Final Report Composer** — assembles the report with citations

The workflow is bounded by:
- Maximum steps (configurable)
- Maximum tool calls per step
- Token budget
- Per-step timeout
- Total timeout

When an action requires approval, the workflow pauses (persisted state) and resumes when
the approval is granted. The policy engine re-checks the approval scope, expiry and action
hash immediately before execution.

## Data flow

```
Incident → Start Investigation
  → Triage (classifies)
  → Evidence Retrieval (RAG: vector + BM25, authz-filtered, injection-neutralized)
  → Diagnostic (typed tools: query_service_metrics, query_logs, query_dependencies)
  → Remediation Planner (proposes allowlisted actions)
  → Governance Review (reviews plan)
  → Policy Engine (allow / deny / require_approval)
  → [if approval required] → Human Approval → Resume
  → Simulated Executor (idempotent, CAS-locked, snapshot for rollback)
  → Verification Agent (checks simulated effect)
  → Final Report (with citations)
  → Incident resolved
```

## Technology choices

| Layer | Technology | Why |
|---|---|---|
| Backend | FastAPI | Async, OpenAPI, type-safe, widely known |
| ORM | SQLAlchemy 2.0 | Portable between SQLite and PostgreSQL |
| Migrations | Alembic | Standard for SQLAlchemy |
| Workflow | LangGraph | Stateful, resumable, bounded execution |
| Vector DB | pgvector / SQLite | Portable; no separate service for local dev |
| Frontend | React 19 + Vite | Modern, fast, widely known |
| State | TanStack Query | Server state management with caching |
| Charts | Recharts | Simple, composable |
| Styling | Tailwind CSS 4 | Utility-first, no custom CSS framework |
| Tests | pytest / Vitest / Playwright | Standard per layer |
| Auth | Argon2 + JWT | Strong password hashing, stateless tokens |
