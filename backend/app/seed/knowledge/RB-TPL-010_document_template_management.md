# Document Template Management

> SYNTHETIC DEMO DATA - fictional runbook for the template-store.

## Overview

The template-store holds versioned document templates (for example INV-TPL-QTR-2026Q3 for quarterly investment
statements). Each template records its active version and its last approved version. Generators request templates by
ID at render time.

## Missing Template Symptoms

- Generators log TemplateNotFoundException for a template ID.
- Template validation reports status missing and no active version.
- Batches fail with reason template_not_found while the pdf-composer and renderer remain healthy.

## Diagnosis

1. Validate the template ID in the template-store and read its last approved version.
2. Check the template publication job history; a failed publication can remove an active version.

## Remediation

- Restore the missing template from its last approved version. Never publish an unreviewed draft to fix an incident.
  Restoring a template is a medium-risk change that requires operations manager approval.
- After the template validates as active, reprocess the failed statement batch.

## Rollback

A restored template version can be removed again (simulated rollback) if it causes rendering defects.
