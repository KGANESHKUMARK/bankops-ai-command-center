# Design Decisions

## D-001: The LLM is never the authorization boundary

**Decision:** A deterministic policy engine in application code decides what actions are
allowed, denied or require approval. The model can only propose actions.

**Rationale:** LLMs are probabilistic and can be influenced by prompt injection. Authorization
decisions must be deterministic, auditable and independent of model output. Putting
authorization in a prompt would make it non-deterministic, non-auditable and vulnerable
to injection.

**Trade-offs:** The system is less flexible than a fully model-driven approach — the
allowlist of tools and the risk classification are hardcoded. But this is a feature, not
a bug: it makes the system predictable and testable.

## D-002: Mock provider as a first-class citizen

**Decision:** The mock provider is not a stub — it's a fully functional deterministic
provider that generates realistic investigation output. It's the default and runs without
API keys.

**Rationale:** The demo must run offline for portfolio/interview use. The mock provider
also makes the evaluation harness reproducible — the same input always produces the same
output, so metrics are stable.

**Trade-offs:** The mock provider's output is deterministic, so evaluation scores in MOCK
MODE verify pipeline logic, not model quality. This is clearly documented.

## D-003: SQLite for local development, PostgreSQL + pgvector for Docker

**Decision:** The system supports both SQLite and PostgreSQL. SQLite is the default for
local development; PostgreSQL + pgvector is used in the Docker Compose stack.

**Rationale:** SQLite requires no setup and is sufficient for a single-user demo.
PostgreSQL + pgvector is needed for production-like vector search performance.

**Trade-offs:** The SQLite vector search is slower (linear scan vs. HNSW index), but
works fine for the demo dataset (88 chunks). The migration includes dialect-specific
code for both.

## D-004: Hash-chained audit log with database triggers

**Decision:** The audit log is append-only, enforced by database triggers on both SQLite
and PostgreSQL. Each event is hash-chained to the previous one.

**Rationale:** An audit log that can be modified is not an audit log. Database triggers
provide defense-in-depth — even if the ORM is bypassed, the triggers prevent modification.
The hash chain provides tamper evidence.

**Trade-offs:** The hash chain adds a small overhead per event (one SHA-256 computation).
The triggers make the schema less portable, but both SQLite and PostgreSQL support them.

## D-005: Approval bound to action hash

**Decision:** Approvals are bound to a hash of the action (tool name + parameters + target).
Any change to the plan invalidates the approval.

**Rationale:** Prevents a time-of-check-to-time-of-use (TOCTOU) attack where the plan is
changed between approval and execution. The policy engine re-checks the hash immediately
before execution.

**Trade-offs:** If the plan legitimately needs to change (e.g., the diagnostic agent finds
new information), a new approval is required. This is intentional — it forces the human
approver to review the updated plan.

## D-006: Pydantic `extra="forbid"` on all request models

**Decision:** All API request models use `extra="forbid"` to reject unexpected fields.

**Rationale:** Prevents mass assignment attacks where a client sends additional fields
(e.g., `is_admin=true`) that the server didn't intend to accept.

**Trade-offs:** The API is less forgiving of client errors (extra fields cause 422 instead
of being silently ignored). This is a security feature.

## D-007: sessionStorage instead of cookies

**Decision:** JWTs are stored in `sessionStorage`, not in cookies. The Authorization header
is used for authentication.

**Rationale:** Eliminates CSRF (no cookies to forge). `sessionStorage` is cleared when the
tab closes, limiting token lifetime. CSP headers limit XSS exposure.

**Trade-offs:** The token doesn't persist across tabs or browser restarts. For a demo, this
is acceptable. For production, a refresh token flow with httpOnly cookies would be more
secure.

## D-008: 7-day minimum dependency age

**Decision:** All dependencies (Python and npm) must be at least 7 days old. A script
verifies this in CI.

**Rationale:** Supply chain attacks often target newly published packages. A 7-day delay
gives the community time to detect and yank malicious packages.

**Trade-offs:** Bug fixes and security patches in new versions are delayed by 7 days. For
a demo, this is acceptable. For production, critical security patches should be expedited.

## D-009: Workflow bounds (steps, tools, tokens, timeout)

**Decision:** The LangGraph workflow is bounded by maximum steps, tool calls per step,
token budget, per-step timeout and total timeout.

**Rationale:** Prevents runaway execution (infinite loops, excessive API calls, token
explosion). The bounds are configurable and audited.

**Trade-offs:** Complex investigations might hit the bounds and be interrupted. The
interrupted state is persisted and can be resumed. The bounds are generous enough for
the demo scenarios.

## D-010: Simulated remediation only

**Decision:** All actions are simulated against seeded demo state. There are no real
banking connections, no real transactions, no real money movement.

**Rationale:** This is a portfolio/interview demonstration. Connecting to real banking
systems would be irresponsible and illegal without proper authorization. The simulation
is clearly labeled as synthetic.

**Trade-offs:** The simulation is less realistic than a real integration. But the
architecture (idempotency, CAS, rollback, verification) is production-ready — only the
execution target is simulated.
