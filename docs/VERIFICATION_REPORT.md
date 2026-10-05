# Final Verification Report

> **BankOps AI Command Center — SYNTHETIC DEMO**
> Generated: 2026-10-12
> All data is fictional. No real banking systems are involved.

## Summary

| Category | Check | Result |
|---|---|---|
| Backend | Tests (pytest) | **158 passed**, 0 failed |
| Backend | Lint (ruff) | **clean** (0 errors) |
| Backend | Types (mypy) | **clean** (89 files, 0 errors) |
| Backend | Dependency age (≥7 days) | **0 packages younger than 7 days** |
| Frontend | Type check (tsc --noEmit) | **clean** (0 errors) |
| Frontend | Lint (eslint) | **clean** (0 errors) |
| Frontend | Build (vite build) | **OK** (2536 modules, 868.72 KB / 250.12 KB gzip) |
| Frontend | Unit tests (vitest) | **43 passed**, 0 failed |
| Frontend | E2E tests (Playwright) | **3 passed**, 0 failed |
| Deployment | Docker Compose syntax | **valid** |
| Deployment | Docker image build | **not verified** (Docker daemon unavailable) |
| Deployment | PostgreSQL + pgvector | **not verified** (Docker daemon unavailable) |
| Live | Backend health (`/health`) | **OK** (`{"status":"ok"}`) |
| Live | Backend readiness (`/ready`) | **OK** (DB, migration head, 88 chunks, MOCK mode) |
| Live | Frontend proxy → backend login | **OK** (verified with `ops.analyst`) |
| Live | Security headers | **OK** (nosniff, DENY, no-referrer, CSP, no-store) |
| Live | E2E scenario (statement outage) | **OK** (analyst starts, manager approves, investigation resolves, audit chain valid) |

## Detailed results

### Backend tests

```
$ cd backend && .venv/Scripts/python -m pytest --tb=short -q
........................................................................ [ 45%]
........................................................................ [ 91%]
..............                                                           [100%]
158 passed in 12.3s
```

Test coverage:
- Policy engine (allow/deny/approval-required, SoD, prohibited actions)
- RAG (chunking, embeddings, hybrid retrieval, authz filters, injection defense, citations)
- Model gateway (mock provider, retries, circuit breaker, typed outputs)
- Tool registry (typed parameters, allowlist, target validation)
- Action service (idempotency, CAS, rollback, verification)
- Approval service (SoD, expiry, hash binding, invalidation)
- Workflow (7 agents, bounds, degraded mode, resumable approval)
- API routes (auth, dashboard, incidents, investigations, approvals, actions, knowledge, governance, evaluations, observability, demo, settings)
- Seed/migration (idempotent seeding, alembic up/down/up round-trip)
- Evaluation (metrics, release gate, promotion workflow)

### Backend lint

```
$ cd backend && .venv/Scripts/python -m ruff check app tests
All checks passed!
```

### Backend type check

```
$ cd backend && .venv/Scripts/python -m mypy app
Success: no issues found in 89 source files
```

### Backend dependency age

```
$ backend/.venv/Scripts/python scripts/check_dependency_age.py
Checked installed packages; 0 younger than 7 days, 0 unknown.
```

### Frontend type check

```
$ cd frontend && npm run typecheck
(clean — 0 errors)
```

### Frontend lint

```
$ cd frontend && npm run lint
(clean — 0 errors)
```

### Frontend build

```
$ cd frontend && npm run build
> tsc --noEmit && vite build
✓ 2536 modules transformed.
dist/index.html                   0.72 kB │ gzip:   0.40 kB
dist/assets/index-ChUqGwU4.css   36.55 kB │ gzip:   7.94 kB
dist/assets/index-CXmHOJ49.js   868.72 kB │ gzip: 250.12 kB
✓ built in 1.50s
```

### Frontend unit tests

```
$ cd frontend && npx vitest run
Test Files  5 passed (5)
     Tests  43 passed (43)
```

Test files:
- `src/lib/format.test.ts` (12 tests) — formatting utilities
- `src/api/client.test.ts` (12 tests) — API client, session management, error handling
- `src/components/badges.test.tsx` (6 tests) — badge rendering
- `src/pages/LoginPage.test.tsx` (4 tests) — login form, validation, error handling
- `src/pages/OverviewPage.test.tsx` (2 tests) — dashboard rendering, error state

### Frontend dependency age

```
$ node scripts/check_npm_dependency_age.mjs frontend/package-lock.json
Checked 340 npm packages; 0 younger than 7 days, 0 unknown.
```

### Frontend E2E tests (Playwright)

```
$ cd frontend && npx playwright test --reporter=list
  ok 1 [chromium] › analyst starts, manager approves, investigation resolves (18.8s)
  ok 2 [chromium] › read-only viewer cannot start investigations (4.3s)
  ok 3 [chromium] › analyst cannot approve (separation of duties) (3.9s)
  3 passed (31.0s)
```

The E2E test exercises the full statement-outage scenario:
1. Analyst logs in, starts the scenario from the Guided Demo page
2. Investigation runs (7 agents, 14 tool calls), reaches awaiting_approval
3. Manager logs in (separate browser context), opens Approval Center
4. Manager reviews the policy explanation, opens the approval modal, checks the confirmation checkbox, confirms approval
5. Workflow resumes — simulated restart, reprocess, verification
6. Investigation completes with resolved status
7. Audit hash chain verified as valid

The RBAC test verifies that a read-only viewer cannot start investigations (button disabled).
The SoD test verifies that an analyst cannot approve actions (approve button disabled).

### Docker Compose syntax

```
$ docker compose -f docker/docker-compose.yml config --quiet
(exit code 0 — valid)
```

### Live server verification

```
$ curl -sf http://127.0.0.1:8000/health
{"status":"ok","version":"1.0.0","environment":"local","synthetic_data":true}

$ curl -sf http://127.0.0.1:8000/ready
{"status":"ready","database":"ok","migration_head":"0001","indexed_chunks":88,...}

$ curl -sf http://127.0.0.1:5173/ | head -1
<!doctype html>
```

Login through the Vite proxy:
```
$ curl -sf -X POST http://127.0.0.1:5173/api/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"ops.analyst","password":"BankOpsDemo!2026"}'
{"token":"...","expiresAt":"...","user":{...}}
```

Security headers observed:
- `x-content-type-options: nosniff`
- `x-frame-options: DENY`
- `referrer-policy: no-referrer`
- `content-security-policy: default-src 'none'; frame-ancestors 'none'`
- `cache-control: no-store`

## Items not verified (infrastructure limitations)

| Item | Reason | Mitigation |
|---|---|---|
| Docker image build | Docker daemon unavailable on this machine | Dockerfiles written and Compose syntax validated; run `make docker-up` on a machine with Docker |
| PostgreSQL + pgvector path | Docker daemon unavailable | SQLite path fully verified; migration includes pgvector-specific code (extension, HNSW index) |
| Live model provider | No API key configured | MOCK mode fully verified; OpenAI-compatible provider code is present and tested via mock |
| Vercel deployment | Not deployed | `vercel.json` written; requires a backend hosting provider |

## Synthetic/demo-only confirmation

- All banks, customers, accounts, amounts, services, metrics and logs are fictional.
- No real banking systems are connected.
- No real transactions are executed.
- No destructive actions are performed.
- All remediation mutates seeded demo state only.
- The platform is explicitly labeled as synthetic in the UI, API and documentation.

## How to reproduce

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
cp ../.env.example ../.env
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m app.cli seed
.venv/Scripts/python -m pytest                    # 158 tests
.venv/Scripts/python -m ruff check app tests      # clean
.venv/Scripts/python -m mypy app                  # clean
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Frontend (new terminal)
cd frontend
npm ci
npm run typecheck    # clean
npm run lint         # clean
npm run build        # OK
npm run test         # 43 tests
npx playwright test  # 3 tests (requires backend + frontend running)

# Dependency age
backend/.venv/Scripts/python ../scripts/check_dependency_age.py
node ../scripts/check_npm_dependency_age.mjs frontend/package-lock.json

# Docker (if daemon available)
docker compose -f docker/docker-compose.yml config --quiet  # syntax check
docker compose -f docker/docker-compose.yml up -d            # start stack
```
