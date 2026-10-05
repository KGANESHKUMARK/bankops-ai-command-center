# Security Model & Threat Model

> **SYNTHETIC DEMO — NOT A REAL BANKING SYSTEM.**
> This document describes the security design of a portfolio/interview demonstration.
> It is not a production security certification.

## Security principles

1. **The LLM is never the authorization boundary.** A deterministic policy engine in
   application code decides what actions are allowed, denied or require approval.
   The model can only propose; the policy engine disposes.

2. **All LLM output is untrusted.** Agent outputs are validated through Pydantic schemas.
   Retrieved documents, tool results, logs and analyst notes are treated as data, not
   instructions.

3. **Everything is simulated.** Actions mutate seeded demo state only. There are no real
   banking connections, no real transactions, no real money movement.

4. **Defense in depth.** Security controls operate at multiple layers: network, API,
   application, database and audit.

## Authentication

- **Password hashing:** Argon2 (via `argon2-cffi`) with default parameters.
- **Tokens:** Short-lived JWTs (30-minute default expiry), signed with HS256.
- **Token revocation:** JWTs are checked against a revocation list on every request.
- **Session storage:** Tokens are stored in `sessionStorage` (cleared when the tab closes).
  No cookies are used, so CSRF does not apply.
- **Demo accounts:** All demo accounts use a single local-only password (`DEMO_PASSWORD`
  from `.env`). Demo accounts are refused outside local/demo mode.

## Authorization (RBAC)

5 roles, 27 permissions. See [RBAC_POLICY_MATRIX.md](RBAC_POLICY_MATRIX.md) for the full matrix.

- Permissions are enforced on **every** API endpoint via FastAPI dependencies.
- The UI uses permissions only for presentation/gating; the server is authoritative.
- Object-level checks enforce tenant isolation (a Contoso user cannot see Fabrikam data).
- Data classification clearance is enforced on knowledge documents and retrieval results.

## Tenant isolation

- Every database query that returns tenant-scoped data filters by `tenant_id`.
- The `tenant_id` is extracted from the JWT, not from the request body.
- Cross-tenant access is tested in the backend test suite.

## Data classification

Four levels: `public`, `internal`, `confidential`, `restricted`.

- Each role has a clearance level (the highest classification it may read).
- Knowledge documents are tagged with a classification.
- Retrieval results are filtered by the user's clearance before ranking.
- Ingestion validates that the uploader's clearance is >= the document's classification.

## Input validation

- All request models use Pydantic with `extra="forbid"` to prevent mass assignment.
- File uploads are size-limited and content-sniffed (Markdown, text, PDF only).
- URL parameters are validated and bounded.
- SQL injection is prevented by SQLAlchemy parameterized queries.

## Prompt injection defense

See [RAG_INJECTION_DEFENSE.md](RAG_INJECTION_DEFENSE.md) for details.

- Documents, logs, tool results and analyst notes are treated as untrusted data.
- Instruction-like patterns are detected and neutralized at ingestion and at retrieval.
- The system prompt explicitly instructs the model to treat all retrieved content as data.
- The policy engine does not parse model output for authorization decisions.

## Action safety

- **Allowlisted tools only:** Unknown tools are rejected. Each tool has typed parameters
  validated by Pydantic.
- **Prohibited actions:** Certain actions (e.g., `delete_customer_record`,
  `modify_transaction_amount`) are explicitly prohibited and can never be executed.
- **Risk-based approval:** Low-risk actions execute automatically. Medium/high-risk
  actions require human approval.
- **Separation of duties:** A requester can never approve their own high-risk action.
- **Approval binding:** Approvals are bound to an action hash. Any change to the plan
  invalidates the approval.
- **Approval expiry:** Approvals expire after a configurable TTL.
- **Idempotency:** Every action has an idempotency key. Duplicate execution is prevented
  via compare-and-swap (CAS) on the action status.
- **Preconditions:** Each action has preconditions that are checked before execution.
- **Rollback:** Actions that support rollback have a state snapshot captured before
  execution. Rollback restores the snapshot.
- **Post-action verification:** Verification checks confirm the simulated effect.
- **Policy re-check:** The policy engine re-checks the approval scope, expiry and action
  hash immediately before execution.

## Audit

- **Append-only:** `audit_events` table has database triggers that block UPDATE and DELETE
  (on both SQLite and PostgreSQL).
- **Hash chain:** Each event stores `SHA-256(prev_hash + canonical_event)`. Tampering
  with any event breaks the chain.
- **Verification:** The `/governance/audit/verify` endpoint walks the chain and reports
  the first invalid event (if any).
- **Coverage:** Every authentication, policy decision, approval, action execution,
  rollback, verification, ingestion, search, evaluation and promotion is audited.

## API security

- **CORS:** Configurable allowed origins (default: localhost only).
- **Security headers:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`,
  `Content-Security-Policy`.
- **Body size limits:** Request bodies are size-limited (configurable).
- **Rate limiting:** Login attempts are rate-limited per IP and per username.
- **Request IDs:** Every request gets a unique `X-Request-ID` for traceability.
- **No secrets in responses:** The `/settings` endpoint returns only whether secrets are
  configured, never the values.

## Secrets management

- All secrets are in environment variables (`.env` for local dev, git-ignored).
- `.env.example` documents all variables without real values.
- The JWT secret, demo password, and API keys are never logged or returned in API responses.

## Threat model (simplified)

| Threat | Mitigation |
|---|---|
| Prompt injection via retrieved documents | Neutralization at ingestion and retrieval; model instructed to treat content as data; policy engine independent of model output |
| Unauthorized data access (cross-tenant) | Object-level `tenant_id` filtering on every query; tested |
| Unauthorized action execution | Deterministic policy engine; allowlisted tools; risk-based approval; SoD |
| Mass assignment | Pydantic `extra="forbid"` on all request models |
| Privilege escalation | Permissions checked per endpoint; RBAC matrix tested |
| Audit tampering | Append-only triggers; hash chain; verification endpoint |
| Token theft | Short-lived JWTs; sessionStorage (not localStorage); revocation list |
| Brute force login | Rate limiting per IP and username |
| XSS | CSP headers; untrusted content rendered as text (not HTML); no `dangerouslySetInnerHTML` |
| CSRF | No cookies; JWT in Authorization header |
| DoS via large payloads | Body size limits; rate limiting |
| Supply chain attack | All dependencies pinned; 7-day minimum age policy enforced |

## What this demo does NOT do

- It does not implement real banking integrations.
- It does not handle real customer data.
- It does not use HSM-backed key management.
- It does not implement mTLS between services.
- It does not have a SIEM integration (audit is self-contained).
- It does not implement field-level encryption for PII.
- It does not have a formal penetration test certification.

These are noted as future production hardening requirements, not current claims.
