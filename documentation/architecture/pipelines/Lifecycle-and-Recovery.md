---
id: lifecycle-and-recovery
status: observed
sources:
  - bootstrap/lib/factory_lifecycle.py
  - bootstrap/lib/factory_lifecycle_contract.txt
  - bootstrap/lib/factory_enrollment.py
  - bootstrap/lib/provider_repository_state.py
  - environment_setup/azurefactory-cli/src/azurefactory/factory_deletion.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py
  - environment_setup/aifactory/bicep/scripts/delete-services-if-disabled.sh
  - environment_setup/aifactory/bicep/scripts/project-deletion.py
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_factory_lifecycle.py
  - environment_setup/unit-tests/test-bicep/unit/test_factory_lifecycle_bootstrap_handoff.py
  - environment_setup/unit-tests/test-bicep/unit/test_selective_project_deletion.py
  - environment_setup/azurefactory-cli/tests/test_factory_deletion.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_operations.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_deletion_lifecycle.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_deletion_shell.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_deletion_pipelines.py
graph_symbols:
  - bootstrap/lib/factory_lifecycle.py::function:execute
  - bootstrap/lib/factory_lifecycle.py::class:BlobLocks
  - bootstrap/lib/factory_lifecycle.py::class:RepositoryCoordination
reviewed_source: 'a1acd983 + deletion-hardening working tree; observed 2026-10-07'
---
# Lifecycle and recovery

## Observed execution boundary

`AIFACTORY_LIFECYCLE_CONTRACT=1` freezes exact source, configuration, plan, scope, provider route, revisions and expiry. `capabilities`/`inspect` do not authenticate or deploy. Execution requires a separate clean published source checkout; this vault's dirty-source review is not an executable deployment approval.

Enrollment is separate: plan is cloud/provider read-only; ensure creates explicitly scoped prerequisites under reviewed governance. Publishing the runtime binding is another prepare/confirm operation. Enrollment does not itself create runners, networks or workloads.

Default coordination uses Blob leases and durable claims/receipts. Explicit single-writer mode uses private provider-repository compare-and-swap state, not physical leases or global Azure exclusion. It must never be a fallback from Blob failure. Current `capabilities`, plan validation and cohort execution support whole-owned-group single-writer deletion (`provider-repository-cas-cohort-v1`): every manifest group and resource must be marked delete. Selective/mixed delete-retain plans remain blocked on that path. This generic lifecycle capability does not establish the separately named API's ordered-project-pipelines capability or certify the pinned/published runtime.

## Deletion and recovery

- Deletion freezes ownership, complete inventory, dependency closure and retained resources. Exact manifests and fresh permission/inventory checks precede mutation.
- Project deletion and whole-factory deletion have different scopes and retention policies. Group cascading cannot be used to delete an explicitly retained dependency.
- Whole-factory API deletion requires enrolled deletion permission and exact human confirmation; Entra groups and Git history are preserved under the documented contract.
- Partial, interrupted or uncertain results retain durable evidence/claims for reconciliation. Replanning or resubmitting is not a supported way to erase uncertainty.
- Agent status observation does not reconfirm or continue jobs. Only the approved paused Full bootstrap supports the specific plan-and-observation-bound continuation.
- Cancelling an unexecuted agent plan does not cancel an already-running underlying job.

**Intended rule:** reconcile the observed job, receipt, ownership and inventory before deciding on another reviewed operation. Do not automatically retry uncertain writes, clear claims or perform destructive rollback.

## Legacy project-pipeline deletion

The shared ADO/GHA deletion script is separate from the enrolled lifecycle engine
above. Its explicit flags remain the authorization boundary; this hardening does
not add enrollment permissions or relax the reviewed-operation contract.

The shared `project-deletion.py` helper uses scoped ARM inventory and bounded
resource/group state polling. ML endpoint/workspace cleanup does not depend on the
ML CLI extension. Already-deleting resources are observed without duplicate delete
requests. Full-delete success requires actual resource-group absence plus scoped
network absence; accepted submissions, rollback and failed inspection cannot be
reported as completion. Provider templates retain deletion reports on failed tasks.
GHA passes `AIF_DELETE_PRESERVE_FOUNDATION=true` to preserve its legacy services-only
retention boundary; explicit full-project deletion overrides it. ADO keeps its
existing services-only policy. Confirmed-deletion markers preserve downstream
purge eligibility without treating stale live-existence flags as deletion evidence.
These are source changes, not proof of an updated consumer checkout or deployed run.

See [[Reviewed-Operations]], [[State-Machines-and-DAGs]], [[Bootstrap-and-Layouts]], [[Orchestration-and-Updates]], [[IaC-and-Private-Networking]] and [[Index]].

Authority: [lifecycle wire contract](../../../bootstrap/lib/factory_lifecycle_contract.txt), [deletion and review workflows](../../../environment_setup/azurefactory-cli/readme.md).
