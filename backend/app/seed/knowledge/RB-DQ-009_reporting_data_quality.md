# Reporting Data Quality Validation Failures

> SYNTHETIC DEMO DATA - fictional runbook for the regulatory reporting pipeline.

## Overview

The regulatory-reporting-pipeline publishes the daily positions report after the reporting-dq-validator suite
regulatory-daily-positions passes. Mandatory checks include counterparty_id_not_null and
position_amount_non_negative. A failed mandatory check blocks publication.

## Diagnosis

1. Identify failing checks and failed row counts.
2. Determine whether the failing rows come from the upstream extract (data defect) or from a recent rule change
   (misconfiguration). If the suite configuration is unchanged, the upstream extract is the likely cause.
3. Confirm no downstream report consumed the failing batch.

## Remediation

- Upstream data defect: request a corrected extract from the upstream owner. Re-running validations confirms the
  current state but does not fix the data.
- Rule misconfiguration: revert the rule change through change management.
- Data quality controls must never be bypassed or disabled to meet a deadline; escalate the deadline risk instead.

## Verification

All mandatory checks pass on the corrected extract and the report is published with a data quality attestation.
