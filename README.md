# BankOps AI Command Center

> **SYNTHETIC DEMO — NOT A REAL BANKING SYSTEM.**
> Every bank, customer, account ID, amount, service, metric and log line is fictional.
> Remediation only mutates seeded demo state. The platform never connects to real banking systems,
> never executes real transactions and never performs destructive actions.

A portfolio/interview demonstration of governed AI for banking operations incident response.
The system shows how an LLM-based multi-agent workflow can investigate synthetic operations
incidents while remaining **deterministic at every authorization boundary** — the model is never
the authorization boundary.

## What it demonstrates

| Capability | How |
|---|---|
| **Governed RAG** | Hybrid retrieval (vector + BM25 with reciprocal-rank fusion) over fictional runbooks, with tenant/classification/role filters enforced in the query and citations on every claim. |
| **Bounded multi-agent orchestration** | A 7-agent LangGraph workflow with step, tool-call, token and timeout limits. LLM output is untrusted and validated through Pydantic schemas. |
| **Typed allowlisted tools** | A typed tool registry. Unknown tools, unexpected fields and unauthorized targets are rejected. |
| **Deterministic policy enforcement** | A policy engine in application code (never in a prompt) decides allow/deny/approval-required. It keeps working when the model provider is unavailable. |
| **Human approval & separation of duties** | Medium/high-risk actions require approval. A requester can never approve their own high-risk action. Approvals are bound to an action hash and expire. |
| **Simulated remediation only** | Actions mutate seeded demo state. Every action has an idempotency key, preconditions, a state snapshot for rollback and post-action verification. |
| **Post-action verification & rollback** | Verification checks confirm the simulated effect; rollback restores the snapshot. |
| **Append-only audit** | Every decision and action is recorded in a hash-chained audit log. UPDATE/DELETE are blocked by database triggers. The chain can be verified at any time. |
| **Evaluation & release gates** | A reproducible evaluation harness on a versioned synthetic dataset measures retrieval, citation, safety, injection resistance and policy compliance. A release gate blocks promotion on failures. |
| **Observability / LLMOps** | Request, workflow, agent, tool, model, retrieval, policy and approval metrics with p50/p95/p99 latency, token counts, estimated cost and a trace waterfall. |
| **Secure auth, RBAC & tenant isolation** | Argon2 password hashing, short-lived JWTs with revocation, 5 roles, 27 permissions, object-level tenant isolation and data classification clearance. |

## Quick start (local, no Docker, no API keys)

**Prerequisites:** Python 3.12+, Node.js 20+, GNU Make (optional).

```bash
# 1. Backend
cd backend
python -m venv .venv
# Windows (Git Bash):  .venv/Scripts/python -m pip install -r requirements-dev.txt
# Windows (PowerShell): .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# Linux/macOS:         .venv/bin/python -m pip install -r requirements-dev.txt
cp ../.env.example ../.env
.venv/Scripts/python -m alembic upgrade head    # create the SQLite database
.venv/Scripts/python -m app.cli seed            # seed synthetic data
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. Frontend (new terminal)
cd frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173** and sign in.

**Demo credentials:** all accounts use `BankOpsDemo!2026` (local-only, set in `.env`).

| Tenant | Username | Role |
|---|---|---|
| Contoso | `demo.admin` | Demo administrator |
| Contoso | `ops.analyst` | Operations analyst |
| Contoso | `ops.analyst2` | Operations analyst |
| Contoso | `ops.manager` | Operations manager |
| Contoso | `ops.manager2` | Operations manager |
| Contoso | `risk.auditor` | Auditor (read-only) |
| Contoso | `readonly.viewer` | Read-only viewer |
| Fabrikam | `fab.analyst` | Operations analyst |
| Fabrikam | `fab.manager` | Operations manager |

## 5-minute walkthrough

1. **Overview** (30s): note the synthetic banner, KPIs, MOCK MODE badge and the measured AI-quality panel.
2. **Scenario A** (2m): sign in as `ops.analyst`, open **Guided Demo**, start the statement outage. Watch the live timeline, authorized citations, ranked hypotheses and deterministic policy decisions.
3. **Approval** (1m): sign out, sign in as `ops.manager`, open **Approval Center**, review the policy explanation and evidence, approve with explicit confirmation.
4. **Outcome** (1m): the workflow resumes — simulated restart, reprocess, verification and the final report with citations.
5. **Governance** (30s): open **Governance Center → Audit log**, click **Verify hash chain**.

## Makefile shortcuts

```bash
make install       # install backend + frontend deps
make seed          # migrate + seed
make run-backend   # start backend (port 8000)
make run-frontend  # start frontend (port 5173)
make test-all      # backend + frontend tests
make test-e2e      # Playwright E2E (requires both servers running)
make lint          # ruff + eslint
make check-deps    # verify all packages are >= 7 days old
make docker-up     # start Docker Compose stack (requires Docker daemon)
```

## Docker

```bash
make docker-up     # PostgreSQL + pgvector, backend, frontend
# Frontend: http://localhost
# Backend:  http://localhost:8000/docs
make docker-down
```

> **Note:** The Docker daemon was unavailable during development, so Docker images were
> not built locally. The Compose file syntax is validated. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Project structure

```
├── backend/
│   ├── app/
│   │   ├── ai/            # model gateway, prompt registry, typed outputs
│   │   ├── agents/        # LangGraph workflow, tool registry, simulation
│   │   ├── api/           # FastAPI routes, middleware, serializers
│   │   ├── core/          # config, security, middleware
│   │   ├── evaluation/    # versioned dataset, metrics, release gate
│   │   ├── models/        # SQLAlchemy models
│   │   ├── policy/        # RBAC, permissions, deterministic policy engine
│   │   ├── rag/           # chunking, embeddings, retrieval, injection defense
│   │   ├── seed/          # synthetic data, guided scenarios
│   │   └── services/      # actions, approvals, audit, investigations, etc.
│   ├── alembic/           # migrations
│   └── tests/             # 158 tests
├── frontend/
│   ├── src/
│   │   ├── api/           # typed client, endpoints, SSE
│   │   ├── auth/          # auth context, route guards
│   │   ├── components/    # UI, badges, modal, toast, layout
│   │   ├── pages/         # 14 pages
│   │   └── lib/           # formatting, investigation events hook
│   └── e2e/               # Playwright E2E tests
├── docker/                # Dockerfiles, Compose, Nginx config
├── docs/                  # architecture, security, interview guide, etc.
├── scripts/               # dependency-age checkers
├── .env.example           # documented environment variables
├── Makefile               # common tasks
└── vercel.json            # Vercel deployment config
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Security model & threat model](docs/SECURITY.md)
- [RBAC & policy matrix](docs/RBAC_POLICY_MATRIX.md)
- [RAG & injection defense](docs/RAG_INJECTION_DEFENSE.md)
- [Evaluation & LLMOps](docs/EVALUATION_LLMOPS.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Interview guide](docs/INTERVIEW_GUIDE.md)
- [Design decisions](docs/DECISIONS.md)

## Verification status

| Check | Result |
|---|---|
| Backend tests (pytest) | 158 passed |
| Frontend unit tests (vitest) | 43 passed |
| Frontend E2E (Playwright) | 3 passed |
| Frontend build (tsc + vite) | OK (≈250 KB gzipped) |
| Frontend lint (eslint) | clean |
| Backend lint (ruff) | clean |
| Backend types (mypy) | clean |
| Dependency-age check | 0 packages < 7 days |
| Docker Compose syntax | valid |
| Docker image build | not verified (daemon unavailable) |
| PostgreSQL + pgvector | not verified (daemon unavailable) |

## License

This is a demonstration project. All data is synthetic and fictional.
