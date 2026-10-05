# Fraud Operations Escalation Procedures

> SYNTHETIC DEMO DATA - RESTRICTED fictional procedure. Visible only to operations managers, auditors and the demo
> administrator.

## Duplicate Refund Patterns

When fraud rule FR-77 flags duplicate refunds, determine whether duplicates stem from refund-service retries after
ledger timeouts or from coordinated abuse. Retry-driven duplicates show "retrying refund" log entries that correlate
with ledger timeouts.

## Escalation Steps

1. Notify the fraud operations duty lead within 15 minutes.
2. Freeze automated refunds using the fraud-operations console (manual, fraud-ops authority only).
3. Reconcile affected synthetic accounts; reversals require dual control outside incident tooling.
4. File an internal suspicious activity review record (fictional process).

## Prohibited Actions

Incident tooling must never adjust account balances or reverse refunds automatically.
