---
id: lifecycle-and-recovery
status: observed
sources:
  - bootstrap/lib/factory_lifecycle.py
  - bootstrap/lib/factory_deletion_pipeline.py
  - bootstrap/lib/factory_lifecycle_contract.txt
  - bootstrap/lib/factory_enrollment.py
  - bootstrap/lib/provider_repository_state.py
  - environment_setup/azurefactory-cli/src/azurefactory/factory_deletion.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/operations.py
  - environment_setup/aifactory/bicep/scripts/delete-services-if-disabled.sh
  - environment_setup/aifactory/bicep/scripts/project-deletion.py
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_factory_lifecycle.py
  - environment_setup/unit-tests/test-bicep/unit/test_factory_deletion_pipeline.py
  - environment_setup/unit-tests/test-bicep/unit/test_factory_lifecycle_bootstrap_handoff.py
  - environment_setup/unit-tests/test-bicep/unit/test_selective_project_deletion.py
  - environment_setup/unit-tests/test-bicep/unit/test_factory_deletion_access_hub.py
  - environment_setup/unit-tests/test-bicep/unit/test_bootstrap_teardown.py
  - environment_setup/azurefactory-cli/tests/test_factory_deletion.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_operations.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_deletion_lifecycle.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_deletion_shell.py
  - environment_setup/unit-tests/test-bicep/unit/test_project_deletion_pipelines.py
  - environment_setup/unit-tests/test-bicep/unit/test_resource_closure_parallel_reads.py
  - environment_setup/unit-tests/test-bicep/unit/test_cloud_keepalive_reads.py
  - environment_setup/unit-tests/test-bicep/unit/test_resource_fingerprint_churn.py
graph_symbols:
  - bootstrap/lib/factory_lifecycle.py::function:execute
  - bootstrap/lib/factory_deletion_pipeline.py::function:connectivity_groups
  - bootstrap/lib/factory_lifecycle.py::class:BlobLocks
  - bootstrap/lib/factory_lifecycle.py::class:RepositoryCoordination
  - bootstrap/lib/factory_lifecycle.py::function:collect_resource_closure
  - bootstrap/lib/factory_lifecycle.py::class:ClosureReads
  - bootstrap/lib/factory_lifecycle.py::class:KeepAliveHTTPSHandler
  - bootstrap/lib/factory_lifecycle.py::class:ThrottledReadHandler
  - bootstrap/lib/factory_lifecycle.py::function:fingerprint_body
  - bootstrap/lib/factory_lifecycle.py::function:consent_sources
  - bootstrap/lib/factory_lifecycle.py::function:verify_consent_ancestors
reviewed_source: '01f06fa1 + connectivity-retention port (main's factory-owned hub wins); observed 2026-10-21; throttled reads 4130c8bf, 2026-10-23; volatile-field fingerprints 2026-10-23; consent ancestors 2026-10-24; teardown absent groups 2026-10-25'
---
# Lifecycle and recovery

## Observed execution boundary

`AIFACTORY_LIFECYCLE_CONTRACT=1` freezes exact source, configuration, plan, scope, provider route, revisions and expiry. `capabilities`/`inspect` do not authenticate or deploy. Execution requires a separate clean published source checkout; this vault's dirty-source review is not an executable deployment approval.

Enrollment is separate: plan is cloud/provider read-only; ensure creates explicitly scoped prerequisites under reviewed governance. Publishing the runtime binding is another prepare/confirm operation. Enrollment does not itself create runners, networks or workloads.

Default coordination uses Blob leases and durable claims/receipts. Explicit single-writer mode uses private provider-repository compare-and-swap state, not physical leases or global Azure exclusion. It must never be a fallback from Blob failure. Current `capabilities`, plan validation and cohort execution support whole-owned-group single-writer deletion (`provider-repository-cas-cohort-v1`): every manifest group and resource must be marked delete. Selective/mixed delete-retain plans remain blocked on that path. This generic lifecycle capability does not establish the separately named API's ordered-project-pipelines capability or certify the pinned/published runtime.

## Inventory reads

`collect_resource_closure` builds every review, freeze and verification inventory: resource groups, provider schemas and operations, child collections, resource bodies and extension scopes. It consumes every read in its serial walk order, but `ClosureReads` (a Proxy over the cloud's read calls) starts the reads the walk already knows it will make (queued resource bodies, planned child and extension collections, provider schemas) on at most `RESOURCE_CLOSURE_READ_WORKERS` (8) threads. Each started read is consumed once, and its value or error surfaces where the serial walk makes that call. So the closure, its digests and insertion order, and the failure code (the first failing read in serial order) are those of a serial walk over the same responses. Any failure aborts the walk, and no read continues after it returns. A cloud object without `closure_read_workers` (the offline test fakes) reads serially.

`Cloud`'s default opener adds `KeepAliveHTTPSHandler`: GET/HEAD borrow a pooled TLS connection to their host, one per concurrent reader, and a reused connection the server closed while idle is replaced once. Writes and proxy-tunnelled requests keep urllib's one connection per request with `Connection: close`. One lock makes token refreshes single-flight. An opener injected by a caller (pink's bundled helpers) is used as given, so it must be thread-safe, and the parallel speedup depends on it allowing concurrent requests. Why: on aif-119 (2026-10-20) a common-deployment review made 2,706 serial ARM reads (695 s of 728 s, about 190 s of it TCP and TLS setup) and overran the Factory API's evidence window.

The default opener also adds `ThrottledReadHandler`, a urllib error handler for reads only: a GET or HEAD that ARM answers 429 (throttling) or 503 is sent again after `Retry-After` (seconds; otherwise 5 s, kept within 1 to 60 s), at most `THROTTLED_READ_ATTEMPTS` (8) answers and `READ_TRANSPORT_RETRY_WINDOW_SECONDS` (180 s) after the first throttled answer, each logged as a `remote-request-throttled` event without credentials. Writes and every other status pass through, so `Cloud.request` still sees each final status once and never treats a status as a transport retry. Why: on aif-124 (2026-10-23) the first COMMON run's worker stopped as `reconciliation-required` with `remote-request-failed-429` about 37 s into its pre-write reads, before any Azure write. Pink's dispatched reconciliation (v0.47.33) retires such an attempt.

Resource fingerprints (`resource_digest`, `resource_etag`) hash `fingerprint_body`: the ARM body without the fields the platform or subscription governance rewrites with no write of ours (`VOLATILE_FIELDS`). For a VM that is its etag, embedded `resources` (extensions are closure resources of their own), provisioning state and its view of the OS disk's size and type. For a managed disk it is SKU, tags, disk state, last ownership time, IOPS/MBps and tier. For a NIC it is its etag, `defaultOutboundConnectivityEnabled` and DNS suffix. A Defender for Cloud extension (publisher `Microsoft.Azure.AzureDefenderForServers`) counts only its identity: name, type, location, publisher, extension type and protected VM. VMs and NICs compare no etag. The closure stores collection rows the same way, and the reviewed Defender permit no longer pins the extension's provisioning state. Every other field still counts. Why: after COMMON, every later deploy of a scale set re-checks the preserved runner VM, OS disk, NIC and Defender extension (pink `_registered_resources`). From 2026-10-15 to 2026-10-23 each nightly governance deallocate/start (about 01:47 CEST), the Standard HDD downgrade with removed tags (about 01:55) and Defender's retries of a failed MDE.Linux (aif-124: 04:13 and 15:33) rewrote exactly these fields, so the first night after COMMON would block every later deploy.

## Consents at a later published commit

The two reviewed preserve-only consents in an exact bootstrap foundation (the runner permit, `reviewed-bootstrap-preservation-v1`, and the DNS SOA consent, `reviewed-bootstrap-dns-soa-preservation-v1`) record the commit they were reviewed at. `validate_preservation_permit` and `validate_dns_soa_preservation_permit` accept that commit when it is the manifest's `source.commit` or is declared in `bootstrap_foundation.consent_ancestors` (`consent_sources`: sorted, distinct, lowercase 40-hex commits, never the deploy commit itself, else `consent-ancestors-invalid`). `validate_exact_bootstrap` refuses a declared commit no present consent uses (`consent-ancestors-unused`), and the foundation's own `source_commit` must still equal the deploy commit. `_verify_source` calls `verify_consent_ancestors`, which proves with `git merge-base` in the verified checkout that every declared commit is an ancestor of the deploy commit (`consent-source-not-published-ancestor`), on the published path and on the worker's unpublished re-check alike; the capability `bootstrap_consent_ancestors: published-ancestor-consent-v1` tells the caller this support exists. Everything a consent covers is still re-verified against the fresh closure by the deploy commit's code (`exact_bootstrap_snapshot`, `verify_dns_soa_preservation`, including the run command's script against the deploy commit's `runner-registration.sh`), so a changed instance, fingerprint or record-set inventory still blocks. Why: pink re-selects the moving published tip for every deploy after a registered bootstrap handoff, so before this any push to main between a factory's bootstrap and a later deploy stranded both consents with no supported renewal (aif-125, 2026-10-24, had to freeze main overnight). Pink decides what may be carried (published descendant on the same branch, identical runner scripts) and declares it; see pink's Source-integrity contract.

## Deletion and recovery

- Deletion freezes ownership, complete inventory, dependency closure and retained resources. Exact manifests and fresh permission/inventory checks precede mutation.
- Project deletion and whole-factory deletion have different scopes and retention policies. Group cascading cannot be used to delete an explicitly retained dependency.
- Whole-factory API deletion requires enrolled deletion permission and exact human confirmation; Entra groups and Git history are preserved under the documented contract.
- Partial, interrupted or uncertain results retain durable evidence/claims for reconciliation. Replanning or resubmitting is not a supported way to erase uncertainty.
- A single-writer run that failed after mutation keeps its provider-repository claim (`active`). The only supported release is the reviewed `reconcile-run-claim` operation ([[Reviewed-Operations]]): owner-bound, terminal receipts, completed remote run, nothing else running, one CAS that keeps every record and adds an audit record. Never edit the state ref by hand.
- Agent status observation does not reconfirm or continue jobs. Only the approved paused Full bootstrap supports the specific plan-and-observation-bound continuation.
- Cancelling an unexecuted agent plan does not cancel an already-running underlying job.
- Whole-factory teardown (`ordered-project-pipelines-v1`, `factory_deletion_pipeline.py`) runs every project stage in the configured GHA/ADO pipeline first, then common teardown from the operator. Reusable VPN/hub/connectivity types stay protected, with one reviewed exception (`factory-owned-access-hub-v1`): an integrated access hub and private runner that the factory's own bootstrap created inside its own common group (for a hub-connected factory only its own Bastion Developer or DNS resolver parts, never a VPN gateway, which stays in the shared hub). The catalog proves it from consumed bootstrap stage records only; the runtime gives covered untagged resources the core owner, still blocks shared/protected tags, owner conflicts, site connections and any DNS zone link or VNet peering to a VNet the cohort does not delete, and tears the hub/runner closure down last. The deployment principal may sit only on that covered common runner/identity because it runs project stages only; the operator identity may sit on nothing in scope. A hub-connected factory (`shared-hub-spoke-links-v1`) never owns its shared connectivity hub, but the catalog may prove, from the same records, the hub-side peering and private DNS/ruleset links its bootstrap created there to its own VNet. The runtime freezes only those whose spoke VNet it deletes (unproven links are reported, never deleted), lets the factory side of a recorded peering pair point into the hub, and the operator removes them as the very last step, after the whole common teardown, only while each still targets its now-absent spoke VNet. The hub itself and every other network's links stay.
- A factory that its Full bootstrap created but that was never registered or enrolled has no lease store, route or pipeline, so the ordered pipelines cannot run. `bootstrap-operator-teardown-v1` (`freeze_bootstrap_teardown` / `execute_bootstrap_teardown`) covers it: scopes equal the consumed bootstrap record's groups (including old-region groups a confirmed region replan explicitly retained). Ownership is one resolver for freeze and validation: exact factory tags, the record, a role assignment for a principal the bootstrap recorded, or the nearest owned parent resource (never the resource group). Project resources, unowned, shared or protected resources block. The operator first removes only this factory's own DNS links and both sides of its peerings inside configured connectivity hubs, then deletes in dependency order with groups last. Child resources (NSG rules, subnets, zone links, VM extensions; never extension resources such as role assignments, never peerings) go with their nearest deleted parent, which inherits the child's ordering (a subnet's NSG outlives its VNet). Instead of leases, the exact inventory is verified before the first change and after the last; each delete re-verifies identity, permissions, no active deployment in its group and that the resource keeps its type, location, tags, principal and gains no unreviewed dependency. Its Cloud trusts only ARM and still forbids Entra writes. A failed run keeps evidence and is re-prepared from fresh inventory. A recorded group already deleted outside the teardown (ARM 404 `ResourceGroupNotFound` on its exact id; 403, another 404 code or no body still blocks) is recorded in `absent_resource_groups`, left out of the closure and deployment checks, and re-proven absent before execution (`bootstrap-teardown-absent-group-reappeared` otherwise); its bootstrap-recorded VNets still select this factory's own hub links to unlink.

**Intended rule:** reconcile the observed job, receipt, ownership and inventory before deciding on another reviewed operation. Do not automatically retry uncertain writes, clear claims or perform destructive rollback.

The separate Blob-only `ordered-project-pipelines-v1` factory cohort runs the
reviewed scoped worker for every scale set. All four deletion flags must be actual
boolean true. Capability hosts precede Search
`searchServices/sharedPrivateLinkResources`, services and networking; project
groups require empty reviewed children. Every environment's provider completion,
exact duplicate-free worker receipt and freshly observed ARM absence precede any
common teardown. Final success and completed resume freshly verify every selected
resource/group remains absent, rather than trusting recorded deletion IDs.

Connectivity RGs are retained in full, including all their network, DNS and
supporting resources, even when tagged with the factory's ownership. Exact
`connectivity_resource_group_ids` from resolved configuration/catalog must be
frozen per environment within the locked scope/dependency union. Names containing
`connectivity` (case-insensitive) also identify retention, never ownership, except
a group covered by a valid `factory-owned-access-hub-v1` proof, which stays
deletable; a declared connectivity group inside that proof blocks. Resource types
never mark a group: unproven VPN gateways/sites/connections, local network gateways
and Bastion hosts stay protected resources, as in the factory-owned hub exception
above. Effective group IDs are frozen in the deletion inventory and
rederived on validation. Direct, nested and managed-cascade deletion into these
groups is rejected.

The named API must omit connectivity groups from deletable targets/stages, expose
their exact RG IDs as retained/protected, and require runtime capability
`factory_deletion_connectivity_retention=whole-connectivity-resource-groups-v1`.
The CLI rejects connectivity-named deletion targets and contradictory declared
connectivity retention. An older API may still block preparation instead of
excluding a mixed common/connectivity group; these accelerator/CLI source changes
are not proof of API/MAUI integration or an installed runtime update. Other
protected infrastructure inside a selected whole-group target still blocks
cascading deletion; empty inventories never override protection.

`protected_resource_group_patterns` is an optional hash-bound manifest policy of
case-insensitive RG-name globs. The guard blocks direct/nested deletions and
managed-group cascades. A backend requiring it must freeze its policy on every
manifest and require `factory_deletion_group_protection` capability
`case-insensitive-name-globs-v1`; an older source pin cannot satisfy that check.
The CLI can add a local JSON-array policy via
`AIFACTORY_PROTECTED_RESOURCE_GROUP_PATTERNS` and rechecks saved confirmation
receipts against it. It does not send that local policy to the API or prove the
server/worker enforces it.

An operator session deny policy can be frozen in this manifest field without
changing customer variables or inferring ownership from names. Apply it to every
environment before hashing/review. Frozen matching groups/cascades are rejected
before source/provider execution, and a newly changed managed cascade fails the
fresh exact closure check before provider dispatch.

Consumer lifecycle definitions are generated copies of
`bootstrap/templates/factory-lifecycle-gha.yml` and `factory-lifecycle-ado.yml`,
not accelerator-root deployment workflows. Source capability, consumer workflow
commit/submodule, enrollment, deployment identity, auth namespace and Linux runner
must be independently compatible. Registration is not adoption authority:
untagged older resources need verified durable deployment-ownership evidence,
not inferred factory/project names. Shared DNS links and dependencies require
their own closure/ownership evidence.

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

When the optional `AIFACTORY_PROTECTED_RESOURCE_GROUP_PATTERNS` JSON-array policy
is configured, the legacy shell entry point preflights project and external common
group names plus project managed cascades before its direct service deletions.
Unsupported resource types whose cascades cannot be inspected block this legacy
preflight. This is defense in depth, not authorization to substitute the legacy
shell for the named ordered-pipeline contract.

See [[Reviewed-Operations]], [[State-Machines-and-DAGs]], [[Bootstrap-and-Layouts]], [[Orchestration-and-Updates]], [[IaC-and-Private-Networking]] and [[Index]].

Authority: [lifecycle wire contract](../../../bootstrap/lib/factory_lifecycle_contract.txt), [deletion and review workflows](../../../environment_setup/azurefactory-cli/readme.md).
