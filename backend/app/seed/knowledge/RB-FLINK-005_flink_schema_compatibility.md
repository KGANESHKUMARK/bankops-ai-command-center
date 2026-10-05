# Flink Job Failure and Schema Compatibility Runbook

> SYNTHETIC DEMO DATA - fictional runbook for the real-time risk aggregation job.

## Overview

The flink-risk-aggregator job consumes the risk-events topic and maintains intraday risk aggregates. Records are
serialized with schemas registered in the schema-registry under subject risk-events-value. The job checkpoints state
regularly (for example chk-18842) and reads records with a pinned reader schema version.

## Symptoms of a Schema Mismatch

- SchemaMismatchException or deserialization failures in job logs.
- The job restarts repeatedly until the restart strategy is exhausted and the job state becomes FAILED.
- A producer recently registered a new writer schema version.

## Diagnosis

1. Read the job exception and identify the writer and reader schema versions (for example writer v7, reader v6).
2. Run a schema compatibility check between the writer and reader versions. Field type changes (for example amount
   from decimal to string) are incompatible for existing readers.
3. Confirm the last successful checkpoint so the job can be restored without data loss.
4. Rule out checkpoint timeouts and TaskManager memory issues.

## Controlled Remediation

- Restart the job from its last checkpoint with the reader pinned to the last compatible schema version. Incompatible
  records are routed to a quarantine topic for later reprocessing. This is a high-risk change that requires approval
  from an operations manager other than the requester.
- The producer must publish a backward-compatible schema through change management (CAB).
- Production schema registry settings and compatibility modes must never be changed silently or from incident tooling.

## Verification

- Job state RUNNING with no restarts for 30 minutes.
- Quarantine topic volume tracked; reprocessing scheduled after the producer fix.

## Rollback

Restore the previous job configuration snapshot if the restarted job misbehaves.
