# Snowflake Ingestion Delay Runbook

> SYNTHETIC DEMO DATA - fictional runbook. Warehouse, pipe and task names are invented.

## Overview

Card settlement files are loaded by the snowpipe-card-settlements pipeline through task LOAD_CARD_SETTLEMENTS into the
analytics warehouse. The data freshness SLA is 30 minutes.

## Symptoms

- Freshness lag above the SLA; finance dashboards show stale settlement data.
- Task state SUSPENDED or repeated failed loads.

## Diagnosis

1. Check the task state. Tasks auto-suspend after repeated failures, for example when the warehouse is unavailable.
2. Check the warehouse state; a transient warehouse outage is a common cause of suspended tasks.
3. Inspect failed load files for parse failures or a changed file format before re-running.

## Remediation

- Task suspended after a transient warehouse outage: resume the task and re-run the failed loads once the warehouse is
  available. Loads are de-duplicated by load key, so re-running is idempotent and low risk.
- File format change: fix the file format mapping through change management before re-running.

## Verification

- Task state STARTED and freshness lag below 30 minutes.
- No new failed loads for two consecutive load cycles.
