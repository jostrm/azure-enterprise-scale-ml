---
id: reviewed-operations
status: observed
sources:
  - bootstrap/lib/factory_lifecycle.py
  - environment_setup/azurefactory-cli/src/azurefactory/review.py
  - environment_setup/azurefactory-cli/src/azurefactory/factory_deletion.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/signing.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/actions.py
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_native_foundry_lifecycle.py
  - environment_setup/azurefactory-cli/tests/test_reviews.py
  - environment_setup/azurefactory-cli/tests/test_factory_deletion.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_operations.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_signing.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_actions.py
graph_symbols:
  - bootstrap/lib/factory_lifecycle.py::function:freeze_foundry_identity_stage
  - bootstrap/lib/factory_lifecycle.py::function:verify_foundry_identity_receipt
  - environment_setup/azurefactory-cli/src/azurefactory/review.py::function:write_receipt
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py::class:OperationStore
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py::function:OperationStore.approve
reviewed_source: 'effdb843 + working tree; native identity boundary observed 2026-10-11; other sections reviewed 2026-10-07'
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

## Native identity-only boundary

The local, unpublished native Foundry implementation separates cold identity
production from dependent-resource approval. For the exact supported source shape,
`freeze_foundry_identity_stage` projects only the selected project resource group,
naming and UAMI into a separately reviewed payload. No role assignment or common
resource-group write belongs to that producer.

Its successful receipt has `completion="identity-only"` and
`continuation_required=true`; it is not a completed project. Receipt verification
binds the source/configuration/target/identities/route/locks, producer manifest and
payload, exact UAMI principal/client/tenant GUIDs, complete body and observation
time. Only ownership-linked durable evidence can recover original generated
run/time inputs. The full rebuilt source-step context must still match.

A fresh preparation within the one-hour identity observation boundary rechecks
the exact current UAMI and freezes literal-bound dependent-resource previews.
Their new approval is mandatory; the identity producer approval cannot execute
them. Raw preserved `Ignore` changes cannot become source-declared grants.
Account/network/provider readiness is separately required before full execution;
this does not claim general effective access or SAMI propagation.

Consumers must distinguish verified identity-only completion from whole-project
completion and stop automatic whole-workflow consent at this boundary. Protected
host attestation and current durable-receipt/identity verification, not public
outcome flags alone, govern continuation. Changed, expired or ambiguous evidence
requires reconciliation without automatic renewal, recreation or retry.

These local source contracts do not establish published/installed capabilities
or successful Azure execution.

See [[Factory-API-and-SDK]], [[Lifecycle-and-Recovery]], [[Trust-and-Authorization]], [[Selection-and-Promotion]], [[MCP-Boundary]], [[Chat-and-Grounding]] and [[Index]].

Authority: [review and deletion usage](../../../environment_setup/azurefactory-cli/readme.md), [agent human approvals](../../../usecase_code/40-agent-factory/40-aifactory-agent/readme.md).
