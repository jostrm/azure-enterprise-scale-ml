# AI Factory Configuration Wizard for Windows 11

Status: Under development

A native .NET MAUI desktop app with the Python API from the Tkinter wizard included.

## Install

Status: Tested

1. Download **all four files** below and keep them together in one local folder. These are direct download links.
2. Double-click the setup EXE and follow the short wizard. It installs for your Windows account; administrator rights are not normally required.
3. Open **Enterprise Scale AI Factory** from Start. The app starts its bundled local API automatically.

| Download | Size |
| --- | --- |
| [Setup EXE](https://raw.githubusercontent.com/jostrm/azure-enterprise-scale-ml/main/environment_setup/install_config_wizard/maui/ESAIF.ConfigWizard-1.0.0-win-x64-setup.exe) | 2.3 MB |
| [Data part 1](https://raw.githubusercontent.com/jostrm/azure-enterprise-scale-ml/main/environment_setup/install_config_wizard/maui/ESAIF.ConfigWizard-1.0.0-win-x64-setup-1.bin) | 93.7 MB |
| [Data part 2](https://raw.githubusercontent.com/jostrm/azure-enterprise-scale-ml/main/environment_setup/install_config_wizard/maui/ESAIF.ConfigWizard-1.0.0-win-x64-setup-2.bin) | 96.0 MB |
| [Data part 3](https://raw.githubusercontent.com/jostrm/azure-enterprise-scale-ml/main/environment_setup/install_config_wizard/maui/ESAIF.ConfigWizard-1.0.0-win-x64-setup-3.bin) | 33.3 MB |

**Yes, all three data parts and the Setup EXE are required.** The `.bin` files contain the compressed application and bundled runtimes. They are not optional downloads or your personal data. The installer is split to stay below GitHub's file-size limit.

Keep all four files together with their original filenames, then run **only the Setup EXE**. It reads the three data parts automatically. [SHA256SUMS.txt](SHA256SUMS.txt) lists the expected hashes; compare a download with `Get-FileHash .\filename -Algorithm SHA256`.

**Unsigned preview:** Windows SmartScreen or your organization's application policy may warn or block installation. Verify the download source and hashes. Follow your organization's approval process; do not disable security controls. This is not a Microsoft Store or signed enterprise deployment package.

Installation, bundled API/schema/templates, Python/Tcl/Tk files and uninstall were exercised on Windows 11 x64 build 26100. The current desktop preview also ran with .NET and Windows App SDK loaded locally. This is not a clean-VM certification of every Windows 11 build or managed-device policy.

## Prerequisites

Status: Tested

| Purpose | What you need |
| --- | --- |
| Open the app | Windows 11 **x64** (build 22000 or later) and [Microsoft Edge WebView2 Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/). WebView2 is normally already installed on Windows 11; setup checks for it. |
| App/API runtimes | **Included:** .NET, Windows App SDK, Python, Tcl/Tk, FastAPI and API dependencies. No Visual Studio, .NET SDK, MAUI workload or separate Python installation is needed just to use the desktop UI. |
| Run deployment scripts | [Git for Windows with Git Bash](https://git-scm.com/downloads/win), [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli-windows), and a **host Python 3.10+** available in Git Bash. The embedded API interpreter does not replace the standalone Python command required by the Bash launchers. |
| GitHub Actions projects | [GitHub CLI](https://cli.github.com/), plus access to the target repository and appropriate Azure permissions. |
| Azure DevOps projects | Access to the target Azure DevOps organization/project, configured pipelines and appropriate Azure permissions. |

Internet access is required for sign-in, Azure inventory, source-version checks and deployments. Installing the app does **not** grant Azure or repository permissions. The [deployment prerequisites](../../../documentation/v2/10-19/12-prerequisites-setup.md) still apply.

The tested scope here is the recorded local installation above, not successful provisioning with every listed service or permission configuration.

## First use

Status: Under development

- Choose **Configuration wizard** to open or create your configuration; point it at your consumer repository's `aifactory` folder, not this accelerator source repository.
- Use **Connection** if you need to inspect the API connection or intentionally connect to a separately hosted API.
- On **AI Factory**, **Plan to Stage** saves a Stage card with **Status: Not deployed**. Planning does not deploy resources.
- Use **Deploy** for a planned environment and **Update** for an observed deployment. Both open an explicit review before a script starts. **Patch** unchecked passes `--project-only`; checked refreshes the shared templates as well.
- The launcher is in the parent of `aifactory`: `ADO-update-aifactory-and-run-project.sh` or `GHA-update-aifactory-and-run-project.sh`. Keep your consumer launchers and templates current.
- The main menu retains the current page's project-style gradient highlight. **Manage factories** handles the newer factory catalog; legacy views can redirect there when a catalog root is selected.

## Updates and uninstall

Status: Tested

Close the app and finish or explicitly resolve any active deployment before updating. Run the newer installer to update the same per-user installation. Uninstall through **Settings > Apps > Installed apps > Enterprise Scale AI Factory**.

Your repositories, saved configurations and Azure resources are separate from the app installation. Uninstall is not an Azure cleanup operation.

## Screenshots

Status: Under development

<img src="../images/maui-aifactories-1.png" alt="AI Factory overview" width="900" />

<img src="../images/maui-config-sku.png" alt="AI Factory configuration and model SKU" width="900" />

These existing preview images are retained at a readable width. Newer menu views and the evolving map/catalog flows may differ from these screenshots.

## Feature guide and status conventions

Status: Finished

The sections below describe the MAUI application after setup. **Finished** here means the documentation conventions are complete, not that Azure workflows are production-certified. **Tested** is limited to local unit/presentation coverage and the recorded Windows installation or native UI exercises. **Under development** includes implemented previews whose end-to-end integration, prerequisites or live-cloud outcomes still need verification. No cloud deployment was performed for this update.

The guide follows the current MAUI source. An older installer or Python API may not expose every documented control. Backend capability checks and the exact server review take precedence over a screenshot, saved configuration or button label.

| Menu view | Purpose |
| --- | --- |
| [Configuration wizard](#configuration-wizard) | Advanced schema-driven configuration, import/export and saved snapshots. |
| [Simple Mode](#simple-mode) | Separate private-network, Dev-first GitHub Actions creation preset. |
| [Full bootstrap](#full-bootstrap) | Explicit create-launcher workflow for common infrastructure and an initial project. |
| [Monitoring](#monitoring) | Current-factory analytics, source-labelled charts and Prompt Explorer. |
| [AI Factories](#ai-factories--regional-map) | Regional map, recorded pipeline findings and entry points to factory management. |
| [Manage factories](#manage-factories--catalog) | Exact factory, scale-set and project identities; reviewed configuration and runtime operations. |
| [AI Factory](#ai-factory--environment-board) | Observed Dev/Stage/Prod projects, planning drafts and deployment reviews. |
| [Projects](#projects) | Saved project configurations, filters, observed resource-group links and ticket drafts. |
| [Scale sets](#scale-sets) | Saved shared configurations and common-resource-group access. |
| [Tickets](#tickets) | Own tickets, severity/status changes and Ticket Connections. |
| [Connection](#connection) | Python API connection, authentication key and live API documentation. |
| [Appearance](#appearance) | Local theme and animation preferences. |
| [About](#about) | Application architecture and responsibility boundaries. |

### Navigation and technical-value disclosure

Status: Tested

Open the main menu from the page header. Its gradient border identifies the current view; selecting a project or scale-set card is not the same as loading its configuration. Navigation retains the wizard session's edits. Catalog-root restrictions may redirect legacy views to **Manage factories** rather than display a misleading unscoped overview.

GUIDs and local paths normally appear behind contextual labels. Hover or choose **Details**, **view / edit**, or **View / copy** to inspect full values; editing requires **Save value** or **Cancel**. **Copy all** is explicit, not automatic. Password/API-key fields remain concealed. Masking is presentation-only: saved values, reviewed commands and execution are not redacted. The interactive terminal, explicit detail dialogs and OS file picker can show full paths and identifiers.

Local coverage includes `CardSelectionLayoutTests`, `TechnicalValuePresentationTests`, `TechnicalValueLayoutTests` and `WizardPageRebindingTests`. This does not establish Azure access or deployment success.

## Configuration wizard

Status: Tested

Choose an **AI Factory folder**, browse to an existing consumer `aifactory` directory, or use **Recent projects / ADO** and **Recent projects / GHA**. The Python API supplies defaults, field options, validation and persistence; MAUI does not maintain a separate set of deployment defaults. Use **Back**, **Next**, the section selector, or **Search by label or API field**. Search spans all sections and both SKU tabs; search results edit the same draft fields.

| Section | What to configure |
| --- | --- |
| Start & destination | Scaling mode, network mode, hub topology, GitHub/Azure DevOps route, runner/build-agent options, factory folder and dashboard link. |
| Scale set & region | Shared subscription/tenant settings, factory prefix/suffix and Azure region. |
| Platform networking | Supported VNet-format guidance, VNet and Dev/Stage/Prod ranges, common subnets, DNS and service connections. |
| Security & governance | Identity, RBAC settings, encryption, diagnostics, tags and cost controls. |
| Project | Project number, project-specific values and pipeline behavior. |
| Services | Service selection, models and compute options provided by the API schema. |
| SKUs | Separate **Dev** and **Stage & Prod** service-tier settings, including AI Search tier. |
| Advanced | Remaining supported settings, including AI Foundry Capability host. The unsupported Foundry Hub control is hidden without deleting its saved compatibility value. |
| Review & save | Validate, save a project/scale set, import/load/reset, or export a variable file. |

**Admin Location** uses the API's region catalog and updates the suggested location suffix only when the region is changed. Imported/custom values remain intact; enter a suffix manually when no default exists. Compact field cards show a readable title and API key, with help on hover and validation messages when needed.

Local coverage includes `WizardSessionTests`, `WizardFieldCatalogTests`, `ConfigFieldViewModelTests`, `NetworkModeAndSearchTests` and `WizardNetworkValidationTests`. These cover editing, schema mapping and validation behavior, not the availability of selected Azure SKUs.

### Import, export and saving

Status: Under development

- **Import (.yaml | .env | .json)** reads a configuration into the draft through the API. **Load folder** reads the selected factory's saved state; **Reset defaults** replaces the editing state with API defaults.
- **Validate** displays the API result. **Network advice for** limits advice to All environments, Dev, Stage or Prod; it does not change deployment targets or the SKU tab. Network advice is distinct from blocking configuration/topology errors.
- **Save project** persists the project snapshot. **Also write variables.yaml or .env for the pipeline** controls the additional pipeline-variable write; review that choice before saving.
- **Save scale set** persists shared settings for reuse. **Export variable file (.yaml | .env | .json)** renders the chosen format and opens the device's save flow.
- Saved project loading merges missing defaults while preserving explicit saved values. Selecting, exporting or saving a configuration does not deploy it.

The controls and API-backed flows are implemented. The named wizard tests cover state isolation, rebinding and validation; this guide does not claim a newly verified round trip for every file format or older backend version. Keep backups before replacing an imported draft or existing pipeline file.

### Network, hub and scaling choices

Status: Under development

**Network mode** groups Private, Hybrid and Public and shows the resulting flags read-only; unknown imported combinations are not silently rewritten. **Hub topology** distinguishes External Hub connected, Standalone with own Hub, and Standalone AI Factory. Private mode needs an appropriate own/external hub before saving; selecting a topology does not provision VPN Gateway, Bastion or AVD.

**Scaling mode** offers Own subscriptions per project or Common subscriptions for up to 8 projects. It does not create subscriptions. **Supported VNet formats** explains aligned CIDRs and the `XX` environment substitution. The API calculates capacity from the current ranges and subnet layout; the "up to 8" label is not a guarantee that the allocator or a deployed network has eight available project slots.

**Apply network defaults** previews exact draft replacements. **Optimize space** previews common-subnet starting positions within the existing VNet ranges. Both require confirmation and are draft tools, not migrations of deployed Azure networks. Custom/imported ranges are preserved unless explicitly replaced; overlapping/misaligned ranges need correction. Peering, remote-hub compatibility and available live capacity require separate review.

## Simple Mode

Status: Under development

Use this separate draft for the fixed **Private · Dev · GitHub Actions** preset: an existing Dev subscription, own hub, private endpoints and initial `project001`. **Open advanced configuration** returns without importing or overwriting the advanced draft. **Reload sign-ins** obtains cached Azure CLI/GitHub CLI context from the API host; no PAT or password is entered here.

Choose the subscription, region, factory prefix, template version and GitHub `owner/repository`. Repository visibility defaults to private; selecting public warns that repository code/workflow logs may be exposed, without changing Azure networking. **Additional options** supplies team membership, Entra group and cost center. Suggested names are updated only while unedited.

The API catalog separates hub, common and project resources. Required resources stay selected; optional resource checkboxes can be cleared. Dependencies must be resolved explicitly. When required, Application Gateway settings collect frontend hostname, backend FQDN and a versionless Key Vault certificate secret URI—not a certificate, password or secret value.

**Create AI Factory** prepares a preview only. Review destination, identity, selected resources, exact command, environment values, version, warnings and costs before **Confirm and create**. Edits or expired consent require another preview. Stage/Prod, subscription creation, live service availability and permission provisioning are not implied. Navigation does not cancel a submitted job; inspect its existing outcome before retrying an uncertain or partial creation.

## Full bootstrap

Status: Under development

This is separate from both Simple Mode and catalog configuration. **Reload creation capabilities** reads the server's creation registry; explicitly select a supported **create launcher** and **ADO/GitHub Actions** route. Update launchers are references, not substitutes for creation.

**Use current wizard configuration** copies it into an isolated bootstrap draft. Edit API-described fields, then **Prepare full bootstrap preview**. Open the complete command, effects and source-configuration review and accept the specific cost/common-infrastructure/initial-project consent before **Start full bootstrap once**.

**Refresh this job** inspects the submitted job without starting another. Changed inputs, root/connection changes, leaving the page or expiry invalidate consent. Provisioning can incur Azure costs and is not automatically retried. Bootstrap requires compatible published scripts, host tools, authentication and permissions; it does not silently migrate a catalog or replace wizard edits.

## Monitoring

Status: Under development

**Current AI Factory** is the default tab. API-provided cards show environment comparisons, stalled projects, blockers, service demand and project/department/cost-center evidence when available. **Reload analytics and counts** retries collection. Missing history or identity remains **Unknown**.

**Overview** provides requests, input/cached/output tokens, success/error rates, latency, model and resource/environment breakdowns, plus **New / Active / Solved** counts for your tickets in the current factory. Source labels and timestamps distinguish fresh Azure data, cached snapshots and mock/demo charts. Rings are not streaming updates; missing access is not zero usage.

Collection remains scoped to the configured factory's environment, region, tenant and subscriptions, even when the map aggregates multiple known folders. Partial telemetry failures remain visible. The app does not grant missing Reader/query permissions or alter network policy. For catalog roots, legacy Monitoring can redirect to **Manage factories** until a correctly scoped view is available.

### Prompt Explorer

Status: Under development

Choose **Explore prompts** from Monitoring. Filter by project, environment, model, category, status and text, then **Search** or **Clear**. **All** means no API filter. Select a record to inspect its prompt, response, identifiers and token breakdown.

Telemetry is read from the API host's local SQLite store; this view does not send prompts to an external classifier or modify operational data. An empty result is not proof that no requests occurred, and mock/partial sources remain labelled. Treat displayed prompt/response content as potentially sensitive.

## AI Factories — regional map

Status: Tested

The map explores known factory regions and their legacy/catalog configuration context using an offline world map with approximate datacenter locations. Select a marker or region picker to open **Region details**; right-click exposes management entry points. **Motion** pauses map pulses. Map geography uses [Natural Earth public-domain data](https://www.naturalearthdata.com/about/terms-of-use/), without online tiles or location permission.

Configured factory, Azure-region and selection markers are not live application-health indicators. Recorded pipeline failures can take visual precedence. Region details show available factory/project/resource counts, subscription context and monitoring scope; cached or unknown data must not be treated as current capacity.

**Add AI Factory** and catalog operations lead to **Manage factories** for exact identity selection and a server preview. For a selected legacy source, **Clone AI Factory** and **Add AI Factory scale set** open the independent configuration setup screen instead. **Review factory deletion** opens catalog identity selection, not immediate deletion. A datacenter is a destination filter, not permission to modify all resources in a region. Catalog configuration nodes must not be mistaken for observed legacy Azure inventory.

### Map navigation and selected scale sets

Status: Tested

The separate **Azure dashboard** link appears above **Open AI Factory**. It opens Azure Portal, preferring the explicitly configured `aifactory-dash-01` / `AIFACTORY_DASHBOARD_URL`. Without that override, the link uses the exact observed **Dev common resource group and subscription** for the selected scale set and the script's exact naming convention, `AIFactory-{prefix}-{locationSuffix}-{suffix}-dash-01`. A valid HTTPS Portal dashboard link is required; an enabled link neither creates a dashboard nor verifies that it exists.

**Open AI Factory** stays inside the app and selects the exact legacy root or catalog factory/scale-set context. Switching an editable root requires confirmation before replacing wizard edits. A historical legacy scale set that is not the root's active configuration opens a **read-only selected AI Factory** view; inspecting that snapshot never switches the root's deployment authority to it.

Purple scale-set nodes connect by lines to the selected yellow datacenter. Select a node or use the scale-set picker to show its selection pulse and exact context. The side panel shows common-resource-group details, project counts/numbers and subscription information. Crowded maps expand within the scrollable view rather than drop targets. Colors and pulses identify selection/configuration, not live health.

**Clone AI Factory** remembers the last populated source when an empty target datacenter is selected. A compact native confirmation shows the source and destination; a dropdown makes the source choice explicit when several factories are available. Cancelling changes nothing. For legacy clone/add-scale-set flows, the optional `source_scale_set_id` is carried through both prepare and save, so the selected saved snapshot's actual settings are used rather than unrelated root settings or unsaved editor values. Source files remain unchanged; cloning configuration does not clone Azure resources.

Local targeted tests and Windows publishing have passed. Native Windows interaction exercised the selected `mrvel-1-007` node, enabled dashboard link, internal AI Factory navigation, Sweden Central-to-Norway East confirmation, cancellation, and the four-source dropdown. These checks do not establish dashboard availability or successful live Azure deployment.

### Recorded pipeline findings

Status: Under development

**Import run report** reads a downloaded structured JSON preflight/pipeline report. The API also ingests reports in the active factory's `config-wizard\pipeline-reports` folder. Hosted CI artifacts must be downloaded/imported; the map does not silently retrieve authenticated pipeline logs.

Select a failing region and choose **View / copy findings** for service/SKU, reason, evidence source, environment and run metadata. Red means a recorded issue, not a live capacity probe. Findings are scoped to their factory/subscription/tenant; an unrelated successful run does not resolve a different SKU or establish restored capacity.

## Manage factories — catalog

Status: Under development

Select the consumer root in Configuration wizard, then **Reload catalog**. Select the exact logical factory and, where needed, its environment/suffix/subscription/tenant scale set and project. Catalog selections are separate from unsaved wizard edits and retained per root. Catalog status is configuration inventory, not observed Azure deployment.

Factory, scale-set and project IDs identify the scope; a friendly name or map region is insufficient. Existing identities and project placements are immutable in these editors. Configuration drafts, scoped settings and runtime previews must not overwrite the source factory or the legacy root variable files as a side effect.

**Prepare review — no changes yet** obtains the server plan. Open **Review exact scope, revision, version, effects and resource manifest**, inspect warnings/blockers, and explicitly accept before **Confirm reviewed plan**. Consent is bound to that root, revision, identity, inputs, authentication context and expiry. Edits, reloads or scope changes require a fresh review; submission uses the server receipt, not a silently rebuilt request.

### New factories, scale sets and project placements

Status: Under development

- **New factory draft** supplies destination prefix/region, saved release and initial scale-set configuration. A new configuration is not a deployed factory.
- **Create scale-set configuration** stays in the selected factory's region. Select Dev, Stage or Prod explicitly, a unique nonzero three-digit suffix, subscription/tenant, ADO/GHA route, VNet CIDR and maximum projects from 1 through 8. No initial project is added or deployed.
- Optional custom common-subnet configuration requires all four CIDRs: common, scoring, Power BI and Bastion. The server validates containment, overlap and real allocator capacity; existing networks are not resized.
- **Add a new project** takes a nonzero three-digit project number, display name and explicit per-environment placements. Number uniqueness/capacity are checked per physical scale set.
- **Add existing project placements** adds missing environments to the selected project. Existing placements cannot be retargeted here; Dev is never implicitly mapped to Stage or Prod.

These actions save configuration only. Use a separate runtime deployment review, or **Full bootstrap** when common infrastructure plus an initial project is actually intended.

### Clone configuration

Status: Under development

Select an exact source factory, choose the destination prefix and canonical Azure region, and choose **No projects (configuration only)** (`none`, the default) or **All project configurations** (`all`). There is no implicit partial-project selection. A blank clone release inherits the source's saved release; an explicit override belongs to the new factory.

Clone copies configuration, not Azure resources, deployment status, resource ownership, data or model weights. Source configuration and wizard edits remain unchanged. Review inherited networking, identities, pipeline bindings and target-specific dashboard settings before any separate deployment. The older configuration-setup detail screen likewise saves an independent configuration; **Open saved configuration** is a separate switch, not an automatic replacement of the editor.

### Scoped settings

Status: Under development

Choose **Edit scoped configuration settings**, then Selected factory, Selected scale set, or Selected project. **Load or reload scoped settings** retrieves that exact scope and revision. Project settings apply across its existing placements; unset child values continue to inherit.

Search the allowed settings and change only server-whitelisted, non-secret scalar values. Only changed values are submitted; untouched inherited settings are not flattened into overrides. This is not an identity, placement, credential, release-version or network-address editor, and it does not update the legacy root or deploy resources.

Revision conflicts retain the draft but block stale submission. Reload/reconcile deliberately, then prepare and review again. Automated editor tests cover isolation and changed-value submission; backend integration remains a prerequisite for using these saves.

### Pipeline bindings, identities, runners and locks

Status: Under development

**Configure pipeline binding and locks** stores references for the chosen ADO/GHA route: consumer repository/ref, enrolled physical writer, authentication namespace/principal, explicit Linux runner, distributed-lock enrollment and exact writable/read-only dependency resource-group ARM IDs. The consumer ref is independent of the AI Factory release.

Choose a hosted Ubuntu image, GitHub self-hosted Linux labels, or Azure DevOps Linux pool/optional agent. Runtime workers are not inferred from the Windows desktop. A shared-remote binding may override the writer, identity and runner together for one exact scale set while preserving other targets. An unreadable saved binding requires explicit whole-binding replacement.

Lock storage, coordination document/hash/revision, identities and permissions must already be provisioned/enrolled. Saving references does not sign in, create a runner, grant ownership or prove runtime connectivity. Names, regions and wildcard filters do not authorize writes; inspect the complete binding and server blockers before consenting.

### Legacy-root compatibility and migration

Status: Under development

Without a catalog manifest, the API reports legacy mode. **Continue in legacy configuration wizard** keeps the existing workflow; opening/reloading a catalog never migrates it automatically. **Review explicit legacy migration** is a separate prepared and confirmed change. A genuinely empty root can instead create a new factory when the server permits it.

Legacy configuration loading uses the current `factory_state.json` when available, otherwise root `variables.json` or the current orchestrator's variable file. Historical project/scale-set snapshots remain loadable but do not broaden Azure query scope. Once a root is catalog-backed, legacy AI Factory, Monitoring, Projects and Scale sets navigation may redirect to exact catalog selection rather than operate against unscoped root files.

### Common-only deployment and exact deletion

Status: Under development

**Deploy selected scale set** defaults to **common only**. To deploy a project, explicitly enable the project choice and select exactly one project already placed in that scale set. Full bootstrap is different: it creates common infrastructure and an initial project.

**Delete selected scale set** targets the exact environment/suffix/subscription/tenant identity. **Delete selected factory** covers the entire selected factory, including all scale sets in the server-owned resource manifest—not just the highlighted scale set. Both require an unblocked runtime preview, inspection of exact resources/dependencies, acceptance and the displayed typed deletion phrase.

Azure deletion is irreversible and distinct from **Delete config** on saved snapshots. A region, name match or imported report is not ownership evidence. Runtime capability, credentials, enrolled locks, immutable reviewed source/configuration and the exact manifest must be verified by the server. Unit tests of confirmation logic are not evidence that deployment/deletion has completed end to end in Azure.

**Reload jobs** inspects server-owned outcomes; **Open interactive terminal** is enabled only for an available owned job. Failed, interrupted or uncertain results require inspection before another operation. Transport failures do not cause automatic resubmission.

## AI Factory — environment board

Status: Under development

The compact Dev/Stage/Prod board aligns each project's environments in one row. Real cards come from observed or cached Azure resource groups, not configuration-only or mock inventory. Empty dotted placeholders are not selectable; under partial inventory they do not prove an environment is undeployed.

Select a card without loading its configuration. **Link to project RG** opens an observed group with the correct subscription/tenant, offering a chooser if several exist. **Plan to Stage** / **Plan to Prod** saves an independent, persistent **Not deployed** draft without changing the wizard or creating Azure resources. **Planning options**, including delete-project/delete-services switches, are planning controls rather than deletion execution.

**Update** reviews the same project in its existing environment; it is not promotion. **Deploy** reviews a draft. Inspect exact command, target, working directory, side effects, version and prerequisites before confirming. Compatible route-specific launchers live immediately above the consumer `aifactory` folder. Depending on the reviewed script, execution can refresh templates, stash changes, commit/push and start billable deployments.

### Versions and Patch

Status: Under development

The consumer repository branch, saved factory release and optional runtime template override are separate choices. Examples are `124` for `release/v1.24`, `125` for `release/v1.25`, dotted releases, and `main`. There is no universal `124` default across all workflows.

On the environment board, omitting the optional override lets **Patch** use `main`; with Patch off, installed code is preserved and must be verified. **Patch** is unchecked by default and passes `--project-only`; checking it allows the shared-template refresh. Planning carries the choice but does not upgrade anything.

In **Manage factories**, runtime **Inherit selected factory release** submits no override; the server resolves the saved release. An unresolved legacy release requires an explicit choice. New-factory and clone saved-release inputs are separate from runtime overrides.

Preparation resolves the source to an exact published commit for review. Version/Patch edits invalidate consent; confirmation must not change the code selector or silently accept an API that ignored it. Patch-disabled deployment must not pretend a requested different release was installed.

### DataOps, MLOps, RAG and fine-tuning

Status: Under development

The corresponding project-card buttons open project/environment-specific operation configuration detail pages. They provide typed fields, choices and guidance for data ingestion, machine-learning, retrieval-augmented generation and fine-tuning settings. **Save** persists the operation configuration; **Back** returns to the board.

These forms are not proof that a pipeline, training job, index build or fine-tune ran. Review the chosen project/environment and data-source/model settings and use the appropriate separately configured execution path.

### Interactive terminal and outcome review

Status: Under development

On Windows the shared footer hosts a real Git Bash ConPTY session with bundled xterm.js. **Open terminal** reopens the selected job; type into prompts, select/copy output, resize or send Ctrl+C. Collapsing the footer or navigating away does not stop the job. Only the reviewed script is launched, not an unrestricted parent shell.

Terminal output/input are bounded in-memory data, not durable logs. API restarts or expired scrollback can leave output unavailable. Connection loss disables typing until an explicit reconnect; uncertain input is not resent automatically.

Running/awaiting-confirmation indicators are not deployment proof. A successful script exit still needs Azure inventory confirmation; partial resource creation must not hide a known failure. For failed/interrupted jobs, **Review outcome** and **Acknowledge reviewed outcome** release only the reviewed job's repository hold. Acknowledgement does not roll back, retry, clear the failure or make that failed draft deployable again.

## Projects

Status: Under development

**Show saved** lists project snapshots from known folders. Use factory/scale-set, environment and owner filters, and select a row for its gradient highlight. Selection alone does not load a project. **Load** explicitly restores the exact folder/snapshot into Configuration wizard; stale paths or intervening editor changes must be rejected.

**Link to RG** uses observed project groups, with a chooser for multiple matches. **Accessible** requires a fresh authenticated HTTP 200 and matching identity for every linked group; a Portal URL or inventory entry alone is insufficient. This is resource-group access, not application health. **Not deployed** requires complete inventory, while unchecked/failed access remains unknown.

**Delete config** requires confirmation and deletes only that saved snapshot. Azure resources, exported variable files and the current editor are unchanged. **Create ticket** opens an unsaved ticket draft, offering only matching observed groups; when none exists, paste a group name yourself rather than accept a guessed name.

## Scale sets

Status: Under development

**Show saved** lists reusable shared subscription, network, region and common-resource settings across known folders. **Load** selects the exact saved scale-set configuration. **Link to RG** uses only matching observed **common** groups, never another scale set's group or a project's group.

Access lights follow the same authenticated identity/HTTP checks as Projects; every linked common group must pass. **Refresh Azure** rechecks access, while simply reopening **Show saved** reuses verified results.

**Delete config** removes only the confirmed saved scale-set snapshot, preserving common Azure resources, projects, root variables, exports and the editor. **Create scale-set configuration** opens the catalog draft flow; **Full bootstrap** is the separate common-plus-initial-project creation workflow.

## Tickets

Status: Under development

The **Tickets** tab lists your own tickets across factories. Create **Request Azure service** or **Bug report** tickets, with separate **minor / major / blocker** severity and **New / Active / Solved** status. Azure sign-in is required to save; the API assigns ownership.

Paste a project resource-group name and choose **Extract details** (or Enter). The naming parser supplies project, environment, region, factory prefix and suffix/scale-set context; cost center and department are optional. Parsing is not a deployment/access check. Project/Wizard **Create ticket** shortcuts open an unsaved draft and require consent before replacing draft edits.

Creating or updating a ticket saves it in the backend only. It does not send an email or submit to Jira/ServiceNow.

### Ticket Connections and external sync

Status: Under development

The **Ticket Connections** tab stores per-user Jira/ServiceNow profiles. Tab changes preserve drafts, selections and errors; **Reload** is explicit. Enter the provider's HTTPS URL and required account/project metadata plus `credential_env`: the name of an environment variable on the Python API host, never its secret value.

Saving a profile is not a successful connection or credential test. The host administrator must configure credentials and any approved custom-host allowlist; default destination restrictions and Azure identity/factory authorization still apply.

Select a ticket/profile, save pending status/severity changes, then **Preview external sync — no send**. Review the exact **WHO** and **CONTENT** before **Confirm and send this exact content**. This manual action can disclose owner, factory, project and description data to the chosen provider. Selection/scope changes invalidate the preview. On uncertain failure, inspect the external outcome before preparing another send; there is no background synchronization.

## Connection

Status: Under development

The Windows installation starts the bundled local Python API on an available loopback port and updates its connection automatically. A standalone API commonly uses `http://127.0.0.1:8765`. Use **API base address**, **API key** and **Connect & open wizard** when configuring the connection explicitly. The key is kept in platform secure storage, not in source code.

**Open live Swagger** and **Open OpenAPI JSON** describe the running API, not a guaranteed newer contract. Rebuild/restart an older API when required endpoints are missing. **Copy key for Swagger** is an explicit secret-copy action; authorize in Swagger and protect the clipboard. Trying creation/deployment endpoints can change files or Azure resources.

Mobile targets need a reachable authenticated HTTPS companion API: `127.0.0.1` on a phone means that phone. Do not expose the loopback HTTP service to an untrusted network. Remote/mobile authentication and cloud operations are not certified by the Windows setup exercise.

### Azure login and shared refresh

Status: Under development

**Login to Azure** is available at the menu bottom and footer. The Python API verifies Azure CLI authentication; a cached account name is not enough. When required, select a tenant and explicitly start browser sign-in on the API computer. **Logout** requires confirmation because it signs out the shared Azure CLI session, potentially affecting other tools. Neither action grants roles or signs out Microsoft 365.

The active app checks authentication periodically; a timer does not open a login browser. Verified login triggers the shared refresh without resetting wizard edits. **Refresh Azure** collects current/recent factory folders independently, deduplicates them and keeps their tenant/subscription/regional scopes separate. Navigation does not duplicate or cancel collection.

The footer shows progress, completion time and warnings: cyan while refreshing, green only after complete success and access checks, amber for partial/cached/unavailable/unverified data, and red for failure. **!** reopens messages without querying Azure again. **View / copy** exposes the complete message; dismissing/fading a toast does not resolve its underlying error.

## Appearance

Status: Tested

Select **System**, **Light** or **Dark**; the theme applies immediately and is saved locally on the device. **Animate status lights** disables decorative pulses/rotating highlights without changing data, refreshes or configuration. Windows animation preferences are respected; inactive views/windows stop their animations.

Local coverage includes `ThemePaletteCatalogTests` and `StatusLightMotionPolicyTests`. Colors and motion are presentation aids, not guarantees of freshness, authentication or Azure service health.

## About

Status: Finished

The read-only About view explains the architecture: **MAUI** handles presentation, navigation, device storage and file selection; **ESAIF.DomainLayer** supplies typed API contracts; **ESAIF.BaseLayer** supplies transport/MVVM primitives. The **Python API** remains authoritative for defaults, mappings, validation, import/export, projects and scale sets.

This informational page has no deployment, credential-management or resource-deletion action.
