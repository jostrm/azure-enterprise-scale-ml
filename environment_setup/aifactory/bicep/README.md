# BICEP to provision the AIFactory and new projects
This repo is BICEP first. Meaning that Terraform has lower prio. 

You can use either **GITHUB** or **Azure Devops** automation pipelines (that uses BICEP under neath the hood)

You do **not need** to interact with either BICEP or Terraform, since the AIFactory provides automation pipelines.

We recommend to use the GITHUB option, that uses Github actions with workflows, and also is provided as a TEMPLATE Github repository.

The Azure Devops option, provides automation pipelines (option of choosing classic release pipeline, or the new way - YAML build pipeline)

## Alternative: Github Actions
Start with setting up a common AIFactory environment, example, the DEV environment
- [Github Action - readme.md](./copy_to_local_settings/github-actions/readme.md)

## Alternative: Azure Devops
- [Azure Devops - readme.md](./copy_to_local_settings/azure-devops/esml-yaml-pipelines/readme.md)

> [!TIP]
>  A quicker & easier way? You can use the AIFactory Github Template repository to get a bootstrappd repo quickly (as a mirror repo, or "bring your own repo"). [AIFactory Template Repo](https://github.com/jostrm/azure-enterprise-scale-ml-usage), ready to run. All files copied already. Just configure and run.
>

## Reviewed common-network preservation profile

`esml-common\main\12-networkCommon.bicep` retains its **legacy default**.
Modern creation/replay can explicitly select `commonNetworkProfile=preserve-v1`
with the `preservationPlan` produced by
`bootstrap\lib\common_network_preservation.py`. This is an actual add-only
network deployment, not `BYO_subnets=true` or a blanket networking skip. Public
and private resource-access modes use this same network entrypoint.

The coordinator must verify the selected pinned source with
`assert_preservation_capability`, collect the complete live routing domain and
approved reserved/on-premises/VPN ranges, approve the plan, hold the shared hub
lease, and recollect/revalidate immediately before deployment. The capability
compiles real ARM using standalone Bicep (`--no-restore`); its file fingerprint
is not by itself proof that a Git ref has been published. Existing profiles must
not infer the capability from a version name or BYO flags.

The planner accepts `desired` containing `factory_id`, exact `vnet_id`, resolved
common-template `parameters`, `approved_address_prefixes`, prior-receipt
`owned_resource_ids`, and explicitly approved `reused_resource_ids`.
`required_resource_ids(desired)` supplies exact inventory targets.
`collect_inventory` accepts the enrollment Cloud GET adapter and the complete
cross-subscription VNet list; absence must be a real 404, never an RBAC error.
`plan_common_network` returns deployment parameters, the snapshot hash, exact
mutation/owned/retained IDs, and an empty deletion list. Existing-resource policy
is explicitly `preserve-without-reconciliation`: changing retained NSG/subnet
configuration needs a separately approved operation, not a common replay.
`verify_common_network(plan, before=..., after=...,
expected_resources=prepared['expected_resources'])` checks native post-deployment
GET snapshots. Preparation freezes all created writable bodies, including
evaluated NSG rules; identity/status alone is not proof. Existing NSG writable
configuration remains exact; only the precisely planned new subnet reverse
associations and their service-maintained etag may change. New-resource checks
allow only documented defaults/read-only fields. Unexpected changes retain
failure evidence rather than trigger destructive rollback.

The bounded coordinator hooks are `prepare_common_network(source_root=...,
desired=..., inventory=...)` and `execute_common_network(prepared, cloud=...,
source_root=..., inventory_collector=..., assert_lease=...)`. Preparation validates
the compiled ARM parameter schema and exact effective resource scopes/names,
counts and forwarding. It returns `can_execute`, effects, blockers, commands,
source proof, expected resource bodies and frozen plan. Execution uses native ARM through the
injected Cloud adapter, revalidates fresh inventory under the lease, polls the
exact subscription deployment, and verifies native post-deployment snapshots.
It creates no RG/managed identity and authenticates nobody: the coordinator first
creates its canonical RG/identity substrate. Network creation requires no ADLS.
Failure/pending outcomes never trigger automatic deletion.

* An absent parent is created once with its approved address space. There is
  **no parent VNet PUT on reuse**, including with `vnetNameFull_param`.
* Missing canonical common/scoring/Power BI/Bastion subnets are created as
  serialized child resources. Existing subnets and NSGs require explicit reuse
  approval or prior ownership, and are not rewritten. Their full configuration,
  gateway/resolver/PE subnets, DNS server sets and peerings remain intact.
* Existing address-space changes, overlapping live/reserved ranges, stale
  snapshots and unreviewed AI Gateway network extensions require a new reviewed
  operation; they are never silently merged or dropped.
* External hub/VPN resources are retained, not factory-owned. `plan_peerings`
  plans only the exact named source/destination pair, validates a ready hub VPN
  and remote-gateway prerequisites, and requires ownership plus etags to update
  an existing child. It never changes DNS records/links or parent VNets.
* ARM Incremental mode is **not atomic create-only**. Shared governance must
  exclude uncoordinated writers during the revalidation/deployment interval.
  Complete mode and automatic factory-removal deletion of hub/VPN/network
  resources are not supported by this helper.

Offline verification: from `environment_setup\unit-tests\test-bicep`, run
`python -m pytest -q unit\test_common_network_preservation.py`.
Tests interpret compiled ARM against native-resource snapshots for initial
creation, replay and a second factory, checking full retained subnet, DNS and
peering configurations. No live Azure deployment is claimed.

## My Project workbook parameter and empty-series contracts

`modules\myProjectWorkbook.bicep` creates only the existing saved-workbook surface;
it does not collect or ingest telemetry. The Model tokens account list remains
restricted to `AIServices` / `OpenAI` accounts in the exact project RG. One account
auto-selects; zero or multiple accounts retain an explicit empty selection.

The account dropdown supplies a scalar ARM ID, while its hidden inventory query
explicitly serializes the dynamic array with `tostring`. KQL also accepts legacy
JSON strings or singleton arrays, but rejects ambiguous shapes and still validates
inventory membership, resource kind and exact RG. The validated text parameter
supplies Metrics `resourceIds`; its value must match the selected account before
native charts become visible. There is no subscription-wide or first-account
fallback. The source table exposes inventory/selection shapes, scoped account count
and metric-binding agreement for diagnosis.

The three daily business charts use query-backed availability gates. An
all-unavailable/undefined result displays a coverage explanation instead of
sending all-null columns to the time-chart renderer. A partially defined series
retains its null days; measured/reviewed-complete zero remains distinct from null.
No synthetic observations, zero-fill of unavailable values or historical backfill
are introduced.

These are **local corrections, not a deployed or Portal-verified fix**. Compiled
workbook tests cover substituted parameter forms, scope guards and visualization
gates; they do not execute ARG/KQL or emulate the Portal. The September 21 runtime
parameter payload was not available offline, so its precise serialized failure
shape remains unconfirmed. The dashboard-only adapter uses the same module and
needs no additional deployment parameters.

After an explicitly approved publication and dashboard-only rollout, acceptance
must use the saved workbook's own controls (not explicit-parameter standalone
queries): confirm `InventoryShape=array`, a positive `ScopedAccounts`,
`AccountSelected=true`, `MetricAccountMatchesSelection=true` and the exact
nonempty account ID; verify native input/output metrics and independently scoped
request logs for the same token window. Empty/ambiguous/out-of-scope account
selections must fail closed. With unreviewed business coverage, all three daily
panels must display their unavailable explanations without chart-column errors.
Do not enable coverage merely to make a chart appear. Missing cache series/logs
remain unavailable, and native Metrics are never added to request-log totals.