# Statement Generation Pipeline Runbook

> SYNTHETIC DEMO DATA - fictional runbook for Contoso Federal Bank (fictional). Not a real procedure.

## Overview

The retail statement pipeline produces monthly customer e-statements. The statement-scheduler triggers a nightly
batch; the statement-generator assembles statement data and calls the document-renderer to produce PDF output using
templates served by the template-store. A batch is identified by an ID such as STMT-BATCH-YYYYMMDD-A.

## Architecture and Dependencies

- statement-scheduler -> statement-generator (batch trigger)
- statement-generator -> document-renderer (synchronous render API, POST /v2/render)
- statement-generator -> template-store (template lookup)
- document-renderer -> template-store (layout assets)

The statement-generator protects itself with a render client circuit breaker. When the document-renderer is
unavailable the circuit opens and the whole batch fails with reason renderer_unavailable.

## Symptoms

- statement-generator error rate above 50 percent and queue depth growing.
- Render calls fail with 503 Service Unavailable from document-renderer.
- Batch status failed with reason renderer_unavailable; documents_failed equals documents_total.
- Render client circuit breaker OPEN in statement-generator logs.

## Diagnosis

1. Check document-renderer health: instances ready versus total, error rate, heap usage.
2. Review document-renderer logs for OutOfMemoryError, connection pool exhaustion or failing health checks.
3. Validate that the batch template (for example STMT-TPL-RETAIL-2026Q3) is active in the template-store. A valid
   template rules out a missing-template failure.
4. Confirm the upstream account extract arrived on time; if it did, upstream delay is unlikely.

## Remediation

- If the document-renderer is down or has 0 ready instances, perform a rolling restart of the document-renderer
  (see the Document Rendering Service Operations Guide). A restart affects availability and is a medium-risk change
  that requires operations manager approval.
- After the renderer reports all instances ready, reprocess the failed statement batch. Reprocessing is idempotent per
  batch and is a low-risk action.
- Do not replay events or regenerate statements for other batches unless they also failed.

## Verification

- document-renderer healthy with all instances ready and render error rate at zero.
- The failed batch shows status completed and documents_failed equal to zero.
- statement-generator error rate returns to normal and the render client circuit breaker is closed.

## Rollback and Escalation

A restart cannot be rolled back. If the renderer does not recover after one rolling restart, escalate to Document
Services on-call and open a problem record for heap growth analysis.
