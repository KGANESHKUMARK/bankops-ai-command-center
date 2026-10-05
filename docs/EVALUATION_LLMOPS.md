# Evaluation & LLMOps

## Evaluation harness

The evaluation harness (`backend/app/evaluation/`) measures the quality of the AI pipeline
on a versioned synthetic dataset. It is reproducible and runs entirely offline in MOCK MODE.

### Dataset

- **Versioned:** `bankops-eval-1.0.0` — changes to the dataset create a new version.
- **Synthetic:** All cases are fictional, derived from the seeded incidents and runbooks.
- **Case types:**
  - `retrieval` — measures retrieval recall, precision and MRR
  - `citation` — measures citation coverage and correctness
  - `tool_validation` — measures tool argument validation and selection
  - `injection_resistance` — measures injection neutralization
  - `root_cause` — measures root-cause identification accuracy
  - `abstention` — measures correct abstention when evidence is insufficient
  - `policy_compliance` — measures policy engine decisions
  - `unsupported_claims` — measures the rate of unsupported claims in reports
  - `workflow` — measures workflow completion and failure handling (dry-run mode)

### Metrics

| Metric | Description | Gate |
|---|---|---|
| `retrieval.recall_at_5` | Recall@5 for retrieval cases | ≥ 0.90 (required) |
| `retrieval.mrr` | Mean Reciprocal Rank | ≥ 0.80 (required) |
| `retrieval.unauthorized_leaks` | Unauthorized chunks in results | == 0 (required) |
| `tool.validation_accuracy` | Correct tool + validated args | ≥ 0.95 (required) |
| `injection.resistance` | Injection neutralization rate | ≥ 0.95 (required) |
| `diagnosis.root_cause_accuracy` | Correct root cause | ≥ 0.85 (required) |
| `abstention.accuracy` | Correct abstention | ≥ 0.90 (required) |
| `safety.policy_compliance` | Policy decisions match expected | == 1.0 (required) |
| `citation.coverage` | Claims with citations | ≥ 0.90 (required) |
| `citation.correctness` | Citations that support the claim | ≥ 0.95 (required) |
| `claims.unsupported_rate` | Unsupported claims in reports | ≤ 0.05 (required) |
| `workflow.completion_rate` | Workflows that complete | ≥ 0.95 (required) |
| `workflow.prohibited_executions` | Prohibited actions executed | == 0 (required) |
| `workflow.failure_rate` | Workflows that fail | ≤ 0.05 (warning) |
| `workflow.latency_ms_p95` | p95 workflow latency | ≤ 30000 (warning) |

### Release gate

The release gate blocks promotion if any **required** metric fails. **Warning** metrics
are reported but do not block.

### How to run

```bash
# Via the UI: Evaluations & Releases → Run evaluation
# Via the API:
curl -X POST http://127.0.0.1:8000/evaluations/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"include_workflow": true}'
```

### LLM-as-judge

The harness supports an optional LLM-as-judge mode for metrics that benefit from model
evaluation (e.g., citation correctness). When enabled, the judge model's output is labeled
as "model-assisted" — it is not ground truth. In MOCK MODE, the judge is the deterministic
mock provider, so judge scores are also deterministic.

## Promotion workflow

The promotion workflow simulates moving an AI configuration bundle (prompts + model +
embeddings + retrieval + index + workflow + policy + dataset) between environments.

### Environments

1. **development** — initial promotion target
2. **staging** — requires development to be active first
3. **production_ready** — requires staging to be active first

### Process

1. Run an evaluation. If the gate passes, the bundle hash is eligible for promotion.
2. Promote to development → staging → production_ready (sequential).
3. Each promotion is recorded with the bundle hash, gate failures (if any) and timestamp.
4. Rollback reverts an environment to its previously active bundle.

### What is simulated

- Nothing is actually deployed. The promotion workflow only records the intent.
- A production system would integrate with a CI/CD pipeline, canary deployment and
  automated rollback based on observability signals.

## Observability

The `/observability/summary` endpoint provides LLMOps-style metrics:

| Category | Metrics |
|---|---|
| HTTP | Request count, latency p50/p95/p99, 4xx/5xx counts, error rate |
| Workflow | Runs by status, duration p50/p95, failure rate, degraded runs |
| Agents | Per-agent step count, latency p50/p95/max |
| Tools | Per-tool call count, latency p50/p95/max, error count |
| LLM | Call count, mock vs live, latency, tokens in/out, estimated cost, error codes |
| Retrieval | Query count, latency, sufficiency rate, avg results, errors |
| Policy | Decision count, denials, approvals required |
| Approvals | Pending count, wait time p50/p95 |
| Faults | Active failure-injection flags |

### Trace waterfall

The `/observability/traces/{investigation_id}` endpoint returns a nested span tree for
a specific investigation, showing agent steps, tool calls, model calls and policy decisions
with timing. The UI renders this as a Gantt-style waterfall.

### Cost estimation

Token counts and costs are labeled as estimates. In MOCK MODE, the mock provider reports
deterministic token counts. With a live provider, actual usage is reported. The cost is
calculated using configurable per-token rates.

## What this demo does NOT claim

- The evaluation scores (mostly 1.0 in MOCK MODE) verify pipeline logic, not model quality.
  They are real measurements against a dataset written alongside the mock provider.
- A production system would need a larger, human-reviewed dataset and live model evaluation.
- The promotion workflow is a simulation. No actual deployment occurs.
- The observability metrics are scoped to the current process (in-memory). A production
  system would use Prometheus, Grafana and a distributed tracing backend.
