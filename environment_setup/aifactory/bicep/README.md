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

> [!TIP]
>  A quicker & easier way? You can use the AIFactory Github Template repository to get a bootstrappd repo quickly (as a mirror repo, or "bring your own repo"). [AIFactory Template Repo](https://github.com/jostrm/azure-enterprise-scale-ml-usage), ready to run. All files copied already. Just configure and run.
>