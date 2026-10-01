# AI Factory tutorial: configuration, deployment review, and verification

Use the Windows MAUI app to inspect an existing registered AI Factory, configure
projects, plan a second region, and create a configuration reference. Then use
the CLI/API to discover the same scope and follow a separately approved deployment.

The examples use release **1.25** and the registered **version-2 layout**.
Use matching, supported app/API, CLI, source, and launcher versions. Later releases
can have different capabilities; check the running API's contract rather than
assuming that a newer source checkout updates the installed application.

> **Tutorial Mode is guidance over the real application, not a sandbox.**
> Configuration saves write files. Runtime confirmation can start pipelines and
> change Azure resources. You can complete the configuration exercises without
> deploying; stop at each review unless the exact operation is authorized.

## Learning path

1. [Check prerequisites](#before-opening-the-app) and [choose the configuration root](#choose-the-configuration-root).
2. [Open the app and explore its views](#desktop-walkthrough).
3. [Configure project001 and project003](#phase-1-function-update-and-project-003).
4. [Review and optionally deploy](#review-and-run-a-project-deployment).
5. [Plan a regional factory](#phase-2-dedicated-subscriptions-and-germany).
6. [Create a configuration reference](#phase-3-clone-preview).
7. [Use the CLI/API](#api-and-cli-lab) and [verify outcomes](#deployment-promotion-operations-and-handoff).

This is a standalone written tutorial. No companion recording or slide deck is
required.

<a id="take2-workflow-and-ux-changes"></a>
## Before opening the app

1. Install the [Windows MAUI app](../../../environment_setup/install_config_wizard/maui/readme.md).
   Follow [end-to-end setup](24-end-2-end-setup.md) if you do not yet have a
   consumer repository and registered factory. The configuration exercises need
   a functioning local API; deployment needs additional Azure and provider access.
2. Distinguish the accelerator source repository or submodule from your team's
   consumer repository. Updating source does not migrate configuration, refresh
   every copied launcher, or replace a running bundled API. Preserve existing
   work; this tutorial does not require resetting or cleaning a repository.
3. Select **1.25** explicitly when choosing the release for these examples.
   Check the resolved source ref in every deployment review. Selecting a version
   does not check out that release or upgrade existing resources. `main` is a
   development branch, not a published release.
4. Use the intended app instance's **API connection** page to check connectivity.
   The Windows bundled API normally uses a fresh loopback port and key per launch.
   API health is separate from Azure sign-in, repository access, and deployment
   readiness.
5. Obtain approval for the intended tenant, subscription, resource scopes,
   network changes, service profile, and cost before deployment. Never use sample
   IDs as deployment targets. Keep keys, receipts, full configuration exports,
   and unredacted logs private.

The examples use `C:\work\team-factory\azurefactory` as the registered root and
`C:\work\team-factory\aifactory` as an optional legacy source. Substitute your
actual paths. API file arguments refer to paths **on the API host**, not
automatically to paths on a remote client.

The workflow throughout is **select scope → inspect configuration → prepare
review → separately confirm → verify**. Choose either the UI or CLI to perform
a particular write; do not repeat it merely to try the other interface.

<a id="q1-which-folder-is-authoritative"></a>
## Choose the configuration root

Keep the consumer repository root, which contains pipelines and source, separate
from its configuration root:

| Selected folder | Meaning |
|---|---|
| `aifactory` without `config-wizard\catalog.json` | Legacy configuration; use the legacy load/save workflows. |
| `aifactory` with `config-wizard\catalog.json` | Opt-in catalog-v1 layout; use catalog selectors. |
| `azurefactory` | Registered-layout root, including when empty. Do not fall back to legacy project APIs. |
| `azurefactory\register.json` | Canonical version-2 catalog. Generated projections are not an independent source of truth. |

Open the actual configuration folder, not its repository parent. Catalog `folder`
and legacy `aifactory_folder` arguments select configuration roots; a launcher's
`--repo-root` selects a repository/workspace.

Legacy and registered sibling folders can coexist, but must not become independent
runtime writers against the same Azure targets. Use the registered root for
ongoing work after migration. A malformed register or conflicting same-root
layout is an error, not permission to use another API route. An empty
`azurefactory` without a register is an empty catalog even if legacy-looking
files are present; it is not an implicitly migrated factory.

Legacy API routes reject catalog roots. Shell workspace checks can also detect
a registered sibling or ancestor and require the registered launcher path.
Do not hide, rename, or delete a register to bypass those checks.

<a id="q4-safe-hybrid-validation-and-copy-migration"></a>
## Optional: copy a legacy configuration

Skip this section if your factory is already registered. COPY is a reviewed
configuration conversion, not an Azure migration or a repository/template copy.

1. Load the intended project from the explicit legacy root. For API clients,
   use `POST /api/v1/projects/load` and retain the complete returned `state`,
   source provenance, and any `environment_states`.
2. Validate the **complete** state with `POST /api/v1/validation`. A small object
   such as `{"enableFunction":"true"}` is not a patch for this endpoint and can
   default unrelated settings. Validation does not save or verify Azure access.
3. Check that the source has coherent factory identity, region, subscriptions,
   tenant mappings, environments, and placements. Do not mix a new regional
   identity into the existing source to force migration.
4. Choose a different, non-nested, absent or empty `azurefactory` destination.
   A sibling folder is suitable. Do not initialize `register.json` first:
   even a zero-factory register makes the destination nonempty.
5. In **Factory catalog → Advanced → Copy legacy layout**, supply both source
   and destination. Inspect effects, warnings, blockers, expiry, and the file
   list. An explicit `source_folder` selects COPY; omitting it selects a
   different in-place catalog-v1 registration workflow.
6. Confirm only the approved configuration review, then reload the destination
   and check its identities and placements. Expect `catalog` and `job: null`,
   not a deployment job.

Preparation can create the destination and persist confirmation bookkeeping;
it is not a zero-write operation. COPY rechecks source fingerprints, stages the
destination, and publishes the register last. It preserves source files but
removes its own staging directory. It does not transfer plaintext credentials
or establish cloud ownership.

Changed, expired, or consumed reviews require a fresh preview. Do not interchange
the destination `source_revision` with `migration_receipt.source_revision`,
which fingerprints the legacy inputs. Do not run template-copy scripts as a
substitute for migration: template refresh and configuration conversion have
different effects, and legacy refresh scripts can remove or overwrite files.

<a id="take2-director-and-teacher-screenplay"></a>
<a id="tutorial-mode-and-menu-tour"></a>
## Desktop walkthrough

### 1. Open the registered factory

1. Open the Windows app and enable **Tutorial Mode** in AI Factory configuration.
2. Choose **Open existing** and select your `azurefactory` folder.
3. Wait for the catalog to load. Check the selected factory, environment,
   scale-set suffix, and project before continuing.
4. If using the open-existing tutorial scenario, select **Verify action** after
   loading. Entering a path alone does not complete the operation.

**Checkpoint:** the intended registered factory is loaded. No Azure deployment
has occurred.

<a id="q3-what-runs-when-tutorial-mode-is-enabled"></a>
### 2. Use Tutorial Mode

Use **Hint** for more detail and **Show me** to locate a control. Perform the
requested action yourself, then choose **Verify action**. For example, verification
checks a completed validation result; it does not click **Validate** for you.

- Current step and progress describe the supported scenario. Back, Next, and
  Restart are navigation, not deployment consent.
- Guidance is silent by default. In builds that provide Windows local read-aloud,
  enable it deliberately and use Replay or Stop as needed.
- Pause guidance when leaving its scenario. There is not an app-wide tutorial
  tracker for every catalog, deployment, regional, and terminal operation.
- The enabled preference persists; tutorial progress is in memory. Changing
  factory scope restarts verification.
- **Review & save** opens a section; **Save** is a separate write. Export also
  writes a local file through the desktop app.

Tutorial Mode runs in the MAUI process and observes the real editor and completed
operations. It is not an external chatbot or a separate configuration copy.
The ordinary Python API handles application operations; saves, exports, and
prepared-review storage remain persistent even though tutorial progress is not.

### 3. Explore the views without starting operations

Visit the views available in your installed build, then return to the same
factory selection.

| View | What to try | What to distinguish |
|---|---|---|
| Configuration wizard | Expand Start & destination, Scale set & region, Platform networking, Security & governance, Project, Services, SKUs, Advanced, and Review & save. Search by label or exact field name. | Editing a draft, validating, and saving are separate actions. |
| Factory catalog | Inspect factory, scale-set, and project selectors, configuration actions, reviews, and jobs. | Saved definitions versus runtime operations. |
| Simple Mode | Inspect existing-factory navigation and new-factory settings without starting creation. | The GitHub-only new-factory route is not an existing ADO update; use the catalog for existing-factory work. |
| Full bootstrap | Inspect provider choice, destination/team details, capabilities, and warnings. | This is separate creation; execution can create common infrastructure, an initial project, repository changes, and pipelines. |
| Monitoring | Select a tab or filter and read source/time labels. | Live, cached, unavailable, and sample data. |
| Agent/model map | Search, filter, and select a node. | A diagram or animation is not evidence of a running workload. |
| AI Factories / AI Factory | Select an environment or factory and inspect its details. | Saved plans, observed Azure groups, and successful jobs are different. |
| Projects / Scale sets | Select an existing record and inspect its scope. | A project number or suffix alone is not a unique execution target. |
| Concept animations | Explore promotion, DataOps, MLOps, RAG, and fine-tuning. | These explain workflows; playback does not execute them. |
| Tickets | Inspect work and review context. | A ticket is not authorization to deploy. |
| API connection | Open live Swagger or OpenAPI JSON. | Swagger **Try it out** can mutate real state. Protect the API key. |
| Appearance / About | Inspect presentation preferences and installed application information. | These do not change infrastructure. |
| Shared footer / terminal | Inspect scope, warnings, and job output. | Azure refresh is an external read; input and stop controls affect running jobs. |

If using **Copy common details** in Full bootstrap, review the resulting draft:
it copies account/team defaults, not the destination, project, network, or
resource settings. Missing launcher capabilities are prerequisites to resolve,
not a reason to bypass review. Default Simple or Full bootstrap settings are not
proof of an executable deployment chain; check the
[deployment prerequisites](#check-deployment-prerequisites) before starting.

## Phase 1: Function update and project 003

Use an existing factory with a Development scale set of suffix `001`
(**Dev001**). Project numbers below are examples: select existing definitions
where present, and use an unused number for a genuinely new project.

### Configure project001

1. Select the exact factory, **Dev001**, and **project001** in the catalog.
   This is a same-environment update, not promotion.
2. Inspect networking and security. Do not change Private/Hybrid access or
   existing addressing just to follow the exercise.
3. Find `enableFunction` and inspect `functionRuntime`, `functionVersion`, and
   `skuFunctionDev` where exposed. If Function is already enabled, keep it enabled;
   no toggle or save is needed merely to demonstrate the field.
4. For a genuine change, use the scoped configuration editor and review only the
   intended settings. Typed ARM parameter editing uses its own schema and
   prepare/confirm workflow; see the [contract reference](#cli-and-api-contract-reference).
5. Validate as applicable, inspect warnings, and separately confirm the approved
   configuration change. Reload the scoped settings.

Wizard flags commonly use strings such as `"true"`; typed ARM parameters use the
types returned by the selected schema. Do not use `configure-settings` to change
immutable identity, version, region, tenant/subscription, or placement fields.

**Checkpoint:** the saved project configuration reflects the intended Function
settings. This does not establish that a Function App or hosting plan exists.

### Add or reuse project003

1. Refresh the catalog and look for **project003**. If it exists, select it instead
   of creating a duplicate.
2. For a new project, choose **Add a new project**, enter an unused project number
   and friendly name, and select only **Development → exact Dev001**. Do not add
   Stage or Production placements for this exercise.
3. Review the service profile, SKUs, network allocation, and cost. Depending on
   the release and profile, defaults can enable services such as Foundry,
   AI Search, Cosmos DB, Azure ML, Databricks, Data Factory, and Event Hubs.
   Defaults are neither a minimal-cost profile nor a guarantee of regional
   availability.
4. Prepare the configuration review. Check project identity and placement,
   configuration-only effects, warnings, blockers, and expiry.
5. Confirm the approved change once, reload, and check that the project has the
   intended Dev001 placement. For an existing draft, save only genuine approved
   differences.

Layout-2 projects snapshot configuration at creation; later factory or scale-set
setting changes do not silently propagate into every existing project.

**Checkpoint:** the project definition and its intended placement are saved.
No resource group or service deployment is implied. Deploy project001 and
project003 through separate, project-specific reviews if authorized.

<a id="take2-producer-only-readiness-gate"></a>
## Review and run a project deployment

You may stop at a reviewed configuration. Continue only when the exact deployment
scope, effects, and cost are approved.

### Check deployment prerequisites

| Check | Required review |
|---|---|
| Scope and version | Exact root, factory/project/scale-set UUIDs, environment, catalog revision, supported release, and resolved source ref. |
| Azure identity | Correct account, tenant, subscription, permissions/PIM, policy, regional service support, and quota. |
| Pipeline binding | Reviewed repository/ref, writer identity, and supported execution route. Configure register-backed bindings through the supported form/API, not by hand-editing generated `ado.json`. |
| Runtime enrollment | Supported Linux execution runner and verified coordination for all overlapping writers. The guarded v1.25 ADO path requires Azure Blob lock enrollment; newer contracts may support other explicitly governed modes. Use the selected release's requirements. |
| Ownership and dependencies | Verified ownership for writable resource groups and shared dependencies. A dependency-only common scope does not authorize common/network/RBAC writes. |
| Network and cost | Approved address plan, actual capacity, DNS/peering/access, service profile, SKUs, and expected spend. A capacity preview is not live IPAM approval. |
| Non-deletion | All applicable cleanup/delete flags false, authoritative frozen inputs reviewed, and no destructive or unresolved what-if changes. |

For the non-deleting workflow, inspect `cleanFoundryCaphost`,
`debugEnableCleaning`, `deleteAllForProject`, `deleteAllServicesForProject`,
`deleteKeyvaultAlso`, and `enableDeleteForDisabledResources` where present.
The settings API may omit these fields: absence is not proof of `false`.
The guarded runtime uses incremental ARM and accepts **Create, Modify, NoChange**
what-if changes. There is no runtime `--no-delete` switch.

A saved binding or working provider sign-in is not proof of enrollment. Adding
a runner does not coordinate existing writers. Do not adopt resources by name,
grant unrelated RBAC, or route around a blocker through legacy scripts.

**Current integrated-hub limitation:** the registered combination
`access_hub_mode=integrated` with `setup_hub_access=true`, including the default
Simple topology, is currently blocked. A retained shared lock account's single
canonical private endpoint cannot be placed in a factory-owned common VNet
without compatible network, DNS, and deletion-ownership contracts.

Use an explicitly reviewed external-hub or no-hub configuration only with source,
API, and app versions that support that topology. No-hub mode (`integrated` with
`setup_hub_access=false`) skips shared hub-lock storage; it does not mean an
external hub exists or that other execution prerequisites are satisfied. Follow
the [setup guide's topology requirements](24-end-2-end-setup.md#current-integrated-hub-limitation)
and resolve the actual preview's blockers. Saving configuration does not establish
that a default configure-to-deploy chain will succeed.

### Prepare, confirm, and verify

1. Select the project and its Dev001 placement. Choose **Set up project
   deployment** where available, or the installed build's scoped **Review
   deployment** action. Check that the project is explicitly included, rather
   than selecting a common-only operation.
2. Select **1.25**, then **Prepare review**. Navigation to setup does not itself
   prepare, save, confirm, or run anything.
3. Inspect target, resolved source, effects, warnings, costs, ownership,
   non-deletion checks, and what-if results. If `can_execute` is false or any
   blocker remains, stop and resolve the prerequisites with the responsible
   operator. A pipeline-setup shortcut does not provision enrollment.
4. Obtain approval for this exact, unexpired review. Preparation may persist
   bookkeeping and perform external checks, but is not execution.
5. Confirm **once** and retain the resulting job ID. Follow that job's status
   and logs. After a timeout or ambiguous response, inspect existing jobs;
   do not repeat confirmation or start another deployment.
6. After completion, independently inspect the intended Azure scope. For
   project001, verify the Function App and hosting plan. For project003, verify
   its resource group and approved service inventory. Check that Stage and
   Production were not changed.

**Checkpoint:** distinguish an accepted job from a completed job, and a completed
job from independently verified Azure resources. A saved draft, `can_execute:true`,
or a zero exit code alone does not establish the intended cloud outcome.

## Phase 2: Dedicated subscriptions and Germany

### Compare capacity and subscription choices

- **Common subscriptions for up to 8 projects** means shared environment
  infrastructure, subject to configured and actual network capacity. The label
  is a ceiling, not a reservation; a full service profile can estimate fewer
  projects.
- **Own subscriptions per project** requires subscriptions supplied and approved
  by their owner. It does not create subscriptions, transfer resources, or
  allocate quota.
- A full-profile `/20` plan may accommodate only one project. Use the selected
  profile's calculated capacity and review actual Azure networking separately.
- Switching a draft's mode retains existing addressing. **Apply network defaults**
  deliberately replaces draft ranges; it is not a network migration. Do not apply
  it over a saved network without a separate plan.

### Save a regional definition

1. Plan a distinct regional factory in the same register, for example
   **Contoso Germany**, with an approved unique prefix such as `ct-gw-`.
   Choose **Germany West Central** (`germanywestcentral`).
2. Select **1.25** and supply the real approved tenant, subscription, and
   orchestrator. Region belongs to the **factory**; a scale set has no independent
   region field. Adding suffix `002` under a Sweden factory still targets Sweden.
3. Define **Development, suffix 002** with an approved, network-aligned private
   address plan and appropriate capacity. Check organizational IPAM, hub/peering,
   DNS, access posture, policy, service availability, and quota.
4. Prepare the configuration review. Inspect all proposed scale sets and initial
   project behavior in the running API. Some versions create project001 by
   default when creating an AI Factory; do not assume the new factory is empty.
5. Confirm only the approved configuration. Reload the catalog to obtain the
   new factory and scale-set UUIDs.
6. If needed, add an unused project such as **004** with only the returned
   **Dev002 UUID** placement, using a separate reviewed configuration change.
   Reuse any intended project already created with the factory.

An explicitly approved shared subscription is valid only as a shared-subscription
design; do not call it dedicated isolation. Missing or syntactically valid IDs do
not establish ownership. Non-overlap with one factory does not establish
organization-wide network approval.

**Checkpoint:** both regional definitions and the intended placements are visible
in the register. These are configuration results, not Germany Azure deployments.
Runtime support is provider-, capability-, and target-dependent; selecting an
orchestrator does not prove its deployment route is available.

## Phase 3: Clone preview

Use a configuration clone as a reference, not as a copy of a live environment.

1. Open **Factory catalog → Advanced → Clone configuration** and select the
   exact source factory.
2. Supply a new approved prefix, for example `ctref-`, choose the intended
   region, explicitly select **1.25**, and select **no project definitions**.
   A blank clone version can inherit the source; make the selection explicit
   for this exercise.
3. Prepare and inspect the preview. Check new configuration identities, copied
   subscription and CIDR values, overlap warnings, and reset ownership.
4. Stop at preview unless saving the reference is approved. If approved, confirm
   only the configuration review and reload the result.
5. Verify the new identities and unchanged source. No runtime job is expected.

The clone does not copy Azure resources, data, models, secrets, resource
ownership, or live writer/lock enrollment. Retained subscription and network
values do not provide isolation. Keep an overlapping clone as an **undeployed
configuration reference**; do not deploy it until a supported, separately reviewed
configuration and enrollment process has resolved those choices.

<a id="q2-api-connection-and-windows-storage"></a>
## API connection and credential handling

Use the intended app instance's **API connection** page, including **Open live
Swagger**, **Open OpenAPI JSON**, and **Copy key for Swagger** where available.
Do not infer the connection from another instance or a remembered default port.

| Client | URL setting | Key setting |
|---|---|---|
| MAUI persisted connection | Preferences: `api.base-address` | SecureStorage: `api.key` |
| Deliberate MAUI environment override | `ESAIF_API_BASE_ADDRESS` | `ESAIF_API_KEY` |
| Python SDK / CLI | `AIFACTORY_API_URL` | `AIFACTORY_API_KEY` |

Keep each URL/key pair coherent. A running app instance can retain its initialized
connection even when another instance changes shared preferences. On restart,
the bundled API can have a new port and key.

On Windows, MAUI SecureStorage uses user-bound encryption; it is not a plaintext
key in the factory folder or a Windows Credential Manager entry. Packaged and
unpackaged apps use different backing stores. Use the app's controls rather than
opening storage files to recover a key.

Supply the CLI key through an approved process-local secret mechanism. Never put
it in a URL, command argument, checked-in file, transcript, environment dump,
or log. If using the clipboard, clear the copied secret without overwriting
subsequent clipboard content. Close the private session or remove its key
environment variable after use.

The API authenticates with `X-API-Key`. This is distinct from the host's Azure
identity and from execution approval. Do not expose the desktop loopback API as
a public integration endpoint.

This tutorial targets Windows. MAUI source targets or platform-specific
SecureStorage implementations do not establish tested desktop support elsewhere.
The bundled host is Windows-only; a separate Linux Python API/CLI is not a native
Linux MAUI app or a guarantee that Windows-protected manifests are portable.

<a id="take2-cliapi-correspondence-and-guarded-sample"></a>
## API and CLI lab

Install the existing [Python SDK/CLI](../../../environment_setup/azurefactory-cli/readme.md)
and use the [API examples](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md)
for full request schemas. Check `azurefactory --help`, `azurefactory doctor`, and
the running server's OpenAPI before using an operation.

### CLI and API contract reference

This table is a reference, **not a batch script**. Variables must come from
fresh discovery; request files must contain reviewed values. Configuration and
runtime receipts are not interchangeable.

| Task | CLI | API / effect |
|---|---|---|
| Check the connection | `azurefactory health`; `azurefactory doctor` | `GET /health`; OpenAPI/schema checks. Not Azure readiness. |
| Discover identities | `azurefactory catalog list --folder $root` | `GET /api/v1/factory-catalog?folder=...`; returns the catalog directly, not an `ok` wrapper. |
| Read scoped settings | `azurefactory catalog settings --folder $root --factory-id $factoryId --scale-set-id $scaleId --project-id $projectId` | `GET /api/v1/factory-catalog/settings`; exact selectors and catalog revision. |
| Review a settings change | `azurefactory request POST /api/v1/factory-catalog/prepare --body-json .\settings.json --write --yes` | `action:"configure-settings"` with exact IDs, `expected_revision`, and intentional `settings`. This prepares only and does not save a CLI receipt. |
| Read typed ARM parameters | `azurefactory parameters get --folder $root --factory-id $factoryId --scale-set-id $scaleId --project-id $projectId --version-ref 1.25` | `GET /api/v1/factory-catalog/parameters`; use returned schema, template names, and types. |
| Prepare typed edits | `azurefactory parameters prepare --request-json .\approved-parameters.json --save-receipt .\parameters.receipt.json` | `POST /api/v1/factory-catalog/parameters/prepare`; use returned `source_revision` as `expected_revision`, plus `schema_revision`. |
| Save typed edits | `azurefactory parameters confirm --receipt .\parameters.receipt.json --yes` | Separate approved `POST /api/v1/factory-catalog/parameters/confirm`. Not generic catalog confirmation. |
| Add a project definition | `azurefactory project add --folder $root --factory-id $factoryId --number $unusedNumber --placement "dev=$scaleId" --expected-revision $revision --save-receipt .\project.receipt.json` | Catalog prepare with `action:"add-project"`; saves no Azure resources. |
| Prepare a regional factory | `azurefactory factory create --folder $root --prefix $regionalPrefix --region germanywestcentral --aifactory-version 1.25 --scale-set-json .\approved-scaleset.json --expected-revision $revision --save-receipt .\region.receipt.json` | Catalog prepare with `action:"create-factory"`. Inspect initial project defaults in the live contract as well as the supplied scale sets. |
| Add a scale set | `azurefactory scaleset add --folder $root --factory-id $factoryId --scale-set-json .\approved-scaleset.json --expected-revision $revision --save-receipt .\scale.receipt.json` | Catalog prepare with `action:"create-scale-set"`; region is inherited from the factory. |
| Prepare a configuration clone | `azurefactory factory clone --folder $root --factory-id $factoryId --prefix $clonePrefix --region germanywestcentral --aifactory-version 1.25 --include-projects none --expected-revision $revision --save-receipt .\clone.receipt.json` | Catalog prepare with `action:"clone"`; review retained subscriptions/networks and new identities. |
| Save a catalog definition | `azurefactory catalog confirm --receipt $configurationReceipt --yes` | Approved configuration-mode `POST /api/v1/factory-catalog/confirm`; response has `catalog` and `job:null`. |
| Prepare a deployment | `azurefactory runtime deploy --folder $root --factory-id $factoryId --scale-set-id $scaleId --project-id $projectId --version-ref 1.25 --expected-revision $revision --save-receipt $receiptPath` | Catalog prepare with `action:"deploy"`; **not execution**. |
| Execute the reviewed deployment | `azurefactory runtime confirm --receipt $receiptPath --yes` | Separate runtime confirmation; acknowledgement contains **`job.id`**, not a top-level `job_id`. |
| Observe a job | `azurefactory runtime status --folder $root --job-id $jobId`; `azurefactory runtime logs --folder $root --job-id $jobId --cursor 0` | `GET /api/v1/factory-catalog/jobs/{job_id}` and `/api/v1/factory-catalog/terminal`. |

For `create-factory` and `create-scale-set`, each scale-set input needs its
environment, suffix, tenant/subscription IDs, orchestrator, and reviewed network
configuration. Use `--aifactory-version` for factory create/clone and
`--version-ref` for runtime/parameter selection.

For the generic settings request, use the separately reviewed API confirmation
with its returned confirmation ID; do not fabricate a CLI receipt. Generic POST
commands require `--write --yes` even for some offline validation operations:
HTTP method and CLI flags alone do not describe an operation's effects.

### A. Discover one exact project

Run the following blocks separately in a private PowerShell session. The example
uses an existing **ADO** factory, **Dev001**, and project **001 or 003**. It does not
create missing definitions or establish runtime enrollment. If you already
deployed through the UI, use discovery and job reads only.

Set `AIFACTORY_API_KEY` privately before starting. Keep output and receipts in an
access-controlled working location outside your tracked source.

```powershell
$ErrorActionPreference = 'Stop'
$env:AIFACTORY_API_URL = Read-Host 'Live base URL from the intended API connection page'
if (-not $env:AIFACTORY_API_KEY) { throw 'Supply the process-local API key first' }
$root = (Read-Host 'Absolute azurefactory folder on the API host').TrimEnd('\')
if ($root -notmatch '^(?:[A-Za-z]:\\|\\\\[^\\]+\\[^\\]+\\)' -or
    (Split-Path $root -Leaf) -ine 'azurefactory') {
    throw 'Use the absolute registered root on the Windows API host'
}

function Read-AzureFactoryJson {
    param([string[]]$Arguments)
    $output = & azurefactory @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'CLI failed; inspect privately before continuing' }
    return (($output -join "`n") | ConvertFrom-Json)
}
function Select-ExactlyOne {
    param([object[]]$Items, [string]$Label)
    if ($Items.Count -ne 1) { throw "Expected exactly one $Label; do not guess" }
    return $Items[0]
}

$health = Read-AzureFactoryJson -Arguments @('health')
$doctor = Read-AzureFactoryJson -Arguments @('doctor')
$catalog = Read-AzureFactoryJson -Arguments @('catalog', 'list', '--folder', $root)
if ($catalog.contract_version -ne 1 -or $catalog.mode -ne 'catalog' -or
    $catalog.layout_version -ne 2 -or -not $catalog.revision) {
    throw 'A compatible registered version-2 catalog is required'
}
$factoryKey = Read-Host 'Exact factory key from your catalog selection'
$factory = Select-ExactlyOne -Items @(
    $catalog.factories | Where-Object key -CEQ $factoryKey
) -Label 'factory'
$scale = Select-ExactlyOne -Items @($factory.scale_sets | Where-Object {
    $_.environment -eq 'dev' -and $_.suffix -eq '001'
}) -Label 'Dev001 scale set'
if ($scale.orchestrator -ne 'ado') { throw 'This example is scoped to ADO' }
$number = Read-Host 'Project number for this exercise: 001 or 003'
if ($number -notin @('001', '003')) { throw 'Outside this example scope' }
$project = Select-ExactlyOne -Items @(
    $factory.projects | Where-Object number -CEQ $number
) -Label 'project'
$placement = Select-ExactlyOne -Items @($project.placements | Where-Object {
    $_.environment -eq 'dev' -and $_.scale_set_id -eq $scale.id
}) -Label 'matching placement'
if ($number -eq '003' -and @($project.placements).Count -ne 1) {
    throw 'This exercise expects project003 to have only its DEV placement'
}
$factoryId = [string]$factory.id
$scaleId = [string]$scale.id
$projectId = [string]$project.id
$revision = [string]$catalog.revision
$settings = Read-AzureFactoryJson -Arguments @(
    'catalog', 'settings', '--folder', $root, '--factory-id', $factoryId,
    '--scale-set-id', $scaleId, '--project-id', $projectId
)
[pscustomobject]@{ Project = $number; Environment = 'dev'; Suffix = '001'; Version = '1.25' }
```

The summary describes the selected example, not deployment readiness. Inspect
settings privately. Do not print full state or assume that omitted delete/cleanup
fields are false.

### B. Prepare a deployment review

Complete the [deployment prerequisites](#check-deployment-prerequisites) first.
Do not run this block if the UI already executed this operation.

```powershell
if ((Read-Host 'Type PREPARE to request a review for this exact scope') -cne 'PREPARE') {
    throw 'Preparation not requested'
}
$fresh = Read-AzureFactoryJson -Arguments @('catalog', 'list', '--folder', $root)
if ($fresh.revision -ne $revision) { throw 'Catalog changed; rediscover and review' }
$receiptPath = Join-Path (Get-Location).Path (
    "project$number-" + [guid]::NewGuid().ToString('N') + '.receipt.json'
)
$previewOutput = & azurefactory runtime deploy --folder $root `
    --factory-id $factoryId --scale-set-id $scaleId --project-id $projectId `
    --version-ref 1.25 --expected-revision $revision --save-receipt $receiptPath
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed or was blocked; do not confirm' }
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
if ($receipt.format -ne 'azurefactory-review-receipt-v1' -or
    $receipt.purpose -ne 'catalog-confirm' -or $receipt.operation -ne 'runtime-deploy' -or
    $receipt.operation_mode -ne 'runtime' -or $receipt.can_execute -ne $true -or
    $receipt.preview.contract_version -ne 1 -or
    $null -eq $receipt.preview.blockers -or @($receipt.preview.blockers).Count -ne 0 -or
    [DateTimeOffset]::Parse($receipt.expires_at) -le [DateTimeOffset]::UtcNow) {
    throw 'Not a current executable runtime review'
}
$receipt | Select-Object format, purpose, operation, operation_mode, can_execute, expires_at
```

**Stop here for review and approval.** Privately inspect the complete effects,
warnings, what-if, binding, target, resolved source, and costs. The local prompt
is only a pause, not an organizational approval system. Receipt creation refuses
overwriting an existing file; never edit a receipt to clear a blocker.

### C. Separately confirm the approved receipt

```powershell
if ((Read-Host 'Type EXECUTE only after this exact unexpired review is authorized') -cne 'EXECUTE') {
    throw 'Execution not approved'
}
$confirmOutput = & azurefactory runtime confirm --receipt $receiptPath --yes
if ($LASTEXITCODE -ne 0) {
    throw 'Inspect catalog jobs before any further action; do not repeat confirmation'
}
$confirmed = ($confirmOutput -join "`n") | ConvertFrom-Json
if ($confirmed.contract_version -ne 1 -or -not $confirmed.job.id) {
    throw 'Missing runtime acknowledgement; inspect jobs, do not guess or retry'
}
$jobId = [string]$confirmed.job.id
```

The CLI checks receipt purpose/mode, content hashes, request/preview bindings,
API URL, blockers, and expiry. The server performs final concurrency and execution
checks. Hashes are not signatures or authorization. If the connection changes,
do not patch the receipt; first inspect whether a job already started, then use a
fresh review only when a new operation is appropriate.

### D. Follow the existing job

If the UI started the job, obtain its actual job ID from the job view or
`azurefactory catalog jobs --folder $root` and assign it to `$jobId`.
Do not prepare or confirm again.

```powershell
if (-not $jobId) { throw 'Supply the actual job ID before reading status' }
$pollOutput = & azurefactory runtime poll --folder $root --job-id $jobId --poll-timeout 1800
$pollExit = $LASTEXITCODE
$statusOutput = & azurefactory runtime status --folder $root --job-id $jobId
$statusExit = $LASTEXITCODE
$logsOutput = & azurefactory runtime logs --folder $root --job-id $jobId --cursor 0
$logsExit = $LASTEXITCODE
[pscustomobject]@{ PollExit = $pollExit; StatusExit = $statusExit; LogsExit = $logsExit }
```

Inspect the captured status and log output privately, including on nonzero exit:
job failure and timeout need investigation, not resubmission. Polling does not
cancel the job. A zero exit code still requires independent verification of the
intended resources and absence of unintended changes.

### Equivalent API bodies and receipts

These PowerShell statements construct bodies **in memory only**. They send no
HTTP request and are not a second deployment.

```powershell
$prepareBody = @{
    folder = $root
    contract_version = 1
    action = 'deploy'
    factory_id = $factoryId
    scale_set_id = $scaleId
    project_id = $projectId
    version_ref = '1.25'
    expected_revision = $revision
} | ConvertTo-Json
$confirmBody = @{
    folder = $receipt.folder
    contract_version = 1
    confirmation_id = $receipt.confirmation_id
} | ConvertTo-Json
```

An API integration sends the first body to
`POST /api/v1/factory-catalog/prepare`, reviews the returned preview, and only
after approval sends the corresponding confirmation body to
`POST /api/v1/factory-catalog/confirm`. Use the fresh response for that integration,
not a confirmation ID from an operation already consumed by the UI or CLI.

| Receipt/result field | Meaning |
|---|---|
| `format` | `azurefactory-review-receipt-v1`. |
| `purpose`, `operation`, `operation_mode` | For this runtime example: `catalog-confirm`, `runtime-deploy`, `runtime`. |
| `base_url`, `folder`, `confirmation_id`, `expires_at` | Bound connection, configuration root, review, and lifetime. |
| `request`, `preview`, `request_hash`, `preview_hash` | Reviewed content and canonical hashes. Keep the receipt private and unchanged. |
| `preview` | Includes contract/source revision, effects, warnings, blockers, target, inventory, and applicable source-version/binding details. |
| `can_execute`, optional `blocked_reason` | A stored blocked preview is not confirmable. |
| Runtime confirmation | `contract_version:1` and `job.id`; acknowledgement is not job completion. |
| Configuration confirmation | `contract_version:1`, `catalog`, and `job:null`; a saved definition is not deployment. |

### Other workflow boundaries

- Validation uses **`POST /api/v1/validation`**, not `/api/v1/validate`.
  Submit complete state. Validation is offline and does not save.
- `POST /api/v1/export` writes on the API host when `path` is supplied; without
  it the API returns content. The MAUI Export action still writes a local export.
- Registered placements are configuration, not promotion. Typed parameters use
  their dedicated prepare/confirm routes.
- For an unmigrated legacy project, load the exact source and preserve provenance.
  Nested project `variables.json` can take precedence over snapshots and root
  configuration. Do not turn a loaded project into a new one by changing its
  number or stripping source metadata.
- Registered ADO/GHA launchers expose `inspect` and `execute` for reviewed
  protected manifests. `inspect` is not generic JSON inspection; help output
  does not prove enrollment or Azure readiness. Do not manually execute a launcher
  to duplicate a catalog job.
- `--non-interactive` suppresses prompts, not effects; `--no-wait` still
  dispatches. Preparation is not universally zero-write.
- Use the running OpenAPI for the available route inventory. A listed endpoint
  is not a tested deployment capability or permission to invoke it.

## Deployment, promotion, operations, and handoff

Record outcomes in separate categories:

| Result | How to verify it |
|---|---|
| Saved configuration | Reload the exact factory/project/scale-set selection and inspect values and placements. |
| Prepared review | Check action, mode, scope, source version, effects, blockers, and expiry. |
| Started or completed job | Follow the actual returned job ID and inspect status and logs. |
| Verified Azure outcome | Independently check the intended resource scope, service inventory, and unintended changes. |

For registered promotion, establish the target environment's scale set and project
placement, review its parameters and enrollment, then separately authorize its
deployment. Do not assume this copies all Development settings or data.
Legacy update/promotion has a different contract: same-environment planning uses
`operation:"update"`; promotion uses `operation:"deploy"` with an allowed later
environment, not a `promote` operation. Do not mix that route with registered roots.

Use Concept animations to explore the next workflows: DataOps prepares trusted
data; MLOps covers training, evaluation, registration, and serving; RAG retrieves
context during inference; fine-tuning changes model behavior through training.
Each requires its own inputs, permissions, quality gates, and release decisions.
The diagrams execute none of them.

Deletion is outside this tutorial. Catalog factory/scale-set deletion can affect
Azure; legacy snapshot deletion has different local effects. Do not use deletion
to resolve an exercise conflict. Preserve existing configuration and maintain one
coordinated writer model for each physical target.

### Further reading

- [End-to-end setup](24-end-2-end-setup.md)
- [Update an AI Factory](26-update-AIFactory.md)
- [FinOps monitoring tutorial](tutorial-fiops.md)
- [SDK/CLI documentation](../../../environment_setup/azurefactory-cli/readme.md)
- [API usage examples](../../../environment_setup/install_config_wizard/api-usage-examples/readme.md)
- [CLI implementation](../../../environment_setup/azurefactory-cli/src/azurefactory/cli.py),
  [SDK request methods](../../../environment_setup/azurefactory-cli/src/azurefactory/client.py),
  and [receipt checks](../../../environment_setup/azurefactory-cli/src/azurefactory/review.py)
- [ADO launcher](../../../bootstrap/ADO-azurefactory.sh),
  [GitHub Actions launcher](../../../bootstrap/GHA-azurefactory.sh),
  and [runtime guards](../../../bootstrap/lib/factory_lifecycle.py)

Source references explain the contracts; they do not certify the version or
capabilities of an installed binary. Resolve a version or capability mismatch
before continuing rather than falling back to an unreviewed deployment path.
