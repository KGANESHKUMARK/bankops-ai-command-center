# Fabrikam Card Settlement File Runbook

> SYNTHETIC DEMO DATA - fictional runbook belonging to tenant Fabrikam Community Bank (fictional). It must never be
> retrievable by users of any other tenant.

## Symptoms

The nightly card settlement file is not delivered to the settlement-file-gateway before 04:00 UTC.

## Response

1. Check the card-settlement-batch job status and the settlement-file-gateway health.
2. If the gateway is down, fail over to the secondary gateway through change management.
3. Notify the Fabrikam settlement desk of the expected delay.
