# Azure DevOps

Use the Azure DevOps consumer repository for this route; it is separate from a
GitHub repository. Maintain one complete project `variables.json` with `dev` and
`stage_prod`, or use ADO `variables.yaml`. See
[configuration and API](../parameters/index.md) and [all variables](../parameters/advanced.md).

## Create a new factory scale set

```bash
bash ./ADO-create-new-aifactory-scaleset.sh --repo-root "C:/work/my-ado-factory"
```

The source launcher is under `bootstrap/`; installed consumer copies may be at
the repository root. Normal full bootstrap prepares Azure identity, configuration,
repository/pipeline automation, common infrastructure and an initial project.
It can create billable resources and publish repository changes.

Use `--help` for the selected version. `--aifactory-version main` is explicit;
these create wrappers currently default to `main`. `--dry-run` collects and
validates answers without running the normal bootstrap mutations.
`--prepare-only` **does change Azure/identity/configuration**; it is not a preview.
For unattended operation, provide the documented inputs and established
authentication before using `--non-interactive --yes`.

## Update or run an existing project

From the selected ADO consumer repository:

```bash
# Refresh AI Factory/templates, then run the selected project pipeline.
bash ./ADO-update-aifactory-and-run-project.sh --aifactory-version main

# Preserve installed templates and run the project pipeline only.
bash ./ADO-update-aifactory-and-run-project.sh --project-only
```

Normal update defaults to `main`; project-only uses the installed source.
Scripts may prompt for configuration, commit/push or authentication. For API
automation, use the project plan/prepare/start contract, which binds the selected
project, environment, configuration and source version before execution.
Default waiting tracks the submitted run; a submitted pipeline is not yet a
verified deployed environment.

## Tenant and service-connection setup

`azureDevOpsTenantId` identifies the ADO organization tenant; `tenantId` identifies
the Azure deployment tenant. Do not change either ID merely to make them equal.
Cross-tenant reviewed execution needs the compatible organization-tenant
authentication helper and access in both contexts. A standard username-prefixed
ADO clone URL is not a reason to retarget the repository; never embed passwords
or tokens in its URL.

Configure service connections for each environment you actually deploy:

| YAML/JSON variable | Purpose |
|---|---|
| `dev_service_connection` | Dev deployment |
| `dev_seeding_kv_service_connection` | Dev seeding Key Vault access |
| `test_service_connection` | Stage deployment |
| `test_seeding_kv_service_connection` | Stage seeding Key Vault access |
| `prod_service_connection` | Prod deployment |
| `prod_seeding_kv_service_connection` | Prod seeding Key Vault access |

Connections must match the pipeline's authentication mode, subscription and
permissions. The same authorized connection may cover compatible duties; six
names do not necessarily require six distinct principals.
Local execution also needs Git Bash, Azure CLI with the required ADO extension,
and host Python.

The source
[`variables.yaml`](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml)
is copied to the consumer's
`aifactory\esml-infra\azure-devops\bicep\yaml\variables\variables.yaml`.
Project JSON overrides must use the matching pipeline adapter; do not rename
JSON keys to GitHub environment names.

For registered exact-scope operations,
`bootstrap/ADO-azurefactory.sh` consumes a trusted, protected reviewed manifest.
It does not initialize the register or bypass provider publication, service
connections, target-lock enrollment or approval.

!!! warning "Before execution"
    Keep launchers, helpers and YAML templates on a compatible published version.
    Protect populated project configuration and credentials. Run-specific secret
    transport is not permission to commit them to the repository.
