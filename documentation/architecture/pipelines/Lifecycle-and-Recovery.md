---
id: lifecycle-and-recovery
status: observed
sources:
  - bootstrap/lib/factory_lifecycle.py
  - bootstrap/lib/factory_lifecycle_contract.txt
  - bootstrap/lib/factory_deletion_pipeline.py
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
  - environment_setup/unit-tests/test-bicep/unit/test_factory_deletion_pipeline.py
  - environment_setup/unit-tests/test-bicep/unit/test_factory_deletion_access_hub.py
  - environment_setup/unit-tests/test-bicep/unit/test_bootstrap_teardown.py
  - environment_setup/azurefactory-cli/tests/test_factory_deletion.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_operations.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_deletion_lifecycle.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_deletion_shell.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_deletion_pipelines.py
graph_symbols:
  - bootstrap/lib/factory_lifecycle.py::function:execute
  - bootstrap/lib/factory_lifecycle.py::class:BlobLocks
  - bootstrap/lib/factory_lifecycle.py::class:RepositoryCoordination
reviewed_source: '4e2166d9 bootstrap-operator-teardown-v1 parent cascade; observed 2026-10-19'
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
- A single-writer run that failed after mutation keeps its provider-repository claim (`active`). The only supported release is the reviewed `reconcile-run-claim` operation ([[Reviewed-Operations]]): owner-bound, terminal receipts, completed remote run, nothing else running, one CAS that keeps every record and adds an audit record. Never edit the state ref by hand.
- Agent status observation does not reconfirm or continue jobs. Only the approved paused Full bootstrap supports the specific plan-and-observation-bound continuation.
- Cancelling an unexecuted agent plan does not cancel an already-running underlying job.
- Whole-factory teardown (`ordered-project-pipelines-v1`, `factory_deletion_pipeline.py`) runs every project stage in the configured GHA/ADO pipeline first, then common teardown from the operator. Reusable VPN/hub/connectivity types stay protected, with one reviewed exception (`factory-owned-access-hub-v1`): an integrated access hub and private runner that the factory's own bootstrap created inside its own common group. The catalog proves it from consumed bootstrap stage records only; the runtime gives covered untagged resources the core owner, still blocks shared/protected tags, owner conflicts, site connections and any DNS zone link or VNet peering to a VNet the cohort does not delete, and tears the hub/runner closure down last. The deployment principal may sit only on that covered common runner/identity because it runs project stages only; the operator identity may sit on nothing in scope. A hub-connected factory (`shared-hub-spoke-links-v1`) never owns its shared connectivity hub, but the catalog may prove, from the same records, the hub-side peering and private DNS/ruleset links its bootstrap created there to its own VNet. The runtime freezes only those whose spoke VNet it deletes (unproven links are reported, never deleted), lets the factory side of a recorded peering pair point into the hub, and the operator removes them as the very last step, after the whole common teardown, only while each still targets its now-absent spoke VNet. The hub itself and every other network's links stay.
- A factory that its Full bootstrap created but that was never registered or enrolled has no lease store, route or pipeline, so the ordered pipelines cannot run. `bootstrap-operator-teardown-v1` (`freeze_bootstrap_teardown` / `execute_bootstrap_teardown`) covers it: scopes equal the consumed bootstrap record's groups (including old-region groups a confirmed region replan explicitly retained). Ownership is one resolver for freeze and validation: exact factory tags, the record, a role assignment for a principal the bootstrap recorded, or the nearest owned parent resource (never the resource group). Project resources, unowned, shared or protected resources block. The operator first removes only this factory's own DNS links and both sides of its peerings inside configured connectivity hubs, then deletes in dependency order with groups last. Child resources (NSG rules, subnets, zone links, VM extensions; never extension resources such as role assignments, never peerings) go with their nearest deleted parent, which inherits the child's ordering (a subnet's NSG outlives its VNet). Instead of leases, the exact inventory is verified before the first change and after the last; each delete re-verifies identity, permissions, no active deployment in its group and that the resource keeps its type, location, tags, principal and gains no unreviewed dependency. Its Cloud trusts only ARM and still forbids Entra writes. A failed run keeps evidence and is re-prepared from fresh inventory.

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
