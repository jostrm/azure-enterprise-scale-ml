---
id: iac-and-private-networking
status: observed
sources:
  - environment_setup/aifactory/bicep/README.md
  - environment_setup/aifactory/bicep/esml-common/main/12-networkCommon.bicep
  - environment_setup/aifactory/bicep/esml-genai-1/01-foundation.bicep
  - environment_setup/aifactory/bicep/esml-genai-1/31-network.bicep
  - bootstrap/lib/common_network_preservation.py
  - bootstrap/lib/aifactory_private_dns.py
  - environment_setup/aifactory/bicep/modules/projectDash01.bicep
  - environment_setup/aifactory/bicep/modules/foundryMetricTiles.bicep
  - environment_setup/aifactory/bicep/modules/myProjectWorkbook.bicep
  - environment_setup/aifactory/bicep/modules/genericProjectWorkbookItems.bicep
  - environment_setup/aifactory/bicep/scripts/deploy-aifactory-dashboard.py
  - environment_setup/aifactory/bicep/scripts/dashboard_usage.py
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_common_network_preservation.py
  - environment_setup/unit-tests/test-bicep/unit/test_subnet_scaling_capacity.py
  - environment_setup/unit-tests/test-bicep/unit/test_private_data_services.py
  - environment_setup/unit-tests/test-bicep/test_aifactory_dashboard.py
  - environment_setup/unit-tests/test-bicep/test_my_project_workbook.py
  - environment_setup/unit-tests/test-bicep/test_generic_project_workbook.py
  - environment_setup/unit-tests/test-bicep/test_dashboard_usage.py
graph_symbols:
  - bootstrap/lib/common_network_preservation.py::function:prepare_common_network
  - bootstrap/lib/common_network_preservation.py::function:execute_common_network
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# IaC and private networking

## Observed

The maintained infrastructure path is Bicep-first, invoked through provider templates. Common networking and project phases are distinct. `esml-genai-1` contains foundation, core, cognitive/search, database, compute, AI/ML, RBAC, Foundry, dashboard and integration templates; flags and orchestration select the actual resources. A numbered filename is not proof that every deployment executes it.

Foundation resolves common/project scopes, private DNS routing and managed identities. `centralDnsZoneByPolicyInHub` changes whether zone creation is local or delegated to central governance; explicit DNS subscription/resource-group parameters can differ from project placement. Private endpoint creation alone does not prove name resolution, connectivity or caller data-plane authorization.

Network addressing must be aligned and nonoverlapping. Shared/own-subscription presets are configuration choices, not commands to create subscriptions. Allocation must respect existing subnets, gateway/DNS reservations and fragmentation; headline project counts are not guarantees.

The opt-in `preserve-v1` common-network profile is add-only, not a blanket networking skip. `common_network_preservation.py` freezes source/compiled ARM, approved address space, native inventories and exact new/retained resource bodies. Revalidation and lease checks precede deployment; post-checks compare native resource snapshots. Retained resources are preserved without reconciliation. Unexpected changes retain failure evidence rather than triggering destructive rollback.

Dashboard source update (2026-10-08): `projectDash01.bicep` uses compact four-row RG/cost tiles, conditional second-row Azure ML/Databricks/Data Factory shortcuts, existing Log Analytics navigation, and native daily ActualCost charts (total and by service). Usage/token report links are compact cards above service configuration. Phase 10 and the dashboard-only runner already forward the service flags; added AML naming is forwarded to the shared naming module. The factory dashboard's `resource_shortcuts` discovers these services from each project RG, excludes Foundry Hub/Project kinds from AML selection, and `dashboard_parts` places them on its second shortcut row. Configured flags are not resource-existence evidence; discovered inventory is a point-in-time observation and may be retained on read failure. No live deployment, new telemetry, role or network changes are implied.

`foundryMetricTiles.bicep` is an output-only module so account/project IDs resolved by the naming deployment can be used to generate the six native metric tiles. Each tile contains one or two Sum metrics with a 30-day context, and the project dashboard defaults to 30 days. Account requests/images/content-safety/quota metrics and child-project agent activity/estimated USD use distinct resource IDs and namespaces. The component creates no resources; preview metric availability is not guaranteed by the template. Estimated USD is not ActualCost, non-OpenAI BlockedCalls is not content-filter blocking, and Ratelimit is a limit-value sum, not throttled requests. The monitoring guide records the native metric references and interpretation boundaries.

The My Project workbook source now defaults to a generic project view: `genericProjectWorkbookItems.bicep` outputs native account usage, RG inventory and Azure Cost Management query items, while a separate conditional group retains optional instrumented business scenarios. The generic group has no canonical factory/store/coverage dependency and creates no collectors or service resources. Billing currencies come from the API; an absent-currency USD display fallback must not invent an amount or convert reported currency. Read-only Portal observation confirmed that workbook `durationMs: 0` serializes to a zero-second Logs request, not "Set in query"; removing it restores matching request-log observations. Token log items bind their transport window to the token time parameter, and business predicates continue owning local dates/history. Native cache metrics and logged cached tokens remain distinct evidence planes. These follow-up workbook changes are not established as deployed by the earlier dashboard-only rollout.

The shared-dashboard activity extension adds a timestamped aggregate snapshot beside each accumulated-cost tile. Its six measures deliberately separate email-caller management events and completed ADF runs over 30 days from current Foundry/AML/Search inventory and latest storage capacity. Native dashboard reload does not rerun the Python collector; a dashboard pipeline refresh is required. Reads cover every applicable resource in the exact RG and must not silently turn access, network, schema or paging failures into zero. Counts do not establish manual human interaction or business value; inventories do not establish runtime traffic. Data-plane access for Foundry/Search is independent of ARM access and is not provisioned by this change. The dashboard-only command boundary must allow only the collector's bounded read shapes while retaining its existing dashboard/workbook-only write contract. This source work is not proof of deployment.

## Intended constraints

The resource maps are inventory-only: blue circles and the title "Number of resources by region" separate counts from health. The common dashboard uses the native PinnedNotebookQueryPart with a parameter-free live ARG query restricted to exact retained factory RG IDs, placed immediately right of the connectivity RG. Cost/activity and multi-hub layout remain nonoverlapping. The project workbook provides a region-filtered resource table with Azure resource links. Separate health details combine independently queried Resource Graph Resource Health and subscription Service Health evidence through escaped query-backed parameters; a direct join of both health tables is unsupported. Regional advisories have clickable Azure details but are not proof of project impact or regional outage. Capacity can only be flagged when the health service reports it, not as a capacity or quota guarantee. Missing health coverage remains unknown and never changes inventory-map colors.

Regional service-endpoint support, Foundry/agent availability, DNS, egress and RBAC are separate preflights. Unsupported region/service combinations must block, not silently drop endpoints or enable public access. A fingerprint proves byte identity, not publication or operator approval.

See [[Bootstrap-and-Layouts]], [[Identity-and-Personas]], [[Lifecycle-and-Recovery]], [[Factory-Scope-Model]] and [[Index]].

Authority: [Bicep preservation contract](../../../environment_setup/aifactory/bicep/README.md), [private DNS design](../../v2/10-19/14-networking-privateDNS.md), [network orchestrators](../../gh-io/docs/orchestrators/gh.md).
