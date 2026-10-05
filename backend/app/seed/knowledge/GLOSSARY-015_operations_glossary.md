# Glossary of Synthetic Banking Operations Terms

> SYNTHETIC DEMO DATA - public glossary for a fictional bank.

## Terms

- Consumer lag: the number of records a consumer group has not yet processed.
- Dead letter queue (DLQ): a queue holding messages that could not be processed after retries.
- Schema registry: a service storing versioned record schemas and compatibility rules.
- Store-and-forward: holding payments safely until a dependency recovers instead of processing them unscored.
- CAB: change advisory board that approves production changes.
- Freshness lag: minutes between an event occurring and its availability in the warehouse.
- Idempotency key: a unique key that lets a system detect and discard duplicate requests.
