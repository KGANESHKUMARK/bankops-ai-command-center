# RBAC & Policy Matrix

## Roles

| Role | Description | Clearance |
|---|---|---|
| `demo_admin` | Demo administrator — full access for local demos | restricted |
| `operations_manager` | Approves medium/high-risk actions, manages knowledge and promotions | confidential |
| `operations_analyst` | Starts investigations, runs diagnostics, requests actions | confidential |
| `auditor` | Read-only access to all governance and audit data | confidential |
| `read_only` | Read-only access to operational data | internal |

## Permission matrix

Source of truth: `backend/app/policy/permissions.py`

| Permission | demo_admin | ops_manager | ops_analyst | auditor | read_only |
|---|---|---|---|---|---|
| `dashboard:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `incidents:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `investigations:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `investigations:start` | ✓ | ✓ | ✓ | — | — |
| `investigations:resume` | ✓ | ✓ | ✓ | — | — |
| `diagnostics:run` | ✓ | ✓ | ✓ | — | — |
| `actions:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `actions:request` | ✓ | ✓ | ✓ | — | — |
| `actions:verify` | ✓ | ✓ | ✓ | — | — |
| `actions:rollback` | ✓ | ✓ | — | — | — |
| `approvals:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `approvals:decide` | ✓ | ✓ | — | — | — |
| `approvals:cancel` | ✓ | ✓ | ✓* | — | — |
| `knowledge:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `knowledge:search` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `knowledge:ingest` | ✓ | ✓ | — | — | — |
| `knowledge:manage` | ✓ | ✓ | — | — | — |
| `governance:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `audit:read` | ✓ | ✓ | ✓ | ✓ | — |
| `users:read` | ✓ | ✓ | — | ✓ | — |
| `evaluations:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `evaluations:run` | ✓ | ✓ | — | — | — |
| `promotions:manage` | ✓ | ✓ | — | — | — |
| `retention:manage` | ✓ | — | — | — | — |
| `observability:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `settings:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `demo:reset` | ✓ | — | — | — | — |
| `demo:faults` | ✓ | — | — | — | — |

\* Analysts can cancel their own approval requests, but cannot decide (approve/reject) them.

## Policy rules

Source of truth: `backend/app/policy/engine.py` and `backend/app/policy/catalog.py`

| Rule ID | Description |
|---|---|
| P-001 | Only allowlisted tools with validated parameters may execute. |
| P-002 | Prohibited actions (e.g., `delete_customer_record`, `modify_transaction_amount`) are never executable. |
| P-003 | Medium-risk actions require approval from an operations manager. |
| P-004 | High-risk actions require approval from an operations manager who is not the requester (separation of duties). |
| P-005 | Approvals expire after a configurable TTL (default: 30 minutes). |
| P-006 | The policy engine re-checks approval scope, expiry and action hash before execution. |
| P-007 | Actions are idempotent (CAS-locked on status). Duplicate execution is prevented. |
| P-008 | Tool targets must be in the tool's allowed target list. |
| P-009 | Classification clearance is enforced on knowledge documents and retrieval. |
| P-010 | Tenant isolation is enforced on every tenant-scoped query. |

## Action risk catalog

| Tool | Risk | Approvers | Rollback |
|---|---|---|---|
| `restart_service` | high | ops_manager (not requester) | Yes (state snapshot) |
| `reprocess_batch` | medium | ops_manager | Yes |
| `scale_service` | medium | ops_manager | Yes |
| `clear_cache` | low | — (auto-approved) | No |
| `toggle_feature_flag` | medium | ops_manager | Yes |
| `send_notification` | low | — (auto-approved) | No |
| `quarantine_transaction` | high | ops_manager (not requester) | Yes |

## Prohibited actions

| Tool | Reason |
|---|---|
| `delete_customer_record` | Data deletion is never permitted |
| `modify_transaction_amount` | Direct financial data modification is never permitted |
| `execute_sql` | Arbitrary SQL execution is never permitted |
| `access_external_banking_api` | External banking connections are never permitted |
| `transfer_funds` | Fund transfers are never permitted |
