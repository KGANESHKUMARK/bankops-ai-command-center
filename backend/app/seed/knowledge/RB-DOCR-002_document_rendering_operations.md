# Document Rendering Service Operations Guide

> SYNTHETIC DEMO DATA - fictional operations guide. All names, hosts and values are invented.

## Service Summary

The document-renderer converts statement data into PDF documents. It runs three instances behind an internal load
balancer and exposes POST /v2/render and a /health endpoint. Each instance keeps a connection pool (max 200) and a
render worker pool backed by the JVM heap.

## Known Failure Modes

### Heap exhaustion

Large statement batches can exhaust the render worker heap. Symptoms: java.lang.OutOfMemoryError in RenderWorkerPool,
heap usage near 100 percent, health checks returning 503, and 0 of 3 instances ready. All render requests then fail
with 503 Service Unavailable.

### Connection pool exhaustion

When downstream callers retry aggressively the connection pool reaches active=200 max=200 and new requests queue.
This usually accompanies heap exhaustion.

### Missing template assets

If a template is missing in the template-store the renderer returns a template error rather than 503; the renderer
itself stays healthy.

## Rolling Restart Procedure

1. Confirm the failure mode from logs and health metrics; capture a heap dump from one instance if possible.
2. Request approval: a restart is a medium-risk availability change and requires operations manager approval.
3. Restart instances one at a time (rolling strategy) and wait for each /health to report ready.
4. Verify all instances ready, render error rate zero and p95 latency back under 500 ms.

A rolling restart cannot be undone. If instances do not return to ready after a restart, stop and escalate.

## Post-Restart Checks

- Confirm the statement-generator render client circuit breaker has closed.
- Reprocess batches that failed during the outage (see the Statement Generation Pipeline Runbook).
- Monitor heap usage for recurrence for 24 hours.
