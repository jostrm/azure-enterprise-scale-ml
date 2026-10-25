---
id: reviewed-operations
status: observed
sources:
  - bootstrap/lib/factory_lifecycle.py
  - environment_setup/azurefactory-cli/src/azurefactory/review.py
  - environment_setup/azurefactory-cli/src/azurefactory/factory_deletion.py
  - environment_setup/azurefactory-cli/src/azurefactory/run_claims.py
  - environment_setup/azurefactory-cli/src/azurefactory/authorization.py
  - bootstrap/lib/provider_repository_state.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/signing.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/actions.py
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_native_foundry_lifecycle.py
  - environment_setup/azurefactory-cli/tests/test_reviews.py
  - environment_setup/azurefactory-cli/tests/test_factory_deletion.py
  - environment_setup/azurefactory-cli/tests/test_run_claims.py
  - environment_setup/azurefactory-cli/tests/test_authorization.py
  - environment_setup/unit-tests/test-bicep/unit/test_single_writer_coordination.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_operations.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_signing.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_actions.py
graph_symbols:
  - bootstrap/lib/factory_lifecycle.py::function:freeze_foundry_identity_stage
  - bootstrap/lib/factory_lifecycle.py::function:verify_foundry_identity_receipt
  - environment_setup/azurefactory-cli/src/azurefactory/review.py::function:write_receipt
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py::class:OperationStore
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py::function:OperationStore.approve
reviewed_source: 'effdb843 + d03bc189 deletion review; f6fa41f5 retained run-claim release 2026-10-19; authorize-deletion client 2026-10-25; native identity boundary observed 2026-10-11; deletion reviewed 2026-10-19'
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

## Retained run-claim release (single-writer)

`RepositoryCoordination.release()` clears the provider-repository claim only after
run and worker success, and `abort()` only before mutation started. A run that
fails after mutation keeps `active` until an operator reviews it. The Factory API's
`reconcile-run-claim` prepare/confirm (azurefactory `reconcile-run-claim`, SDK
`reconcile_run_claim_prepare`/`_confirm`) is the reviewed way out: owner-bound to
the local job that dispatched the run, it requires the claim to name that run,
manifest and lock scopes, terminal run and worker receipts, a completed GHA/ADO run
that is this run's dispatch, no other queued or running workflow run and no active
local job. Confirmation repeats every check, consumes the review, then makes one
non-force `ProviderState` CAS that sets `active` to null, keeps every record and adds
`claim-reconciliations/<run_id>/<confirmation_id>.json`. An uncertain write is
never retried. The service lives in the API (`run_claim_reconciliation.py`); the
helpers are unchanged, and a contract test proves their readers accept the audit
record, reject the released run and let a fresh run acquire.

## Deletion permission (single-writer)

Deletion under single-writer coordination needs the enrollment's `allow_delete=true`;
new enrollments disallow it and no deletion confirmation grants it. The Factory API's
`authorize-deletion` prepare/confirm (azurefactory `authorize-deletion`, SDK
`authorize_deletion_prepare`/`_confirm`, mode `allow` or `revoke`) is the reviewed
way to change it: a `provider-state` review with `azure_writes: false`, the scopes,
enrollment revision and coordination hash before/after, the bindings, and the exact
phrase `ALLOW DELETE <factory key>` or `REVOKE DELETE <factory key>`. Confirmation makes
one CAS and adds `deletion-authorizations/<factory_id>/<confirmation_id>.json`; it is
never retried. The client checks (`authorization.py`) refuse any other review and
report a missing route without fallback. The server is implemented in the API; the
permission alone does not lift the named whole-factory single-writer limitation.

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

Whole-factory deletion reviews bind one of two frozen server plans. The ordered pipeline plan
runs every project pipeline before common teardown. The operator teardown plan exists only for a
never-enrolled bootstrap draft: it is executed by the operator, unlinks only the factory's own hub
links first and replaces leases with fresh identity, inventory and active-deployment checks. Neither
plan authorizes deleting a connectivity hub, and a changed plan, record or scope requires a new review.

These local source contracts do not establish published/installed capabilities
or successful Azure execution.

See [[Factory-API-and-SDK]], [[Lifecycle-and-Recovery]], [[Trust-and-Authorization]], [[Selection-and-Promotion]], [[MCP-Boundary]], [[Chat-and-Grounding]] and [[Index]].

Authority: [review and deletion usage](../../../environment_setup/azurefactory-cli/readme.md), [agent human approvals](../../../usecase_code/40-agent-factory/40-aifactory-agent/readme.md).
