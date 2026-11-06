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

### Subnet calculation and Az.Network assembly conflicts

The v1.24 ADO task `04_pwsh_calculate_subnet_allocations` runs PowerShell Core
under `AzureCLI@2` with the existing environment service connection. It sets the
internal `AIFACTORY_USE_AZURE_CLI=true` flag so `subnetCalc_v2.ps1` reads the VNet
through `az network vnet show` with an explicit subscription. Only the pinned
`Subnet` arithmetic dependency is imported; no Az PowerShell modules are loaded.

This avoids mixing task-preloaded Az assemblies with the helper's pinned
Az.Network version, which can fail with "Assembly with same name is already
loaded". Do not work around this by changing VNet names/CIDRs or force-loading
more Az versions. Allocation rules, generated `subnetParameters.json`, GitHub's
CLI path and explicit legacy Az-context execution remain unchanged. Failed VNet
reads still stop the task; the calculation performs no Azure writes.

Consumers need both the fixed submodule revision and the refreshed
`esml-infra-project\jobs\job-1-genai-networking.yaml` on their published branch.
Copying only the YAML or rerunning an old pipeline commit does not install the
script/helper fix.

### Project storage and Key Vault RBAC reconciliation

The project infrastructure phase grants the project user-assigned managed identity
Storage Blob Data Contributor on the secondary (`2001`) storage account even when
Logic Apps owns its primary-account assignments. This repair leaves the existing
primary assignments and the legacy `updateRbac` / `skipExistingRoleAssignments`
suppression gates unchanged. Use task `100-rbac-security` with `updateRbac=false`.

For an existing project vault, task `62-core-infrastructure` reconciles user/group
roles when `updateKeyvaultRbac=true`, without recreating that vault. The default
role remains Key Vault Secrets User (read-only). Explicitly set
`keyVaultSecretsOfficerForUsers=true` to select Key Vault Secrets Officer instead.
Both ADO and GitHub forward this opt-in and the selected user/group principal type.
Existing Secrets User assignments are not deleted by the incremental deployment.

The affected users/groups come from `technical_admins_ad_object_id`;
`use_ad_groups=true` identifies them as groups. Verify these object IDs rather than
assuming that changing an update flag selects a different group.
`disableRBACAdminOnRGForUsers=false` enables the existing constrained RG-level RBAC
Administrator assignment. Its condition still prohibits granting Owner, User Access
Administrator, or RBAC Administrator; it is not unrestricted role administration.

The deployment service connection must already be authorized to create every role,
including that constrained RBAC Administrator assignment. These settings cannot
bypass Azure Policy, deny assignments, or the deployment principal's ABAC conditions.
Run the project pipeline for the intended environment, not the common pipeline.
The stock project pipeline is not RBAC-only: review its other enabled tasks first.
Consumers need the updated submodule pin and the matching services-job YAML, plus
their explicit configuration values. No runtime permission change is proven by a
successful local build.

> [!TIP]
>  A quicker & easier way? You can use the AIFactory Github Template repository to get a bootstrappd repo quickly (as a mirror repo, or "bring your own repo"). [AIFactory Template Repo](https://github.com/jostrm/azure-enterprise-scale-ml-usage), ready to run. All files copied already. Just configure and run.
>