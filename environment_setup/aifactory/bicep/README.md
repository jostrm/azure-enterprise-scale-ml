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

## AI Search provisioning-region recovery

`aiSearchFallbackLocationArrayDev` and `aiSearchFallbackLocationArrayStageProd`
both default to `["francecentral","denmarkeast","italynorth","norwayeast","germanywestcentral"]`
in that order, with Germany last: native arrays in JSON, serialized arrays in ADO/GHA.
GHA names are `AI_SEARCH_FALLBACK_LOCATION_ARRAY_DEV` and
`AI_SEARCH_FALLBACK_LOCATION_ARRAY_STAGEPROD`. Test/Stage and Prod use the latter.
Explicit `[]` or blank disables regional fallback; missing runtime fields and
undefined GHA repository variables still resolve to `[]` for historical inputs.
Nonempty lists configure up to five fallback regions: CSV or JSON lists of strings are accepted; region
names are lowercased with spaces removed. Malformed JSON, non-string entries,
empty entries, duplicates and unresolved macros are rejected before deployment.

The primary is `aiSearchLocation`, otherwise project `location`. A primary
repeated in the fallback list is omitted from subsequent attempts. Each region
tries the selected SKU first, then remaining configured SKUs when
`aisearchRetryCapcityArray` is enabled. That historical switch controls SKU
changes only: a nonempty region array independently opts into regional recovery.
The ordinary primary provisioning task and its two conditional SKU-retry tasks
always run first, with at most three primary attempts. Only their qualifying
capacity exhaustion can arm the separate regional task. That task tries **only**
the configured fallback array, in its exact order (for example Denmark then
Italy when configured that way); it never prepends or retries the primary.
There are at most five fallback regions by three SKUs (15 regional attempts),
18 attempts in total, with the existing 240-second retry delay.
A local normalization step publishes
`AIF_AISEARCH_REGION_FALLBACK_ENABLED` for the current environment. `[]` or blank
skips the separate ADO/GHA `63b-ai-search-region-fallback` task entirely and
retains ordinary Search provisioning/networking and the existing three SKU
steps. A nonempty list alone does not run the regional task: primary success
skips it, as do lists containing only the primary region. Terminal or mixed
errors fail immediately rather than arming any retry.

`AIF_AISEARCH_CAPACITY_NEXT=primary-capacity-exhausted` is an explicit pending
state, not provisioned/ready success. It is published only after qualifying
primary capacity failure and a fresh exact-resource read proving absence.
`AIF_AISEARCH_PRIMARY_CONTEXT` binds the pending state to the resolved resource
ID, primary region, environment, deployment, CI run/job, SKU policy and ordered
effective fallback list. The regional command requires both that state and a
matching context; stale/manual invocations, changed names and existing services
are refused. The gate step clears prior-run state. The regional task rechecks
absence before and after its retry delay, and after each capacity failure.
Upgrade copied ADO/GHA task templates together with the runner: older mutually
exclusive regional-task templates do not implement this split-task state contract.

The runner first resolves the exact resource ID through the shared Bicep naming
and context modules using `capacityIdentityOnly` (deployment metadata and
output-only modules; no Search/network resource writes), then reads that named
Search service. Only an explicit resource-not-found response establishes absence;
read denials and unknown responses fail closed. Existing services keep their
actual region, including reruns after fallback lists are cleared.
Region pinning does not freeze the SKU: explicit scalar SKU updates and configured
SKU retry policy still apply within that existing region. Partial failed
creation can bind the name to a region: the runner stops before moving it, never
deletes resources, and directs operators to inspect the failed deployment.
Nested `InsufficientResourcesAvailable` is capacity; mixed, authorization,
policy, template, quota and unknown errors are terminal. Private endpoint/shared
link failures must not trigger Search relocation.
When CLI output contains a known `ResourceDeploymentFailure` wrapper without its
actual leaf error, the runner can read `properties.error` from that wrapper's
explicit group deployment target, only in the exact Search subscription/RG.
Readback is read-only and bounded to five nested levels and ten total reads;
missing targets, cycles, denied/malformed responses, mixed errors and non-Search
targets fail closed. A capacity hint in a wrapper message alone is not proof.

Only the Search service region changes. Subscription deployment `--location`,
RG/naming, project VNet, inbound private endpoint, DNS governance, shared-link
target IDs and target `resourceRegion` remain unchanged. The service **and**
required private-network deployment must succeed before publishing effective
`aiSearchLocation` and the environment's SKU through ADO/GHA state. Source
configuration is never rewritten; terminal failure/exhaustion blocks downstream.
Private Foundry's automatic Search dependency uses the same runner and gates.

Preflight validates the configured region/SKU sequence and regional Search
provider support and quota. Non-Search checks remain in the project region.
Quota headroom is not live allocation capacity; existing mandatory quota,
strict/warn-only and explicit lookup/regional skips remain in force. V1 reports
are grouped by actual observation region with distinct alternate-region files,
so the same SKU in different regions cannot overwrite or misattribute evidence.

Review the new-template defaults for residency, latency, egress and cost before
provisioning: newly created Search indexes/data reside in the selected effective
region. This is provisioning recovery, not runtime failover, index migration or
replication. Shared links still require target-side approval and the existing
managed identity/RBAC; regional fallback never enables public access.
Denmark East is intentionally retained despite its omission from the Microsoft
AI Search region list because the portal allows it; Germany remains last with
its known capacity warning. These defaults do not guarantee availability.

> [!TIP]
>  A quicker & easier way? You can use the AIFactory Github Template repository to get a bootstrappd repo quickly (as a mirror repo, or "bring your own repo"). [AIFactory Template Repo](https://github.com/jostrm/azure-enterprise-scale-ml-usage), ready to run. All files copied already. Just configure and run.
>

## TODO: project-creation Search RBAC and regional parity

**Deferred implementation backlog, observed during the split-table agent demo
on 2026-10-16.** A regional or additional project Search service (for example,
a separate France Central service) must receive the **same correct
persona-scoped authorization and connectivity contract as the primary Search
creation task**. Moving regions or adding a named instance must not skip RBAC.
This list does not change IaC defaults or authorize new grants.

- [ ] **One effective Search target through every phase.** Carry the actual
  subscription, resource group, service ID and managed-identity principal from
  primary/regional/additional-service creation into all RBAC, Foundry connection,
  Storage and private-link steps. Do not recompute the original service name.
  Entry points: `esml-genai-1/03b-ai-search.bicep`,
  `modules/services/aiSearchDeployment.bicep`, and
  `scripts/deploy-capacity-resource.py`.
- [ ] **User/group and runtime Search roles at project creation.** Invoke the
  shared assignment contract for every selected Search instance, including
  regional services. Approved readers need Search Index Data Reader; management
  Owner/Contributor does not grant document reads. Preserve the intended
  user/group versus service-principal types and persona distinctions rather than
  copying all legacy contributor grants onto every reader. Entry points:
  `esml-genai-1/08-rbac-security.bicep`,
  `modules/aiSearchRbacUsers.bicep`,
  `modules/csFoundry/rbacAISearchForAIFv2.bicep`.
- [ ] **Search identity to model and source permissions.** Assign the newly
  resolved Search identity its scoped Cognitive Services OpenAI User role on the
  selected Foundry resource and the reviewed Storage reader contract on the
  selected project/common source. Native ADLS permission ingestion needs exact
  root/ancestor permission-metadata access as well as source-file reads and
  bounded listings. Do not fix this with unconditional common-lake access.
  Entry points: `modules/csFoundry/rbacAISearchOpenAIUserOnFoundry.bicep`,
  `esml-genai-1/08b-rbac-common-rg.bicep`; conditional-reader prior art:
  `../../../usecase_code/40-agent-factory/agent_factory/rag_materialization.py`.
- [ ] **Readiness/status access for the retrieval backend.** Include
  `Microsoft.Search/searchServices/indexers/read` through the approved read-only
  role or existing Reader inheritance, in addition to Search Index Data Reader.
  Do not give a read-only runtime Search Service Contributor merely to poll
  status. Confirm real effective access after propagation.
- [ ] **Private connectivity parity, including common ADLS.** Derive inbound
  endpoint/subnet/central-DNS configuration and outbound `blob`, `dfs` and
  applicable Foundry group IDs from the effective service/source bindings.
  Approve only the proven matching target connections. Check distinct
  private-link group-type limits before writes; preserve existing services and
  never silently upgrade/delete them to make space.
  Entry points: `modules/aiSearch.bicep`,
  `modules/services/aiSearchDeployment.bicep`, and
  `modules/aiSearchSharedPrivateLinkFoundry.bicep`.
- [ ] **Provisioning completion and recoverable cleanup.** Await the actual
  terminal Network/Search operation and verify private DNS plus authenticated
  data-plane access before reporting project readiness. Separate an operational
  replacement from cleanup of an owned failed endpoint; preserve unrelated
  endpoints/NICs. Record request IDs and bounded retry/recovery state.
- [ ] **Parity regressions and acceptance.** Exercise primary success, regional
  capacity recovery, additional-service creation and idempotent reruns with the
  same approved persona matrix. Assert effective resource IDs on every
  assignment, private-link target and Foundry binding; verify reader access and
  expected denial without account-wide test-user data grants. Include a
  post-creation smoke test so a missing role is found before an agent demo.

Search semantic/agentic feature availability remains a separate region
compatibility gate. Graph security-webhook consent/hosting and source-specific
permission mappings are explicit opt-in integrations, not blanket permissions
to add to every project.

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

### Regional service-endpoint preflight

Before approving a network plan, use the same authenticated Cloud adapter for:

```python
capabilities = collect_service_endpoint_capabilities(
    cloud, subscription_id=workload_subscription_id, location=network_location)
readiness = validate_common_network_region(desired, capabilities)
prepared = prepare_common_network(
    source_root=source_root, desired=desired, inventory=inventory,
    regional_capabilities=capabilities)
```

The collector reads only
`GET /subscriptions/{subscription}/providers/Microsoft.Network/locations/{location}/virtualNetworkAvailableEndpointServices?api-version=2023-11-01`.
It returns `subscription_id`, `location`, `api_version`, `source` and `services`.
The validator binds that evidence to the exact target VNet subscription and
location, and checks **all** configured common/scoring endpoints. It returns
`can_execute`, `blockers`, `required_services` and `capabilities`. Each unavailable
service produces a `regional-service-endpoint-not-supported` blocker including
the service, subscription, location and actionable message. Storage.Global is
not an implicit replacement for Storage. No region names are hardcoded.

Preparation accepts the optional `regional_capabilities` argument to expose
blockers **before approval**; it checks only newly planned subnets, not retained
ones. Omitting it preserves the existing call signature, but the returned
`regional_service_endpoints: null` means **regional readiness has not yet been
checked**, not that the region is supported. Execution always repeats the live
capability GET before its first subscription deployment PUT, including before
any NSG creation. Unsupported services raise `RegionalServiceEndpointError`
with structured `.preflight` evidence. Denied/failed/malformed/incomplete reads
fail closed; a paginated response is rejected rather than treated as complete.
A no-mutation replay needs no endpoint capability query and never reconciles
existing subnets. Source fingerprints must be refreshed for this helper change;
compiled ARM shapes and planned writable resource bodies are unchanged.

Manual/public setup flows which invoke Bicep directly must perform the same
read-only regional check before submission; Bicep alone cannot query this
provider capability. For inspection:

```powershell
az network vnet list-endpoint-services --location <network-location> --subscription <workload-subscription> --output json
```

**Denmark East finding (2026-09-24):** the live Network RP capability response
does not include `Microsoft.CognitiveServices`. Therefore the unchanged native
common template cannot be submitted there. The project `31-network.bicep` also
requests this endpoint on AKS, GenAI, ACA and App Service subnets; removing only
the common endpoint would merely postpone failure. No endpoint is silently
dropped, and no firewall, public-access setting, requested workload or region
is changed by this safeguard.

The endpoint itself is **not universally required for private Foundry agents**:
Microsoft's [private-agent sample VNet](https://github.com/microsoft-foundry/foundry-samples/blob/main/infrastructure/infrastructure-setup-bicep/15-private-network-standard-agent-setup/modules-network-secured/vnet.bicep)
uses a delegated agent subnet and a private-endpoint subnet without service
endpoints. However, [Foundry Agent Service's supported-region table](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/limits-quotas-regions#supported-regions)
does not list Denmark East as of that date, and
[private networking requires the Foundry account and injected VNet to share a region](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/virtual-networks).
Endpoint capability support must not be mistaken for Agent/model availability.
For requested private managed agents in Denmark East, the remaining dependency
is **product regional support**, not permission to weaken networking. Proceed
only after Azure confirms that precise regional workload is supported, or the
user explicitly approves a supported-region/topology or workload change. A
private endpoint does not by itself overcome the agent injection region
requirement. No opt-out parameter is introduced as a purported Full-factory fix.

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

## Logic Apps Standard outbound networking

Enabled private Logic Apps Standard (without BYO ASE v3 or public perimeter mode)
uses a **dedicated `/26`** `snt-prj<projectNumber>-logicapp` subnet in the existing
project VNet and VNet resource group. Project `012` therefore uses
`snt-prj012-logicapp`, not the resource suffix. The normal managed networking
update allocates an aligned free range and delegates only the new subnet to
`Microsoft.Web/serverFarms`. Existing Web App/Function and AKS subnets are not
resized or redelegated. Inbound private endpoints remain on the undelegated
GenAI subnet.

With `BYO_subnets=true`, explicitly set `subnetProjLogicapp`
(`SUBNET_PROJ_LOGICAPP` for GitHub) to an existing dedicated subnet name or full
ARM ID in that same VNet. `<xxx>` and `<network_env>` substitutions are supported;
the default is empty, never a guessed cross-project subnet. It must be `/26` or
larger, delegated only to `Microsoft.Web/serverFarms`, with no private endpoints
or NIC IP configurations. Inventory must be a real subnet collection belonging
to the expected VNet. The exact subnet and, for managed networks, its network
deployment must report `Succeeded`. Read failures, malformed inventories,
wrong-scope responses, unsafe reuse, and missing `logicappSubnetId` deployment
outputs fail closed. For historical
managed deployments, rerun with networking enabled to add/reuse the subnet and
publish the output; do not delete or resize existing subnets.

`logicAppType` defaults to `Standard` when omitted. Disabled Logic Apps,
Consumption, BYO ASE and perimeter mode allocate no Logic App subnet. Simple
Mode currently disables Logic Apps, so its capacity profile is unchanged.
No runtime AKS fallback or automatic subnet deletion is introduced. Concurrent
deployments sharing a VNet still require provider-level serialization.
