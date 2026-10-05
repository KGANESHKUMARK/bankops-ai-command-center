# Interview Guide

## How to talk about this project

This is a portfolio/interview demonstration of governed AI for banking operations. It is
**not** a real banking system — every bank, customer, account and amount is synthetic.
The value is in the architecture and the security design, not in the data.

### Elevator pitch

> "I built a synthetic banking operations AI command center that demonstrates how an
> LLM-based multi-agent workflow can investigate incidents while remaining deterministic
> at every authorization boundary. The model proposes; a deterministic policy engine
> disposes. Every action is simulated, every decision is audited, and the whole thing
> runs offline without API keys."

## Key talking points

### 1. "The LLM is never the authorization boundary"

The most important design decision. The policy engine is in application code, not in a
prompt. It decides allow/deny/approval-required based on the action, parameters, risk
level and user role — all validated independently of the model. The model can only
propose actions; it cannot authorize them.

**Q: What if the model outputs a prohibited action?**
A: The policy engine rejects it. Prohibited actions (e.g., `delete_customer_record`,
`modify_transaction_amount`) are in a denylist and can never be executed, regardless of
what the model says.

**Q: What if the model is compromised via prompt injection?**
A: Multiple layers: (1) injection patterns are neutralized at ingestion and retrieval,
(2) the system prompt instructs the model to treat all content as data, (3) the policy
engine doesn't parse model output for authorization, (4) tools are typed and allowlisted.
Even if the model is fully compromised, it cannot execute unauthorized actions.

### 2. "Bounded multi-agent orchestration"

The LangGraph workflow has 7 agents and is bounded by step count, tool calls, token budget
and timeouts. When an action requires approval, the workflow pauses (persisted state) and
resumes when the approval is granted.

**Q: Why LangGraph instead of a simple chain?**
A: LangGraph gives us stateful, resumable execution with conditional routing. The
approval pause/resume is a natural fit for a state machine. The bounds prevent runaway
execution.

**Q: What happens when the model provider is unavailable?**
A: The circuit breaker opens and the workflow runs in degraded mode with deterministic
fallbacks. The policy engine, audit log and all authorization checks keep working.

### 3. "Governed RAG with authorization in the query"

Retrieval is authorized **before** ranking, not after. Tenant, classification and role
filters are applied in the query, so unauthorized data never enters the ranking pipeline.

**Q: How do you prevent the model from seeing restricted documents?**
A: The retrieval query includes tenant_id, classification clearance and role filters.
Only authorized chunks are returned. The model never sees unauthorized content.

**Q: What about prompt injection in retrieved documents?**
A: Documents are scanned for instruction-like patterns at ingestion and at retrieval.
Detected patterns are neutralized and flagged. The system prompt instructs the model to
treat all content as data. And critically, the policy engine doesn't parse model output
for authorization — so even if injection succeeds in influencing the model's text, it
can't change what actions are authorized.

### 4. "Human approval with separation of duties"

Medium/high-risk actions require human approval. A requester can never approve their own
high-risk action. Approvals are bound to an action hash (any plan change invalidates
them) and expire after a TTL.

**Q: Why bind approvals to an action hash?**
A: To prevent a TOCTOU attack where the plan is changed between approval and execution.
The policy engine re-checks the hash immediately before execution.

**Q: What about idempotency?**
A: Every action has an idempotency key. Execution uses compare-and-swap (CAS) on the
action status. Duplicate execution is prevented even if the workflow is resumed multiple
times.

### 5. "Append-only audit with hash chain"

Every decision and action is recorded in a hash-chained audit log. UPDATE/DELETE are
blocked by database triggers. The chain can be verified at any time.

**Q: What database triggers?**
A: On SQLite, `BEFORE UPDATE` and `BEFORE DELETE` triggers raise an error. On PostgreSQL,
the same. The ORM also enforces append-only at the application level.

**Q: How does the hash chain work?**
A: Each event stores `SHA-256(prev_hash + canonical_event)`. Tampering with any event
breaks the chain. The verification endpoint walks the chain and reports the first
invalid event.

### 6. "Evaluation as a release gate"

The evaluation harness measures retrieval, citation, safety, injection resistance and
policy compliance on a versioned synthetic dataset. A release gate blocks promotion on
failures.

**Q: The scores are mostly 1.0 — is that real?**
A: They're real measurements, but in MOCK MODE they verify pipeline logic, not model
quality. The mock provider was written alongside the dataset, so the scores test the
retrieval, validation, policy and injection-defense code. To measure a real model, run
the evaluation with a live provider.

## Demo walkthrough (5 minutes)

1. **Overview (30s):** Show the synthetic banner, KPIs, MOCK MODE badge and the measured
   AI-quality panel. Explain that the quality numbers are measured, not assumed.

2. **Scenario A (2m):** Sign in as `ops.analyst`, start the statement outage. Show the
   live timeline, authorized citations, ranked hypotheses and the deterministic policy
   decisions. Point out that the model proposed the restart, but the policy engine
   decided it requires approval.

3. **Approval (1m):** Sign in as `ops.manager`, open the Approval Center, show the policy
   explanation and evidence, approve with explicit confirmation. Emphasize the separation
   of duties — the analyst couldn't approve their own request.

4. **Outcome (1m):** Show the workflow resuming — simulated restart, reprocess,
   verification and the final report with citations.

5. **Governance (30s):** Open the Audit log, verify the hash chain. Show the RBAC matrix
   and the prohibited actions list.

## Questions to expect

**Q: Is this production-ready?**
A: No, and I'm explicit about that. It's a demonstration of the architecture and security
design. The docs list what's not implemented (HSM, mTLS, SIEM, field-level encryption, etc.).

**Q: What would you do differently for production?**
A: Use a managed PostgreSQL with pgvector, a secrets manager, mTLS between services, a WAF,
Prometheus + Grafana, OpenTelemetry, field-level encryption for PII, a formal pentest,
canary deployment and automated rollback.

**Q: Why not use OpenAI assistants or a framework like CrewAI?**
A: I wanted full control over the authorization boundary, the tool validation and the
audit trail. LangGraph gives me the state machine and bounds without hiding the
authorization logic behind a framework abstraction.

**Q: How do you test prompt injection?**
A: The evaluation harness includes injection-resistance test cases. The synthetic
knowledge base includes a dedicated injection-test document (`RB-INJECT-001`) with
various patterns. The injection-resistance metric is part of the release gate.

**Q: What's the hardest part of this project?**
A: Keeping the model out of the authorization loop while still letting it be useful.
The policy engine, tool registry and output validation all need to be independent of
model output, but the workflow still needs to be flexible enough to investigate
arbitrary incidents.
