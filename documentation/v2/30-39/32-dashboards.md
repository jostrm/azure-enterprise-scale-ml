# Dashboards in the AI Factory

## Dashboard-only Azure DevOps pipeline for v1.24

Use `infra-project-dashboards.yaml` to create or refresh the common AI Factory
dashboard and the selected project's dashboard and My Project usage/cost workbook.
It does not rerun the infrastructure deployment or update other projects'
standalone dashboards.

### Customer setup

1. Update the consumer repository's `azure-enterprise-scale-ml` submodule pin to
   a `release/v1.24` revision containing this backport. Copying the YAML alone
   is insufficient: the runner, isolated templates and workbook assets must be
   present in the checked-out submodule.
2. Copy
   `environment_setup\aifactory\bicep\copy_to_local_settings\azure-devops\esml-yaml-pipelines\esml-infra-project\infra-project-dashboards.yaml`
   beside the consumer's existing `infra-project-genai.yaml`. Retain the
   existing relative `..\variables\variables.yaml` location.
3. Create an ADO pipeline pointing at that copied file and authorize its existing
   environment service connection and selected agent pool.
4. Run `plan` for the intended environment/project, then run `create` or `deploy`
   deliberately.

No changes or new mandatory variables are required in the customer's
`variables.yaml`. The default `configurationSource: variables-yaml` reads an
allowlist of existing non-secret pipeline variables exported by ADO to the job
environment. There is no YAML parser dependency and no generated configuration
file. Configuration, credentials and Azure CLI output are not published as build
artifacts.

Existing YAML settings supply the naming, project number, subscriptions, tenant,
service flags/SKUs and agent routing. The service-connection names are
`dev_service_connection`, `test_service_connection`, and `prod_service_connection`;
runner selection uses `useSelfHostedBuildAgent` and `adminVMBuildAgentPool`.
Stage maps to Azure `test`. The selected subscription always uses its own explicit
selector, never `dev_sub_id` as a fallback for Stage/Prod.

### Manual inputs and behavior

| Input | Default | Meaning |
|---|---|---|
| `environment` | `dev` | Exactly one Dev, Stage/Test or Prod placement |
| `projectNumber` | `001` | Assertion against `project_number_000`, not a renaming operation |
| `configurationSource` | `variables-yaml` | Existing pipeline variables, or `json` for a persistent file |
| `configFile` | `aifactory/variables.json` | Consumer-relative path; used only with JSON source |
| `mode` | `plan` | Read-only preview, create missing assets, or explicitly refresh assets |
| `planOperation` | `create` | Preview `create` or `deploy` without Azure writes |
| `runnerSelection` | `from-config` | Configured agent, explicit Microsoft-hosted, or explicit self-hosted |
| `selfHostedPool` | `Default` | Bootstrap pool for explicit self-hosted selection |
| `serviceConnection` | Empty | Optional existing connection override; must match selected configuration |
| `factory_id`, `scale_set_id` | Empty | Optional exact telemetry identities; never invented from resource names |

`create` checks each exact dashboard/workbook resource independently and skips
existing ones. A missing project dashboard can link an existing workbook without
replacing it; a missing workbook can be created without rewriting the project
dashboard. An existing common dashboard is also untouched, so it will not gain a
new project's navigation tiles until an explicit `deploy` refresh.

The common dashboard uses conditional ARM writes to avoid overwriting a concurrent
creation. Project/workbook creation uses Incremental ARM deployment with per-resource
conditions and repeats existence checks immediately before writing. ARM deployments
are not conditional resource PUTs: coordinate other pipelines/manual writers for
those same project resources during `create`.

`deploy` explicitly creates missing assets and refreshes existing dashboard/workbook
definitions. Existing common-dashboard inventory from other environments/projects
is retained. Dashboard edits made manually in Azure may be replaced by this mode.

### Optional JSON configuration

With `configurationSource: json`, use the project's persistent `variables.json`.
The v1.24 `dev`-only baseline is supported for all environments when it contains the
explicit selected tenant, subscription and connection. If `stage_prod` is present,
it overlays the baseline, and the selected tenant/subscription/connection must be
explicit in that section.

Optional `myProjectApplicationInsightsResourceId` and
`myProjectLogAnalyticsResourceId` override ambiguous telemetry discovery. Optional
`myProjectFactoryId` and `myProjectScaleSetId` identify instrumented business events;
generic native usage/cost views do not require them. No register is required.
JSON mode can resolve matching identities from a schema-version-2 register when one
exists; YAML mode uses only the explicit identity inputs.

### Prerequisites and scope boundaries

Use an agent with Python 3.10+, PowerShell Core and Azure CLI with Bicep preinstalled.
Explicit `runnerSelection: microsoft-hosted` uses `windows-2022` for both jobs,
even if the configured self-hosted agent is offline. This pipeline never starts
or provisions build VMs.

The selected project/common resource groups and the DEV common dashboard host
resource group must already exist. Existing project Application Insights, Log
Analytics and existing project managed-identity naming must be discoverable.
The v1.24 identity resolver preserves supported historical names and naming salts,
including identities retained at `-001` after the service suffix changes to `-002`.
Ambiguous or conflicting identities stop the run rather than selecting a new salt.
The selected service connection must access both the selected project subscription
and the DEV common dashboard host where they differ.

Permissions must already include resource discovery/read, common dashboard
read/write, and selected project dashboard/workbook/deployment write. Native
metrics, billing, Resource Graph and optional usage-snapshot data may require
additional read permissions. Missing data/access is unavailable, not zero.
Some optional usage reads require private-network connectivity; choosing a hosted
agent does not grant that connectivity or enable public access.

Only dashboard/workbook resources and Incremental deployment records may be
written. No resource groups, telemetry infrastructure, diagnostic settings,
identities, RBAC assignments, networking or application services are provisioned.
The new templates live under `modules\dashboard-only` and use a separate
`dashboard-only-shared.py` renderer: normal v1.24 infrastructure entry points and
shared naming safeguards are unchanged.
