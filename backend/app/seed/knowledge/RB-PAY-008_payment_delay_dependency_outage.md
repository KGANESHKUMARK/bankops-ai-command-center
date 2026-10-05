# Payment Processing Delay - Downstream Dependency Outage

> SYNTHETIC DEMO DATA - fictional runbook. The vendor FraudShield-Sim and all volumes are invented.

## Overview

Card-not-present authorizations flow payment-gateway -> payment-router -> fraud-scoring-service (external synthetic
vendor) -> core-ledger. When fraud scoring times out the payment-router opens its fraud client circuit breaker and
holds payments in store-and-forward instead of approving them unscored.

## Symptoms

- Fraud score timeouts in payment-router logs and the fraud client circuit breaker OPEN.
- fraud-scoring-service health failing; vendor endpoint unreachable.
- Store-and-forward depth rising; pending authorizations and latency increasing at the payment-gateway.

## Diagnosis

1. Confirm fraud-scoring-service health and vendor reachability.
2. Confirm the router thread pool is healthy to rule out router saturation.
3. Confirm store-and-forward depth is within its SLA window.

## Response

- There is no automated remediation for a vendor outage. Engage the vendor escalation path and monitor store-and-forward.
- Payments are never executed, replayed or approved unscored by incident tooling; fraud scoring is never bypassed.
- When the vendor recovers, store-and-forward drains automatically.

## Communication

Critical payment delays require updates every 30 minutes per the Incident Communication and Escalation Policy.
