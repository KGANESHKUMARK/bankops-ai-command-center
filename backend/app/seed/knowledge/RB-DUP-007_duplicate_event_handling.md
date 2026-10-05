# Duplicate Event Detection and Handling

> SYNTHETIC DEMO DATA - fictional runbook for the payments event stream.

## Overview

The event-dedup-service watches the payments-events stream and quarantines duplicate events to
payments-events.quarantine using event IDs and idempotency keys. The duplicate ratio normally stays below 0.1 percent.

## Common Causes

- Producer retry storms: a producer retries timed-out sends without idempotency keys, emitting the same event twice.
- Consumer replays: an offset reset or rebalance causes consumers to re-read events.
- Dead letter replays performed without idempotent consumers.

## Diagnosis

1. Check the duplicate ratio and quarantine volume.
2. Inspect producer settings: idempotence enabled, retry counts and send timeouts.
3. Check consumer offset history for resets.

## Handling

- Duplicates are quarantined automatically; never delete events or purge topics - the event history is an audit record.
- Fix producer idempotence through a change request, then reconcile quarantined duplicates against the ledger.
- Any replay of events must be treated as high risk because replays can create further duplicates.

## Verification

- Duplicate ratio below 0.1 percent for 24 hours.
- Quarantined duplicates reconciled and signed off by payments operations.
