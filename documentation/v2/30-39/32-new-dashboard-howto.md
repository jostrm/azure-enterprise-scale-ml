# Get the new dashboards: How to

Use a manual Azure DevOps pipeline to create or refresh the common AI Factory
dashboard, Project001 dashboard and its My Project usage/cost workbook.

**This how-to uses the `release/v1.24` dashboard backport:** accelerator commit
`9d0df70f`, or a later revision containing it. Its YAML configuration support and
create-only mode must not be assumed available in other pipeline revisions.

Anonymized examples: repository `C:\code\customers\example\AIFactory`, branch
`prj001`, AI Factory project `001`, environment `dev`, ADO project `AIFactory` at
`https://dev.azure.com/example-org/AIFactory`. Substitute your own destinations.

**Order: safe configuration -> create project if needed -> dashboard plan -> dashboard deploy.**

## 1. Prepare the consumer repository

Commit and push a consumer submodule pin containing the v1.24 dashboard backport.
ADO runs that pinned version, not the newest local checkout.

For the existing-YAML route, use:

```text
aifactory\esml-infra\azure-devops\bicep\yaml\variables\variables.yaml
```

Before running the general infrastructure pipeline, confirm additive creation
settings rather than deletion settings:

```yaml
  project_number_000: "001"
  enableDeleteForDisabledResources: "false"
  deleteAllServicesForProject: "false"
  deleteKeyvaultAlso: "false"
  deleteAllForProject: "false"
```

Preserve your factory naming, region suffix, subscriptions and service settings.
Review, commit and push to `prj001`. No new mandatory dashboard variables or JSON
file are needed for this route.

## 2. Create Project001 only if it does not exist

Common factory infrastructure must already exist. New Azure AI Factory projects
need their resource group, identity, services and telemetry deployed first.
The dashboard pipeline cannot create them. No new Azure DevOps project is needed.

The general `infra-project-genai` ADO pipeline must already be registered against:

```text
aifactory\esml-infra\azure-devops\bicep\yaml\esml-infra-project\infra-project-genai.yaml
```

From the consumer repository root in **Git Bash**, run:

```bash
ADO_BRANCH=prj001 bash ADO-update-aifactory-and-run-project.sh --aifactory-version 124
```

Answer **No** to the JSON override prompt when using `variables.yaml`.
ADO organization/project come from saved settings, CLI defaults or prompts.
`ADO_BRANCH` avoids the launcher's default of `main`; it is separate from the
accelerator version `release/v1.24`.

The launcher refreshes templates, preserves/merges YAML values, asks before
committing/pushing, and queues Dev deployment, skipping Stage/Prod.
Review its changes and wait for success. `00-start.sh` with `a` only prepares
bootstrap scripts; it does not deploy the project.

`debug_disable_10_aifactory_dashboards: "true"` can remain true to skip the
normal project-dashboard task. A separate task may still update the common
dashboard; use the dedicated pipeline afterward for the new definitions.

## 3. Copy and publish the dashboard pipeline

Step 2 copies the pipeline into the consumer directory. Commit and push it:

```text
aifactory\esml-infra\azure-devops\bicep\yaml\esml-infra-project\infra-project-dashboards.yaml
```

**Existing project? Skip step 2.** From the repository root in **PowerShell**,
copy only the dashboard pipeline, then review, commit and push:

```powershell
Copy-Item `
  'azure-enterprise-scale-ml\environment_setup\aifactory\bicep\copy_to_local_settings\azure-devops\esml-yaml-pipelines\esml-infra-project\infra-project-dashboards.yaml' `
  'aifactory\esml-infra\azure-devops\bicep\yaml\esml-infra-project\infra-project-dashboards.yaml'
```

Retain `..\variables\variables.yaml`. Do not register the template directly from
the submodule: that would import template configuration, not consumer variables.

## 4. Register the pipeline and run a read-only plan

In Azure DevOps, select **Pipelines -> New pipeline -> Azure Repos Git ->
your consumer repository -> Existing Azure Pipelines YAML file**.
Choose `prj001`, select the copied dashboard YAML and save.
Authorize the existing service connection and agent pool if requested.

For the first run, use:

| Parameter | Example |
|---|---|
| Branch | `prj001` |
| `environment` | `dev` |
| `projectNumber` | `001` |
| `configurationSource` | `variables-yaml` |
| `mode` | `plan` |
| `planOperation` | `deploy` |
| `runnerSelection` | `from-config`, or a compatible available runner |
| `serviceConnection` | Empty uses the configured environment connection |

`projectNumber` must match `project_number_000`. YAML mode ignores `configFile`;
no JSON file is needed. Leave optional telemetry identity inputs empty unless
supplying known exact IDs.

## 5. Apply the new definitions

Review the plan's tenant, subscription and project resource group. Rerun with
the same inputs and **`mode: deploy`**.

| Mode | Behavior |
|---|---|
| `plan` | Read-only preview of `planOperation`; performs no Azure writes |
| `create` | Creates missing dashboards/workbook; skips each existing asset |
| `deploy` | Creates missing assets and refreshes existing definitions |

**Use `deploy` to upgrade existing dashboards.** `create` does not update an old
layout or add new project navigation to an already existing common dashboard.
For create-only planning, select `mode: plan` and `planOperation: create`.

Other projects' standalone dashboards and application services are not redeployed.
Common-dashboard project inventory is retained. Refreshing can replace manual
edits to the saved views.

## Prerequisites and boundaries

Project/common resource groups and the DEV common dashboard host must exist.
Application Insights, Log Analytics and managed identity must be discoverable.
The connection needs read and scoped dashboard/workbook/deployment write access,
including the DEV common host when targeting another environment.

Agents need Python 3.10+, PowerShell Core, Azure CLI and preinstalled Bicep.
Match the runner to the service connection: agent-managed-identity authentication
requires that identity. Hosted agents do not grant private-network access.

The dashboard pipeline provisions no infrastructure, diagnostics, identities,
roles or networking. Missing telemetry/access remains unavailable, not zero.
Avoid concurrent writers: project/workbook ARM creation is not atomic create-only;
common-dashboard creation has conditional-write protection.

After success, refresh Azure Portal. Charts still need actual telemetry and access.

See [AI Factory monitoring](32-dashboards.md#dashboard-only-ado-and-github-actions-workflows)
for the broader monitoring architecture. The backport uses isolated
`modules\dashboard-only` assets, preserving normal v1.24 infrastructure templates.
