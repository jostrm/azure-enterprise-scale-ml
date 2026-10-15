# Update existing AI Factory
There are two types of updates you can do: `Library-UPDATE` or `Feature-UPDATE`.

For a `Feature-UPDATE`, you can use a **Quick Feature-update & run** script or follow the manual instructions in [2) Feature-UPDATE: NEW feature, such as "BYOVNet"](#2-feature-update-new-feature-such-as-byovnet).

## Manual Azure DevOps Run pipeline

When starting the existing `infra-project-genai` pipeline directly in ADO using
`variables.yaml`, select the intended **consumer branch**, for example `prj001`,
not `release/v1.24`. These settings are for the infrastructure pipeline, not the
separate dashboard pipeline:

| Field | Manual YAML run |
|---|---|
| Deployment mode (`deploymentTarget`) | `manual` |
| `deploymentProjectNumber` | `not-applicable` |
| `deploymentConfigHash` | `not-applicable` |
| `deploymentSettings` | Default `{}` |
| Build agent selection | `microsoft-hosted`, when compatible with connection/network |
| Override variables.yaml with variables.json | **Unchecked** |
| `configFile` | Default value; ignored with override unchecked |

Keep those nonempty defaults; do not clear them. ADO's Run UI rejects the earlier
empty-string defaults as missing required input. Publish the refreshed copied
pipeline if its UI still shows the old fields. `manual` maps internally to the
legacy empty target; existing API requests with an empty target remain supported.
`project_number_000` in the selected branch's YAML supplies the actual project
number, such as `"001"`; no reviewed hash is needed for this manual route.

**For Dev-only deployment, use Stages to run: select Dev GenAI Project only;
deselect Stage and Prod.** `manual` preserves promotion behavior. It does not
disable later environments if they remain selected. Hosted agents still require
a compatible service connection and sufficient network access.

The JSON checkbox and reviewed mode are independent. Choosing a reviewed target
`dev`, `stage` or `prod` still requires its protected JSON, real project number,
hash and scheduling settings from the reviewed launcher/API, even if the checkbox
is unchecked. Do not guess those fields or use `dev` as a shortcut for manual
Dev-only execution.

See [setup: manual ADO parameters](24-end-2-end-setup.md#manual-azure-devops-run-pipeline-variablesyaml).

## Manual GitHub Actions workflow

Choose the consumer branch and target `environment` in `infra-project.yml`.
Normal manual runs leave the optional `deployment_id`, `project_number` and
`config_hash` empty; GitHub does not need ADO's nonempty placeholders.
Clear `config_file` to use only existing GitHub Environment variables/secrets,
or keep its `aifactory/variables.json` default for a JSON override.

Reviewed runs require the complete protected-secret/project/hash/target contract.
Partial metadata no longer silently skips reviewed validation. GitHub subnet
allocation already uses authenticated Azure CLI, avoiding the ADO Az.Network
assembly-loading problem.

Update the submodule and re-copy **both** `infra-project.yml` and
`infra-project-phase.yml` into `.github/workflows`; updating only the submodule
does not refresh existing consumer workflow copies.
See [GitHub manual setup](24-end-2-end-setup.md#manual-github-actions-project-run)
and the [workflow input guide](../../../environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/readme.md#manual-inputs-and-subnet-authentication).

## Quick Feature-update & run

After `00-start.sh` has copied the scripts to your consumer repository root, run
the following from that root in **Git Bash**. The ADO example targets the
anonymized consumer branch `prj001` and stable accelerator version `124`; replace
`prj001` with your existing customer/project branch.

```bash
# Azure DevOps: consumer branch prj001, accelerator release/v1.24
ADO_BRANCH=prj001 bash ./ADO-update-aifactory-and-run-project.sh --aifactory-version 124

# GitHub Actions
bash ./GH-update-aifactory-and-run-project.sh
```

These scripts replace the manual feature-update steps below. They protect existing work, update the AI Factory submodule and templates, merge the existing configuration into the latest templates, commit and push the changes, start the project pipeline or workflow, and monitor the run until it finishes.

### ADO_BRANCH: when it is needed

**`ADO_BRANCH` is optional only when the intended consumer branch is `main`, or
the correct value is already exported in your shell. For any other consumer
branch, explicitly set it.** The legacy ADO launcher uses
`BRANCH="${ADO_BRANCH:-main}"`: it does not infer the branch from your current
Git checkout, project number, `variables.yaml` or `variables.json`.

In a normal update, this branch controls checkout/pull, the destination of an
approved commit/push, and the branch used for pipeline preview and execution.
Without an override, running the script while checked out on `prj001` can still
switch to and deploy from `main`. Ensure the intended branch already exists
locally and on the consumer's `origin`.

| Selector | Meaning | Example |
|---|---|---|
| `ADO_BRANCH` | Customer/consumer repository branch | `prj001` |
| `--aifactory-version` | Accelerator submodule code/templates | `124` selects `release/v1.24` |
| `project_number_000` | Azure AI Factory project number in the selected configuration | `"001"` |

The branch name does not set the project number or choose Dev/Stage/Prod.
`ADO_BRANCH=prj001` is a one-command environment assignment; a separate `export`
is unnecessary and the value does not persist in your shell.
The old command `bash ./ADO-update-aifactory-and-run-project.sh` remains valid
when `main` is the intended consumer branch; it leaves version selection to the
launcher's normal saved/default version rules.

These branch-override instructions apply to the **legacy Dev/YAML update and
project-only flow**. Reviewed deployments retain their published exact-target
contracts: the reviewed helper requires the published consumer `main`, not an
arbitrary project-branch override.

### Select JSON override without the terminal prompt

For the legacy Dev update flow, set `AIFACTORY_USE_JSON_OVERRIDE` to answer the
JSON-selection question in advance:

```bash
# Use aifactory/variables.json as the deployment override; do not ask that question
AIFACTORY_USE_JSON_OVERRIDE=yes ADO_BRANCH=prj001 bash ./ADO-update-aifactory-and-run-project.sh --aifactory-version 124

# Use variables.yaml instead; do not ask that question
AIFACTORY_USE_JSON_OVERRIDE=no ADO_BRANCH=prj001 bash ./ADO-update-aifactory-and-run-project.sh --aifactory-version 124
```

These anonymized examples run from the consumer repository root in Git Bash.
Replace `prj001` with your existing consumer branch. `yes` requires the intended,
valid `aifactory/variables.json` to exist; it does not generate the configuration.
`no` keeps Azure DevOps on `variables.yaml`. When unset, the interactive launcher
asks which source to use.

**This skips only the JSON override question, not all interaction.** Sign-in,
destination/version questions, commit/push confirmation and deployment approvals
still apply where required. These inline assignments last for this command only;
no separate `export` is needed. Reviewed deployments retain their mandatory
protected configuration contract; `no` is not a way to bypass it.

### Add a project without updating AI Factory

When the existing submodule, templates, and pipeline are already the versions you
want, use `--project-only` to skip all update work and trigger the existing
project pipeline or workflow:

```bash
# Azure DevOps: trigger the existing pipeline from consumer branch prj001
ADO_BRANCH=prj001 bash ./ADO-update-aifactory-and-run-project.sh --project-only

# GitHub Actions
bash ./GH-update-aifactory-and-run-project.sh --project-only
```

This mode does not pull the repository or submodule, refresh or merge templates,
sync GitHub variables, create a commit, push, or run the Azure DevOps preview.
It preserves the normal authentication and optional `variables.json` override
flow, then dispatches the project deployment. For unattended execution, set
`AIFACTORY_PROJECT_ONLY=true`.

Both scripts ask `Do you want to override with variables.json? [y/N]` before starting the update unless `AIFACTORY_USE_JSON_OVERRIDE=yes` or `no` already supplies the answer. Enter `y` to pass `aifactory/variables.json` as the deployment override. Enter `n`, or press Enter, to pass an empty configuration path: Azure DevOps then uses `variables.yaml`, while GitHub Actions uses its configured variables and secrets without applying `variables.json`.

`useAdminVMBuildAgent` has been removed. Existing configurations must use `useSelfHostedBuildAgent` instead. The update scripts remove the deprecated key while merging configuration templates.

Before committing, each script prints only variable-schema changes: new variable names with their template default values and intentionally removed variables. It does not print a Git file-diff summary. If tracked files changed, the script asks `Commit and continue? [y/N]`. Enter `y` to commit, push, and start the pipeline or workflow. Enter `n`, or press Enter, to leave the changes locally and stop before push or dispatch.

When JSON override is enabled, the GitHub script asks `Update GitHub variables and secrets from .env? [y/N]:` before running the bulk uploader. Enter `n`, press Enter, or provide no input to skip `10-GH-create-or-update-github-variables.sh`; enter `y` to run it. For unattended runs, set `AIFACTORY_UPDATE_GITHUB_VARIABLES=y` or `n`. Without JSON override, the existing bulk synchronization behavior is unchanged.

Skipping bulk synchronization still uploads the selected JSON as **one** `AIFACTORY_CONFIG_JSON` environment secret and passes `aifactory/variables.json` as the GitHub Actions `config_file` input. The workflow restores that file from the secret, so the local configuration does not need to be committed. Existing GitHub authentication secrets must already be configured. This avoids uploading every JSON configuration value as a separate GitHub variable.

On the first Azure DevOps run, the ADO script prompts for your organization name or URL and project name, then saves them locally for future runs. Microsoft Entra ID is the default authentication method. The script reads `azureDevOpsTenantId` from `variables.yaml`, or from the `dev` section of `variables.json` when JSON override is enabled, and passes that tenant explicitly to every Azure CLI login and token request. It never attempts authentication against all available tenants. In the browser account picker, select **Use another account** and enter the account's full email address. No Azure subscription is required.

Before authentication, the legacy update flow shows the resolved organization and
project and asks **Do you want to override with a custom Azure DevOps URL? [y/N]**,
even when saved settings exist. Answer `y` and paste the full project URL, for
example `https://example-org.visualstudio.com/AIFactory` or
`https://dev.azure.com/example-org/AIFactory`. The launcher validates and replaces
both destination values, then saves them in `~/.aifactory-ado-settings.json` (or
`ADO_SETTINGS_FILE`). Enter/`n` retains the current destination. This fixes stale
organization/project defaults; it does not grant access or change the Entra
tenant. Noninteractive runs do not prompt and retain the existing environment ->
saved settings -> CLI defaults lookup. Reviewed routes keep their separate
exact-target authorization contracts.

`azureDevOpsTenantId` is the **Microsoft Entra ID directory connected to the Azure DevOps organization**. It can differ from `tenantId`, which is used for Azure deployments. The script generates a direct link using the organization name: `https://dev.azure.com/<organization>/_settings/organizationAad`. That link opens the Microsoft Entra settings directly. Alternatively, open the Azure DevOps organization, click **Organization settings** in the lower-left corner, then click **Microsoft Entra** in the left menu. Copy the **Directory (tenant) ID** into `azureDevOpsTenantId`. Tenant-specific values and PATs are never embedded in the script.

## Prerequisites: An existing AI Factory

### Reviewed single-project Stage/Prod deployment

The updated root launchers declare `# AIFACTORY_PROJECT_DEPLOYMENT_CONTRACT=1`.
Without the following opt-in inputs, their existing Dev/default and full-promotion
behavior is unchanged. A reviewed deployment supplies **all three**:

- `AIFACTORY_PROJECT_NUMBER`: selected three-digit project, for example `017`;
- `AIFACTORY_TARGET_ENVIRONMENT`: exactly `dev`, `stage`, or `prod`;
- `AIFACTORY_PROJECT_CONFIG`: absolute selected JSON export, or a factory/project/
  target-bound Windows current-user-DPAPI artifact produced by the local API.

`AIFACTORY_REPO_ROOT` identifies the consumer repository immediately above
`aifactory`. The MAUI/API confirmation supplies these values explicitly. Do not
set only a target on an old launcher: it cannot safely select isolated Stage/Prod.

The opt-in helper validates project identity and the exact target subscription
and tenant, with **no Dev fallback**. Stage uses `stage_prod.test_sub_id` and the
ADO `test` environment alias; Prod uses `stage_prod.prod_sub_id`. Deletion flags
are rejected. Existing GitHub environment authentication and ADO service
connections must match the selected target. The API currently blocks an ADO
organization tenant different from the Azure target tenant.

The helper snapshots reviewed code/configuration before refresh, restores the
reviewed launcher/helper and pipeline templates afterwards, and uses the selected
configuration in memory. Its interactive commit prompt stages only allowlisted
deployment code and the submodule pointer, never project exports. Declining
returns a nonzero result without dispatch. `--project-only` skips update/publish;
the reviewed workflow must already be installed and published on `main`.

GitHub receives a unique per-run environment secret; dispatch includes a UUID
in the workflow run name. The helper matches that UUID and the published commit,
watches the exact run, verifies its conclusion, and deletes the secret after
verified completion. If dispatch/completion is uncertain, it retains the secret
and fails for manual reconciliation rather than retrying or watching another run.
ADO receives the JSON as a protected per-run variable and watches the exact
returned run ID. Isolated Stage permits **skipped**, not failed/canceled, Dev;
isolated Prod permits skipped Dev and Stage. The legacy promotion DAG is unchanged.
Selected-project network/runner settings control ADO job scheduling even when
another project's export is currently loaded.

Pipeline jobs materialize the protected JSON only in their agent workspace and
remove it with always-run cleanup. A forcibly lost agent still needs workspace
review. The local API's derived artifact remains encrypted on disk/SQLite and
is decrypted only in process memory; raw interactive terminal output is RAM-only.
Pipeline completion is reported as submitted until Azure inventory confirms Active;
failed/interrupted jobs require reconciliation even when a partial resource group exists.

#### Files to install together in an existing consumer

Copy only through your normal reviewed local installation process. This source
change does not automatically modify a consumer or publish its repository.

| Canonical shared source | Consumer destination |
|---|---|
| `bootstrap/GH-update-aifactory-and-run-project.sh` | Root `GH-update-aifactory-and-run-project.sh` for GitHub |
| `bootstrap/ADO-update-aifactory-and-run-project.sh` | Root `ADO-update-aifactory-and-run-project.sh` for ADO |
| `bootstrap/lib/project_deployment.py` | Root `lib/project_deployment.py` |
| `environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project.yml` | `.github/workflows/infra-project.yml` |
| Same GitHub template directory: `infra-project-phase.yml` | `.github/workflows/infra-project-phase.yml` |
| `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/infra-project-genai.yaml` | `aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/infra-project-genai.yaml` |
| Same ADO template directory: `jobs/job-0-reviewed-project-config.yaml` | Same consumer pipeline directory: `jobs/job-0-reviewed-project-config.yaml` |

Keep the existing root `ui/terminal.sh` and normal bootstrap dependencies installed.
Install the helper plus both pipeline files for the selected provider; adding only
the marker is not sufficient. The confirmation blocks missing/stale capabilities.
The helper can publish the reviewed allowlisted code only after its explicit
terminal commit/push prompt. No deployment launcher should be run merely to test
this installation; use the offline contract fixtures.

[Prerequisites - End-to-end setup](./24-end-2-end-setup.md)


## 1) Library-UPDATE: Updated feature or bug fixes
Use this update type when a feature or bug fix does not change the pipelines or configuration files (`variables.yaml` or `.env`).

You can use the **Git** tab in VS Code to pull the `azure-enterprise-scale-ml` submodule, or run the following commands from your repository root in Git Bash or a similar terminal:

```
git config --system core.longpaths true
```

```
git submodule update --init --recursive --remote
```

**Option A)** To get a stable version (recommended), select a specific release branch:
```
git submodule foreach 'git checkout "release/v1.24" && git pull origin "release/v1.24"'
```

**Option B)**
To get the latest, potentially unstable features and fixes, select the `main` branch:
``` 
git submodule foreach 'git checkout main && git pull origin main'
```


**Finished!**

## 2) Feature-UPDATE: NEW feature, such as "BYOVNet"
Use this update type when a new feature changes variables or pipelines, such as BYOVNet, subnets, or personas.
For these features, the pipelines and variables may need to be updated.

<details>
  <summary><b>Azure DevOps: How-To</b></summary>

The following files will be updated by Bash scripts:
- Pipeline templates (`.yaml`) under `aifactory/esml-infra/azure-devops`
- `variables.yaml` under `aifactory/esml-infra/azure-devops/bicep/yaml/variables`


### A) Azure DevOps: How-To

1) Update the submodule in your repository.

    - Use the **Git** tab in VS Code to pull the `azure-enterprise-scale-ml` submodule, or run the following commands from your repository root:

    ```bash
    git submodule update --init --recursive --remote
    ```
    ```
    git submodule foreach 'git checkout "release/v1.24" && git pull origin "release/v1.24"'
    ```

2) Run the start script to copy the latest bootstrap scripts to your repository root.
    ```
    bash ./azure-enterprise-scale-ml/00-start.sh
    ```

3) Run the following script to update the Azure DevOps pipeline templates under `aifactory/esml-infra/azure-devops`.
    - It will not overwrite your `variables.yaml`. It creates `variables-template.yaml` next to it.
    - It will not overwrite your `parameters` folder.
    - **Warning:** If you have [extended AI Factory orchestration pipelines](./27-extend-AIF-pipelines.md), back up the folders under `aifactory/esml-infra/*`.

    ```
    bash ./03-ADO-YAML-bootstrap-files-no-var-overwrite.sh
    ```

4) Compare `variables.yaml` with `variables-template.yaml` using VS Code, GitHub Copilot, or another comparison tool.


**GitHub Copilot prompt**

`Compare aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml with the newer variables-template.yaml in the same folder. Copy all values from variables.yaml into the new variables-template.yaml. If some variables are similar but not exact, try to map them since they may have been renamed. There may be additional variables in variables-template.yaml. Afterward, rename variables.yaml to variables.bak and variables-template.yaml to variables.yaml.`

**Traditional compare tool**

    - Compare the files using a tool such as VS Code or Git, then configure any newly added variables.

**Finished!**

</details>

<details>
  <summary><b>GitHub Actions: How-To</b></summary>

The following files will be updated by Bash scripts:
- GitHub Actions workflows under `aifactory/esml-infra/github-actions`
- `.env` in your repository root
- Parameter files (`.json`) under `aifactory/parameters`, when required


### B) GitHub Actions: How-To

1) Update the submodule in your repository.
Use VS Code to pull the `azure-enterprise-scale-ml` submodule, or run the following commands from your repository root:

    ```bash
    git submodule update --init --recursive --remote
    ```
    ```
    git submodule foreach 'git checkout "release/v1.24" && git pull origin "release/v1.24"'
    ```

2) Run the start script to copy the latest bootstrap scripts to your repository root.
    
    ```bash
    bash ./azure-enterprise-scale-ml/00-start.sh
    ```

3) Run the Bash script to copy files from the submodule to `aifactory/esml-infra/github-actions/bicep` in your repository.
    
    ```bash
    bash 01-aif-copy-aifactory-templates.sh
    ```

4) Run the Bash script to update the pipeline templates under `.github/workflows` from `aifactory/esml-infra/github-actions/bicep`.
    - It will not overwrite your `.env`. It creates `.env.template` next to it.
    - It will not overwrite your `parameters` folder.
    - **Warning:** If you have [extended AI Factory orchestration pipelines](./27-extend-AIF-pipelines.md), back up the folders under `aifactory/esml-infra/*`.

    ```
    bash ./03-GH-bootstrap-files-no-env-overwrite.sh
    ```

5) Compare `.env` with `.env.template` using VS Code, GitHub Copilot, or another comparison tool.

**GitHub Copilot prompt**

`Compare the .env file in the repository root with the newer .env.template. Copy all values from .env into the new .env.template. If some variables are similar but not exact, try to map them since they may have been renamed. There may be additional variables in .env.template. Afterward, rename .env to .env.bak and .env.template to .env.`

**Traditional compare tool**

Compare the files, then configure any newly added environment variables.

**Finished!**
</details>