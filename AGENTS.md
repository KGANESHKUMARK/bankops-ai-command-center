# BankOps AI Command Center — Project Memory

## Project identity

- **Name:** BankOps AI Command Center
- **Type:** Portfolio/interview demonstration (SYNTHETIC DEMO — not a real banking system)
- **Location:** `D:\Siddharitha\SIDDHARITHA TECHNOLOGIES PRIVATE LIMITED\Projects\Linkedin\BankOps AI Command Centre`
- **Status:** Complete and verified (all 17 planned tasks done)

## Quick start

```bash
# Windows one-click:
start.bat          # checks deps, migrates, seeds, starts both servers, opens browser
stop.bat           # stops both servers

# Manual:
cd backend && .venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev
```

- Frontend: http://127.0.0.1:5173
- Backend API docs: http://127.0.0.1:8000/docs
- Demo password (all accounts): `BankOpsDemo!2026`
- Recommended logins: `ops.analyst` (investigate), `ops.manager` (approve)

## Tech stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, LangGraph, Pydantic
- **Frontend:** React 19, Vite 8, TypeScript 5.9, Tailwind CSS 4, TanStack Query 5, Recharts 3
- **Database:** SQLite (local dev), PostgreSQL + pgvector (Docker)
- **AI:** Mock provider (default, no API keys), OpenAI-compatible provider (optional)
- **Tests:** pytest (158), Vitest (43), Playwright (3)

## Key commands

| Command | What it does |
|---|---|
| `make install` | Install all deps |
| `make seed` | Migrate + seed synthetic data |
| `make run-backend` | Start backend on :8000 |
| `make run-frontend` | Start frontend on :5173 |
| `make test-all` | Backend + frontend tests |
| `make test-e2e` | Playwright E2E (needs both servers running) |
| `make lint` | ruff + eslint |
| `make check-deps` | Verify all packages ≥7 days old |

## Environment

- Python venv: `backend/.venv` (use `.venv/Scripts/python` on Windows)
- Node: v22.19.0, npm 10.9.3
- Docker daemon: UNAVAILABLE on this machine (Dockerfiles written, syntax validated, images not built)
- PostgreSQL CLI: not installed (SQLite path fully verified)
- `.env` is git-ignored, copied from `.env.example`

## Architecture summary

- **The LLM is never the authorization boundary.** A deterministic policy engine decides allow/deny/approval. The model can only propose.
- 7-agent LangGraph workflow, bounded by steps/tools/tokens/timeouts, resumable after approval
- Governed RAG: hybrid retrieval (vector + BM25 + RRF), authz-filtered before ranking, injection-neutralized at ingest and retrieve
- Typed allowlisted tools with Pydantic validation
- Simulated remediation only: idempotent (CAS), rollback, post-action verification
- Append-only hash-chained audit log with DB triggers
- 5 roles, 27 permissions, tenant isolation, data classification
- Evaluation harness with 14 metrics and release gate

## Verification results

| Check | Result |
|---|---|
| Backend tests | 158 passed |
| Frontend unit tests | 43 passed |
| Frontend E2E | 3 passed |
| Frontend build | OK (250 KB gzip) |
| ruff / mypy / eslint / tsc | all clean |
| Dependency age (Python + npm) | 0 < 7 days |
| Docker Compose syntax | valid |
| Docker image build | NOT verified (daemon unavailable) |
| PostgreSQL + pgvector | NOT verified (daemon unavailable) |

## Documentation files

- `README.md` — overview, quick start, demo walkthrough
- `docs/DIAGRAMS.md` — 10 Mermaid diagrams (architecture, flow, ERD, deployment)
- `docs/ARCHITECTURE.md` — system design, principles, data flow
- `docs/SECURITY.md` — security model, threat model
- `docs/RBAC_POLICY_MATRIX.md` — roles, permissions, policy rules
- `docs/RAG_INJECTION_DEFENSE.md` — RAG pipeline, injection defense
- `docs/EVALUATION_LLMOPS.md` — evaluation, metrics, observability
- `docs/DEPLOYMENT.md` — Docker, Vercel, production hardening
- `docs/INTERVIEW_GUIDE.md` — talking points, demo walkthrough, Q&A
- `docs/DECISIONS.md` — 10 design decisions with rationale
- `docs/WORK_DONE.md` — comprehensive list of everything built
- `docs/VERIFICATION_REPORT.md` — full verification matrix

## Bugs found and fixed during development

1. Approved actions could never run (CAS check rejected `executing` state) — fixed
2. Config: CSV `.env` lists didn't parse; relative SQLite paths depended on CWD — fixed
3. Re-indexing lost injection flags — fixed; unverified sources now down-ranked
4. 15 mypy type errors (unsafe None handling) — fixed
5. jsdom 30 needed Node ≥22.22; downgraded to jsdom 29.1.1 for Node 22.19
6. Lucide 1.x dropped old icon aliases (AlertTriangle, Trash2, Loader2) — updated to new names
7. Frontend test assertion mismatches (format functions, badge text, locale-dependent number formatting) — fixed

## Important notes

- All data is SYNTHETIC and FICTIONAL. No real banking systems are involved.
- The evaluation scores (mostly 1.0 in MOCK MODE) verify pipeline logic, not model quality.
- The promotion workflow is a simulation — no actual deployment occurs.
- Observability metrics are in-process (no Prometheus/Grafana).
- Nothing has been committed to git yet.
