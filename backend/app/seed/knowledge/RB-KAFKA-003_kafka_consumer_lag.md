# Kafka Consumer Lag Troubleshooting

> SYNTHETIC DEMO DATA - fictional runbook for the card-transactions streaming platform.

## Overview

The transaction-enricher consumes the card-transactions topic (12 partitions) in consumer group
cg-transaction-enricher, enriches each record with a customer-profile-cache lookup and publishes enriched events.
Records that fail enrichment after retries are moved to the dead letter queue card-transactions.dlq.

## Symptoms of Consumer Lag

- Consumer lag growing continuously; throughput below the ingest rate.
- Processing time per message (processing_ms_p99) far above its baseline.
- Downstream fraud features become stale.

## Diagnosis

1. Compare consumer throughput with the topic ingest rate. If throughput is below ingest, lag will grow.
2. Check whether lag is evenly distributed across partitions or concentrated on a hot partition (key skew).
   Evenly distributed lag with slow processing points to a processing bottleneck, not partition skew.
3. Inspect processing time: slow enrichment lookups against customer-profile-cache are the most common bottleneck.
4. Confirm broker health and in-sync replicas; broker problems affect all consumers, not just one group.

## Remediation

- Processing bottleneck: scale the consumer group within the partition count (maximum 12 replicas). Scaling is a
  medium-risk change that requires operations manager approval. Investigate the slow dependency in parallel.
- Partition skew: re-key or add partitions through change management; scaling alone does not help.
- Broker degradation: engage the platform team.

## Dead Letter Queue Replay

Replaying dead-lettered events can cause duplicate processing if the consumer is not idempotent. Treat a replay as a
high-risk action: replay only after lag has recovered, only with idempotent processing confirmed, and only with explicit
approval from an operations manager who did not request it. A replay cannot be undone.

## Verification

- Consumer lag falling and below 100,000 records.
- Throughput above the ingest rate for at least 15 minutes.
- Dead letter queue depth stable or reduced after an approved replay.
