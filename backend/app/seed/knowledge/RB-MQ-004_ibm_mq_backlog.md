# IBM MQ Queue Backlog Response

> SYNTHETIC DEMO DATA - fictional runbook. Queue managers, channels and volumes are invented.

## Scope

Queue manager QM_PAY01 hosts PAYMENT.SETTLEMENT.IN (max depth 50,000) and its dead letter queue
PAYMENT.SETTLEMENT.DLQ. The mq-settlement-consumer reads settlement messages over channel SETTLEMENT.SVRCONN and posts
them to the core-ledger.

## Symptoms

- Queue depth growing toward max depth; oldest message age increasing.
- open_input_count is 0, meaning no consumer has the queue open.
- Consumer logs show MQRC_CONNECTION_BROKEN (2009) and the channel state is STOPPED.

## Diagnosis

1. Inspect queue metrics: depth, max depth, open input count and oldest message age.
2. If open_input_count is 0, the consumer is not connected - check the consumer channel state and last error.
3. If the consumer is connected but depth still grows, check core-ledger commit latency for slow commits.
4. Check the head of the queue for poison messages before restarting.

## Remediation

- Consumer unavailable: restart the mq-settlement-consumer channel. This is a medium-risk change requiring operations
  manager approval. Messages remain safely queued during the restart.
- Queue approaching max depth: prioritize consumer recovery; never delete or purge settlement messages.
- Dead letter queue: review DLQ messages separately. Replaying DLQ messages is high risk and needs explicit approval.

## Verification

- Consumer connected (open_input_count at least 1) and channel RUNNING.
- Queue depth draining below 5,000 and oldest message age below 5 minutes.
