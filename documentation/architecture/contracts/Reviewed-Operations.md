---
id: reviewed-operations
status: observed
sources:
  - environment_setup/azurefactory-cli/src/azurefactory/review.py
  - environment_setup/azurefactory-cli/src/azurefactory/factory_deletion.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/signing.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/actions.py
tests:
  - environment_setup/azurefactory-cli/tests/test_reviews.py
  - environment_setup/azurefactory-cli/tests/test_factory_deletion.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_operations.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_signing.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_actions.py
graph_symbols:
  - environment_setup/azurefactory-cli/src/azurefactory/review.py::function:write_receipt
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py::class:OperationStore
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py::function:OperationStore.approve
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Reviewed operations

## Observed layers

SDK review receipts bind canonical API URL, purpose, folder, operation/mode, confirmation ID, request/preview hashes and expiry. Validation requires `can_execute: true`, an empty blocker list and consistent scope/revision bindings. Receipt creation refuses overwrite. Hashes detect content changes; possession of a checksum is not human authorization.

Agent `OperationStore` adds caller tenant/object identity, exact configured scope, agent namespace, affected resources and durable signed storage. It re-evaluates current grants and allowed write environments. Its approval TTL is bounded to at most 900 seconds and cannot outlive the underlying preview.

Human approval must reference the exact `plan_hash`. Destructive actions additionally validate their exact confirmation phrase. Approval of a configuration change does not approve infrastructure deployment.

## State and concurrency

The normal path is `pending -> approved -> executing`, then `succeeded`, `running`, `awaiting_continuation`, `failed` or `uncertain`. Expiry and cancellation apply to unexecuted plans. Compare-and-swap plus durable audit precede the non-idempotent callback, preventing straightforward replay after a crash.

Status observation does not execute. Continuation is limited to paused approved Full bootstrap and binds both the plan hash and latest observation hash. The operation reports `retry_allowed: false`; uncertainty is an outcome needing reconciliation, not failure that can be automatically retried.

Signed records and backend validation do not let a retrieved document or model become the approver. A changed source revision, scope, endpoint, record or expired review requires the appropriate fresh review rather than editing a receipt.

See [[Factory-API-and-SDK]], [[Lifecycle-and-Recovery]], [[Trust-and-Authorization]], [[Selection-and-Promotion]], [[MCP-Boundary]], [[Chat-and-Grounding]] and [[Index]].

Authority: [review and deletion usage](../../../environment_setup/azurefactory-cli/readme.md), [agent human approvals](../../../usecase_code/40-agent-factory/40-aifactory-agent/readme.md).
