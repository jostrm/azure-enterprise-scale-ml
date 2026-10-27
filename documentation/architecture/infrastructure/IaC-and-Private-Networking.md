---
id: iac-and-private-networking
status: observed
sources:
  - environment_setup/aifactory/bicep/README.md
  - environment_setup/aifactory/bicep/esml-common/main/12-networkCommon.bicep
  - environment_setup/aifactory/bicep/esml-genai-1/01-foundation.bicep
  - environment_setup/aifactory/bicep/esml-genai-1/02-core-infrastructure.bicep
  - environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml
  - environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml
  - environment_setup/aifactory/bicep/esml-genai-1/31-network.bicep
  - environment_setup/aifactory/bicep/esml-genai-1/11-integration.bicep
  - environment_setup/aifactory/bicep/scripts/subnetCalc_v2.ps1
  - environment_setup/aifactory/bicep/scripts/genDynamicNetworkParamFile.ps1
  - environment_setup/aifactory/bicep/scripts/getProjectSubnetState.ps1
  - environment_setup/aifactory/bicep/scripts/modules/logicAppSubnet.ps1
  - bootstrap/lib/common_network_preservation.py
  - bootstrap/lib/aifactory_private_dns.py
  - environment_setup/aifactory/bicep/modules/projectDash01.bicep
  - environment_setup/aifactory/bicep/modules/foundryMetricTiles.bicep
  - environment_setup/aifactory/bicep/modules/myProjectWorkbook.bicep
  - environment_setup/aifactory/bicep/modules/genericProjectWorkbookItems.bicep
  - environment_setup/aifactory/bicep/scripts/deploy-aifactory-dashboard.py
  - environment_setup/aifactory/bicep/scripts/dashboard_usage.py
  - environment_setup/aifactory/bicep/scripts/deploy-capacity-resource.py
  - environment_setup/aifactory/bicep/scripts/preflight.sh
  - environment_setup/aifactory/bicep/scripts/region_report.py
  - environment_setup/aifactory/bicep/esml-genai-1/03b-ai-search.bicep
  - environment_setup/aifactory/bicep/modules/services/aiSearchDeployment.bicep
  - environment_setup/aifactory/bicep/esml-project/22-main.bicep
  - environment_setup/aifactory/bicep/modules/machineLearning.bicep
  - environment_setup/aifactory/bicep/modules/aksCluster.bicep
  - environment_setup/aifactory/bicep/modules/aiSearch.bicep
  - environment_setup/aifactory/bicep/modules/storageAccount.bicep
  - environment_setup/aifactory/bicep/esml-genai-1/07-ml-data-platform.bicep
  - environment_setup/aifactory/bicep/esml-common/main/13-rgLevel.bicep
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/apim-configuration.bicep
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_aks_outbound_type.py
  - environment_setup/unit-tests/test-bicep/unit/test_shared_acr_update.py
  - environment_setup/unit-tests/test-bicep/unit/test_common_network_preservation.py
  - environment_setup/unit-tests/test-bicep/unit/test_subnet_scaling_capacity.py
  - environment_setup/unit-tests/test-bicep/unit/test_logic_app_subnet.py
  - environment_setup/unit-tests/test-bicep/unit/test_private_data_services.py
  - environment_setup/unit-tests/test-bicep/test_aifactory_dashboard.py
  - environment_setup/unit-tests/test-bicep/test_my_project_workbook.py
  - environment_setup/unit-tests/test-bicep/test_generic_project_workbook.py
  - environment_setup/unit-tests/test-bicep/test_dashboard_usage.py
  - environment_setup/unit-tests/test-bicep/unit/test_capacity_resource_deployment.py
  - environment_setup/unit-tests/test-bicep/unit/test_capacity_preflight.py
  - environment_setup/unit-tests/test-bicep/unit/test_region_reports.py
  - environment_setup/unit-tests/test-bicep/unit/test_defender_service_defaults.py
graph_symbols:
  - bootstrap/lib/common_network_preservation.py::function:prepare_common_network
  - bootstrap/lib/common_network_preservation.py::function:execute_common_network
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# IaC and private networking

## Observed

The maintained infrastructure path is Bicep-first, invoked through provider templates. Common networking and project phases are distinct. `esml-genai-1` contains foundation, core, cognitive/search, database, compute, AI/ML, RBAC, Foundry, dashboard and integration templates; flags and orchestration select the actual resources. A numbered filename is not proof that every deployment executes it.

Foundation resolves common/project scopes, private DNS routing and managed identities. `centralDnsZoneByPolicyInHub` changes whether zone creation is local or delegated to central governance; explicit DNS subscription/resource-group parameters can differ from project placement. Private endpoint creation alone does not prove name resolution, connectivity or caller data-plane authorization.

Shared-registry reuse (source reviewed at `e2e1f55c` plus this change,
2026-10-16): project core infrastructure defaults `updateCommonACR` to true.
With `useCommonACR=true` and `updateCommonACR=false`, it skips only the shared
registry/settings/private-endpoint deployment module, not existing-registry
reads or project access assignments. It does not select a new project registry,
delete resources or bypass network/RBAC prerequisites. JSON/ADO YAML and
GitHub environment registration/runtime expose the same default-true option.
The ADO task passes it as environment data, preserves explicit false through
macro expansion and accepts omitted legacy settings with the prior true
default; invalid values fail before the deployment command. Current main
already forwards `enableApplicationInsights` in both providers. These source
contracts do not prove deployment or an installed API's configuration schema.

Search provisioning recovery (source reviewed at `e33addf7` plus this working tree,
2026-10-16): the Dev and StageProd fallback-location arrays both default in order
to `francecentral`, `denmarkeast`, `italynorth`, `norwayeast`, `germanywestcentral`
(Germany last), with at most five additional regions. Ordinary Search primary
provisioning and its conditional SKU retries always precede the separate regional
task (at most three primary attempts). Only validated primary capacity exhaustion
arms regional fallback, which tries only the configured array in order, excluding
the primary without reordering the others. Regional attempts are region-major,
selected-first SKU combinations (maximum 15 regional, 18 total), while the legacy
SKU switch controls SKU changes only. Local normalization publishes the environment's
`AIF_AISEARCH_REGION_FALLBACK_ENABLED` task gate. Explicit empty/blank and missing
runtime arrays skip the separate regional-fallback task and retain ordinary
Search/private-network provisioning through the three CI SKU steps. Primary success
skips fallback even with a nonempty list; invalid arrays fail before provisioning.
The explicit `primary-capacity-exhausted` pending state is not readiness or
provisioned success, and its context binds exact resource identity, primary region,
environment, deployment, CI run/job, SKU policy and ordered fallback list across
tasks. The regional command rejects missing/stale/mismatched state and any existing
name binding. Main's JSON handoff retains resource IDs across Windows Git Bash
environment conversion. The v1.24 raw resource-ID handoff requires a targeted
`MSYS2_ENV_CONV_EXCL` entry in both provider task scripts before native Python;
otherwise MSYS rewrites `/subscriptions/...` as a local filesystem path.
Existing operator exclusions and all identity/fingerprint guards remain intact.
Real Bash-to-native-Python transport tests cover this boundary, not only in-process
environment dictionaries. Absence is checked after capacity failure and again after the
retry delay; a partial binding blocks relocation without deletion (failed/canceled
primary bindings can retain same-region SKU retries). Exact identity
comes from the same output-only naming/context modules before a direct resource
read; denied reads are not absence, existing services retain actual placement
without freezing the explicitly configured scalar SKU or its retry policy,
and partial name binding prevents relocation without resource deletion. Nested
Search capacity errors alone permit retry; downstream endpoint errors and mixed
terminal errors do not. Leaf-less `ResourceDeploymentFailure` wrappers can be
expanded through read-only group-deployment `properties.error` reads only for
explicit targets in the exact Search subscription/RG (at most five levels and
ten reads). Missing/foreign targets, cycles, malformed/denied reads, unknown or
mixed terminal evidence fail closed; wrapper message hints alone are not proof.
Azure CLI may serialize absent optional `details`/inner-error fields as null.
Both classifiers treat those fields as absent children while still requiring
explicit capacity evidence. Null payloads, malformed non-null children and
mixed terminal errors remain non-retryable; no general continue-on-error policy
is introduced for failed primary provisioning.
The enclosing subscription-deployment error target is accepted only within the
same subscription; it remains a wrapper, not a capacity signal or a readback
target. The underlying Search/group-deployment evidence must still qualify.
Effective location/SKU are CI state, never rewritten
configuration. Service placement is distinct from subscription deployment metadata,
project networking/PE/DNS, and shared-link target placement. Preflight checks
configured Search regions, not project-region aliases; quota evidence remains
distinct from allocation capacity. V1 reports split by observation region rather
than collapsing same-SKU observations across regions. Offline source/tests do not
establish deployed capacity or a supported runtime failover/data-migration path.

Subscription-scope Search resource-ID expressions must include both subscription
and resource-group arguments. Main resolves both from the deployment context.
The v1.24 standalone backport now supplies `subscription().subscriptionId`
explicitly for its Search output and both user-assigned identity IDs; the former
three-argument form misinterpreted the RG as a subscription at ARM evaluation.
Compiled-output regressions cover these scope arguments, not merely Bicep syntax.

The v1.24 service-only boundary passes no VNet/subnet names and must not emit
unconditional existing network resources. Its subnet ID is constructed inside
the private-endpoint resource, gated off for service-only provisioning. The
normal networking call keeps its explicit VNet RG/subnet and PE location; shared
links, approvals and DNS outputs retain their separate service-only gates.

Network addressing must be aligned and nonoverlapping. Shared/own-subscription presets are configuration choices, not commands to create subscriptions. Allocation must respect existing subnets, gateway/DNS reservations and fragmentation; headline project counts are not guarantees.

Logic Apps Standard outbound isolation (main source, 2026-10-16): ordinary
managed networking conditionally allocates a dedicated aligned `/26`
`snt-prj<projectNumber>-logicapp` in the existing VNet/RG, delegates it to
`Microsoft.Web/serverFarms`, and publishes `logicappSubnetId`. Existing subnets
are reused without PUT after exact-scope read-only validation; neither the
Web App/Function `/27` nor AKS is resized or redelegated. Inbound private
endpoints remain on GenAI. Both providers carry the enable/type/ASE/perimeter
gates through allocation, discovery, dynamic parameters and task 68; all
unfiltered phase consumers accept the optional internal ID. Missing historical
outputs require a networking rerun, not silently disabled integration.
BYO requires explicit `subnetProjLogicapp` (name or full ID, project/environment
placeholder substitution) and a validated `/26`-or-larger serverFarms-only
subnet in the configured VNet, separate from other purposes. Denied/malformed
reads, wrong identities, private endpoints and NIC IP configurations block reuse.
Inventory must be a real array/list in the expected VNet; the exact subnet and
managed network deployment must report `Succeeded` before integration.
The allocator independently checks every child's ID against that VNet and its
child name. Main-only CLI/Az regressions retain a valid selected Logic App subnet
while rejecting an ordinary child's missing or wrong-name ID, and accept
case-insensitive exact IDs for both children. No stable-branch equivalence or
customer deployment acceptance is inferred from those offline tests.
Disabled, Consumption, ASE and perimeter cases allocate nothing. Simple Mode
disables Logic Apps and retains its existing capacity profile. These are
offline-tested source contracts, not evidence of a successful live deployment.

Existing-app detection and outbound routing (main source, 2026-10-17): ADO/GHA
detect an existing Logic App by its deployed `lapp-<projectNumber>-<location>-<env>-`
name, resource suffix and hosting type, and fail on denied or ambiguous listings,
so a healthy app is skipped instead of being redeployed onto the new subnet. The
WS1 plan is created only for Standard. VNet-integrated apps set
`outboundVnetRouting.allTraffic` and `vnetRouteAllEnabled`, because default routing
sends only RFC1918 traffic into the VNet and would bypass private endpoints in
other private ranges such as `100.64.0.0/10`. Internet-bound connector traffic then
uses the VNet's egress. These are offline-tested source contracts.

AKS outbound type on the ESML project route (main source, 2026-10-21):
`esml-project/22-main.bicep` and `modules/machineLearning.bicep` allow only
`loadBalancer` and `userDefinedRouting` for `aksOutboundType`. These are the values
that variables.json, variables.yaml, .env.template and the pink wizard document.
`modules/aksCluster.bicep` owns the AKS values. Since c7a9d8d8 its `@allowed` list
rejects `none`, so the stale `none` in both callers stopped 22-main from compiling (BCP036).
The GA AKS API enum also lacks `none`. `none` is not mapped to null: the module default
`loadBalancer` would then apply, which means a public egress IP. AKS `none`
belongs to network-isolated clusters (a private ACR bootstrap profile), which this module
does not configure. `managedNATGateway` needs an AKS-managed VNet, and the ESML route
always brings its own subnet. The GenAI route declares aksCluster's four values in
05-compute-services and 07-ml-data-platform. Its 31-network accepts only `loadBalancer`
and `userDefinedRouting` and runs first, unless BYO_subnets is true or
runNetworkingVar is false. So `scripts/preflight.sh` (`check_aks_networking`) judges
the value itself: `managedNATGateway` and unknown values fail
(`AKS_OUTBOUND_UNSUPPORTED`), and `userAssignedNATGateway` fails without BYO subnets
(`AKS_OUTBOUND_NAT_NEEDS_BYO`). On BYO subnets it warns
(`AKS_OUTBOUND_NAT_UNVERIFIED`), because AKS then needs a NAT gateway on the subnet
and preflight does not look. The Bicep lists stay as they are, so a BYO subnet with
a NAT gateway keeps working. `userDefinedRouting` also needs a route table with a
`0.0.0.0/0` route on the cluster subnet. 31-network attaches its UDR route table only
to `snt-<project>-aks-002`, which the AML AKS in 07 uses. The GenAI cluster in 05
(`enableAKS`) lands on `snt-<project>-aks`, which has no route table. So without BYO
subnets, `enableAKS` with `userDefinedRouting` fails in preflight
(`AKS_UDR_GENAI_SUBNET_NO_ROUTE`). Attaching a route table to that subnet in 31-network
is not done yet. A compile test keeps 22-main building and follows each
value through the compiled ARM to the cluster. This proves the source contract
offline, not a live deployment.

ADO/GHA parameter parity on the GenAI route (2026-10-21): GHA's
`65-compute-services` step did not pass `aksExists`, `aksEnablePrivateCluster`,
`aksOutboundType`, `aksPrivateDNSZone` or `aksSkuName` to `05-compute-services`. So on
GHA the GenAI cluster always got the Bicep defaults: `AKS_OUTBOUND_TYPE=userDefinedRouting`
still produced a public egress load balancer, and the `aksExists` reconciliation never
reached the cluster module, so every run re-PUT the cluster. The step now passes them as
ADO does. The AKS modules in 05 only create clusters (`!aksExists`): an existing
Succeeded cluster keeps its egress, private-cluster and SKU settings, and changing them
means recreating the cluster. GHA's `63-cognitive-services` step also did not pass
`enablePublicNetworkAccessForCognitive` (ADO maps `allowPublicAccessWhenBehindVnet` to it),
so Content Safety, Vision, Speech and Document Intelligence kept public network access on
GHA. Steps 63 and 64 did not pass the CMK seeding Key Vault (`admin_bicep_kv_fw`,
`admin_bicep_kv_fw_rg`, `admin_bicep_input_keyvault_subscription`) either, so `cmk=true`
had no vault there (2026-10-22). Both steps now pass them as ADO does; without CMK the
vault values are unused. Upgrade note for existing GHA factories that enable any of those
four accounts with `enablePublicGenAIAccess=false`: the next infra run re-PUTs them with
public network access disabled (and outbound access restricted) when the effective
`allowPublicAccessWhenBehindVnet` is false, so IP-allow-list access from outside the VNet
stops. To keep public access, set the GitHub variable
`ALLOW_PUBLIC_ACCESS_WHEN_BEHIND_VNET=true` or `allowPublicAccessWhenBehindVnet: "true"`
in variables.json. On the `.env` route, `.env.template` spells the key
`ALLOW_PUBLIC_ACCESS_WHEN_BEHINDVNET`. Until 2026-10-22,
`03a-GH-create-or-update-github-variables.sh` uploaded only
`ALLOW_PUBLIC_ACCESS_WHEN_BEHIND_VNET`, so a `.env` with only the template key fell back to
`false` whatever that key said (bootstrap-written `.env` files carry both spellings and were
not affected). Its `env_spellings` map now fills the upload name from either spelling; the
upload name wins when both are set. Upgrade note: rerunning the upload then publishes the
template key's value, and the template default is `"true"`. A factory that ran effectively
private then gets public endpoints limited to its IP allow list on the next infra run
(AI Foundry and, since 7040e1f6, the four cognitive accounts). To stay private, set
`ALLOW_PUBLIC_ACCESS_WHEN_BEHINDVNET="false"` first. Consumers run their root copy
`10-GH-create-or-update-github-variables.sh`, so after bumping the submodule refresh it
(`bootstrap/03a-GH-bootstrap-files-no-env-overwrite.sh`) before running it.
`unit/test_template_flag_sync.py` checks that every name 03a reads from `.env` comes from
`.env.template` or that map, except the reviewed `PROJECT_IP_WHITELIST`. The same gap hit
least privilege: the workflows read `DISABLE_CONTRIBUTOR_ACCESS_FOR_USERS` and
`DISABLE_RBAC_ADMIN_ON_RG_FOR_USERS`, but `.env.template` and 03a used `..._FORUSERS`. So
on the `.env` route project users kept Contributor and RBAC Admin on the project resource
group even when `.env` disabled them. 03a now also uploads the `FOR_USERS` names, filled
from the `FORUSERS` keys through the map. For these two switches the other spelling may
only tighten access: a `FORUSERS` value fills the upload name only when it is `"true"`, so
the template's `"false"` never overwrites a `"true"` an operator set on the repository by
hand. To loosen access, set the `FOR_USERS` name itself. Setting a switch to `"true"` only
stops creating the user Contributor and RBAC Admin assignments on new runs. Existing
assignments stay until removed by hand: Contributor (or `BYO_CONTRIBUTOR_ROLE_ID`) and
Role Based Access Control Administrator for the `PROJECT_MEMBERS` principals at the project
resource group. The test also works the other way: every `vars.*` name a workflow reads is
uploaded by 03a, read only together with a name 03a uploads
(`DISABLE_WHITELISTING_FOR_BUILT_AGENTS`, `COMMON_SUBNET_NAME`, which the project phase now
also falls back to `SUBNET_COMMON_BASE` for, as infra-common does), or listed with a reason.
One listed name is a known gap: nothing sets `COMMON_LAKE_NAME_PREFIX_MAX8CHARS` on the
`.env` route, so the common lake gets no prefix, while the project phase reads `LAKE_PREFIX`
on every route. A common-side fallback would deploy a second, empty lake under a new name,
so it needs its own decision.
`unit/test_genai_parameter_parity.py` compares the
parameter names each provider passes to every GenAI phase template. Its `KNOWN_GAPS`
lists the remaining reviewed differences, and closing one must remove its entry.

Common subnet without BYO subnets (2026-10-27): the `subnetCommon*` values in
`variables.json` and `variables.yaml` (`snet-dev-esml-cmn-001`, ...) are BYO examples.
The common route ignores them unless `BYO_subnets` is true (`13-rgLevel.bicep`
`defaultSubnet`). 02, 06 and 09 take no `BYO_subnets` parameter and use any non-empty
`subnetCommon`, so the pipelines must clear it. ADO's `job-2-genai-services` already did. The
GHA project job env guarded only the GitHub-variable route. `00_Apply_JSON_Config_Override`
then wrote the JSON examples to `GITHUB_ENV`, and nothing cleared them. So on Simple Mode
(the CLI dispatches the project with `config_file=aifactory/variables.json`, the common
without it), 02 tried to move the common ACR private endpoint to a subnet that does not
exist (`CannotChangeSubnetOnExistingPrivateEndpoint`), and 06/09 referenced it as an existing
subnet. `00_Resolve_Network_Env_Placeholders` now clears `subnetCommon`, `subnetCommonScoring`
and `subnetCommonPowerbiGw` when the effective `BYO_subnets` (after the JSON override) is not
true, next to the existing `subnetProjLogicapp` clear. `unit/test_byo_common_subnet.py`
replays job env, override and that step offline for dev, stage and prod. With
`BYO_subnets=false` the project and common jobs resolve the same `common_subnet_name`, and
BYO values still pass through. A JSON `BYO_subnets` overrides `BYO_SUBNETS`, as every
override does. This proves the source contract, not a live deployment.

Compute deployment ordering (2026-10-16): both optional subnet-delegation modules
finish before Web App/Function integration. Function also depends on Web App,
and the batch Container Apps module (v1.24: environment module) waits for both.
These explicit edges survive omitted/disabled intermediate modules, preventing
the ACA subnet PUT from racing an integration on a sibling subnet in the same
VNet. Compiled ARM conditions and dependency reachability cover new, existing
and disabled services, dedicated/legacy subnets and BYO ASE. The fix changes only
ordering, not subnet selection, delegation, endpoints, DNS, identities or RBAC.
Main's separately orchestrated ACA capacity step retains its existing lifecycle.
This is intra-deployment ordering, not a cross-pipeline VNet lock or proof of a
successful live redeployment.

Logic Apps hosting capacity recovery (2026-10-16): ADO/GHA integration tasks use
`deploy-integration-with-retry.py` for up to three identical deployments with
120-second waits only for exclusively recognized App Service worker exhaustion
on the single `appfarm-logicapp01` plan. Nested stringified Web RP errors and
nullable diagnostic fields retain their actual evidence; other resource targets,
mixed/unknown/policy/quota/auth errors stop. The helper compiles Bicep once,
serializes typed parameters into cleaned-up temporary files for Windows-safe
transport, and rejects changed source parameter files before retry. No new
resource group, region/SKU switch, asynchronous WS1 scaling or readiness bypass
is introduced. Azure capacity remains external and exhaustion still fails.

The opt-in `preserve-v1` common-network profile is add-only, not a blanket networking skip. `common_network_preservation.py` freezes source/compiled ARM, approved address space, native inventories and exact new/retained resource bodies. Revalidation and lease checks precede deployment; post-checks compare native resource snapshots. Retained resources are preserved without reconciliation. Unexpected changes retain failure evidence rather than triggering destructive rollback.

Dashboard source update (2026-10-08): `projectDash01.bicep` uses compact four-row RG/cost tiles, conditional second-row Azure ML/Databricks/Data Factory shortcuts, existing Log Analytics navigation, and native daily ActualCost charts (total and by service). Usage/token report links are compact cards above service configuration. Phase 10 and the dashboard-only runner already forward the service flags; added AML naming is forwarded to the shared naming module. The factory dashboard's `resource_shortcuts` discovers these services from each project RG, excludes Foundry Hub/Project kinds from AML selection, and `dashboard_parts` places them on its second shortcut row. Configured flags are not resource-existence evidence; discovered inventory is a point-in-time observation and may be retained on read failure. No live deployment, new telemetry, role or network changes are implied.

`foundryMetricTiles.bicep` is an output-only module so account/project IDs resolved by the naming deployment can be used to generate the six native metric tiles. Each tile contains one or two Sum metrics with a 30-day context, and the project dashboard defaults to 30 days. Account requests/images/content-safety/quota metrics and child-project agent activity/estimated USD use distinct resource IDs and namespaces. The component creates no resources; preview metric availability is not guaranteed by the template. Estimated USD is not ActualCost, non-OpenAI BlockedCalls is not content-filter blocking, and Ratelimit is a limit-value sum, not throttled requests. The monitoring guide records the native metric references and interpretation boundaries.

The My Project workbook source now defaults to a generic project view: `genericProjectWorkbookItems.bicep` outputs native account usage, RG inventory and Azure Cost Management query items, while a separate conditional group retains optional instrumented business scenarios. The generic group has no canonical factory/store/coverage dependency and creates no collectors or service resources. Billing currencies come from the API; an absent-currency USD display fallback must not invent an amount or convert reported currency. Read-only Portal observation confirmed that workbook `durationMs: 0` serializes to a zero-second Logs request, not "Set in query"; removing it restores matching request-log observations. Token log items bind their transport window to the token time parameter, and business predicates continue owning local dates/history. Native cache metrics and logged cached tokens remain distinct evidence planes. These follow-up workbook changes are not established as deployed by the earlier dashboard-only rollout.

The shared-dashboard activity extension adds a timestamped aggregate snapshot beside each accumulated-cost tile. Its six measures deliberately separate email-caller management events and completed ADF runs over 30 days from current Foundry/AML/Search inventory and latest storage capacity. Native dashboard reload does not rerun the Python collector; a dashboard pipeline refresh is required. Reads cover every applicable resource in the exact RG and must not silently turn access, network, schema or paging failures into zero. Failed refreshes retain valid prior same-RG measurements as explicitly dated last-known values, never as fresh evidence. Their original observation window is retained; successful new reads and confirmed absence supersede them. Known transient read failures use bounded retries, while private-network/auth denials remain explicit safe error codes. Counts do not establish manual human interaction or business value; inventories do not establish runtime traffic. Data-plane access for Foundry/Search is independent of ARM access and is not provisioned by this change. The dashboard-only command boundary must allow only the collector's bounded read shapes while retaining its existing dashboard/workbook-only write contract. This source work is not proof of deployment.

Defender for Cloud defaults (source 3f0711f0 plus this change, 2026-10-23; offline evidence only, not a
Defender scan of a deployed factory):

- Resource logs: the common and common-admin vaults send `AuditEvent` (silver/bronze; gold sends allLogs)
  to the common Log Analytics workspace (`13-rgLevel.bicep`, `keyVaultDiagnostics.bicep`); project vaults
  already did (`02-core`). AI Search and AI Services diagnostics are now on by default:
  `skipDiagAISearch`/`skipDiagAIServices` default false in Bicep and the three variable templates.
  Foundry accounts already had diagnostics. A tenant whose Azure Policy deployIfNotExists already sends
  the same categories to the same workspace gets a 409 on a second setting; set the skip flag there.
  Databricks workspaces (`07`, AVM `diagnosticSettings`) send allLogs.
- AI Search key access: `aiSearch.bicep` sets `disableLocalAuth: true` and drops `authOptions` (ARM
  rejects them together) unless `aiSearchDisableLocalAuth` (`AI_SEARCH_DISABLE_LOCAL_AUTH`) is false. No
  consumer in the repository uses a Search key: the agent knowledge index, Foundry, hub and project
  connections (`authType: 'AAD'`), indexers and ADF (managed identity `ResourceId=`), the ACL RAG demo,
  pipelines (control plane only) and the MCP (no Search calls). Unverified: the external azd notebook
  `create-azure-search.ipynb` that `bootstrap/20-genai-agentic-post-bicep.sh` runs is not in the
  repository. The legacy `foundry-apim` v2 path (`standard-dependent-resources.bicep`, used by
  `09-ai-foundry-2025-v2.bicep`) also creates its Search service Entra-only; its project connections are
  `authType: 'AAD'`. `test_defender_service_defaults.py` fails if any non-debug Bicep file creates a
  Search service without `disableLocalAuth` or with it set to `false`.
- Storage network rules: the private project storage path already uses `defaultAction: 'Deny'`, VNet
  rules, private endpoints and `bypass: 'AzureServices'`, and the common lake is Deny. Only
  `enablePublicAccessWithPerimeter` (true in the shipped templates) opens storage with `Allow`, by design
  of that public-perimeter mode; the recommendation clears when that flag is false.
- Databricks private link: `07` injects the workspace into the VNet by default (premium SKU), and with
  `enablePublicAccessWithPerimeter` false it sets `publicNetworkAccess: 'Disabled'`,
  `NoAzureDatabricksRules` and creates the `databricks_ui_api` and `browser_authentication` private
  endpoints. The template default perimeter=true leaves it public. The legacy `esml-project` path uses the
  deprecated standard SKU, and `databricksPrivate.bicep` hardcodes `requiredNsgRules: 'AllRules'`.
- APIM backends: the AI gateway backends (`apim-configuration.bicep`) authenticate in API policy with
  the APIM system identity (`authentication-managed-identity`, audience cognitiveservices). The ARM
  backend `credentials` contract, through api-version 2025-09-01-preview, has no managed-identity
  member, so the Defender check, which reads `credentials`, cannot see it; a static header would be
  weaker. The APIM identity gets Cognitive Services OpenAI User only when `assignOpenAIUserRole`
  (default false) is set; the MCP backend sends a token only when `mcpEntraAppId` is set.

## Intended constraints

The resource maps are inventory-only: blue circles and the title "Number of resources by region" separate counts from health. The common dashboard uses the native PinnedNotebookQueryPart with a parameter-free live ARG query restricted to exact retained factory RG IDs, placed immediately right of the connectivity RG. Cost/activity and multi-hub layout remain nonoverlapping. The project workbook provides a region-filtered resource table with Azure resource links. Separate health details combine independently queried Resource Graph Resource Health and subscription Service Health evidence through escaped query-backed parameters; a direct join of both health tables is unsupported. Regional advisories have clickable Azure details but are not proof of project impact or regional outage. Capacity can only be flagged when the health service reports it, not as a capacity or quota guarantee. Missing health coverage remains unknown and never changes inventory-map colors.

Regional service-endpoint support, Foundry/agent availability, DNS, egress and RBAC are separate preflights. Unsupported region/service combinations must block, not silently drop endpoints or enable public access. A fingerprint proves byte identity, not publication or operator approval.

See [[Bootstrap-and-Layouts]], [[Identity-and-Personas]], [[Lifecycle-and-Recovery]], [[Factory-Scope-Model]] and [[Index]].

Authority: [Bicep preservation contract](../../../environment_setup/aifactory/bicep/README.md), [private DNS design](../../v2/10-19/14-networking-privateDNS.md), [network orchestrators](../../gh-io/docs/orchestrators/gh.md).
