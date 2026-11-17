# AI Factory in Terraform

The same infrastructure and behaviour as the Bicep templates in `../bicep`, in Terraform. It is ported one
slice at a time. Each slice has to keep the same resources, names, conditions and outputs as its Bicep, and
tests check that.

| Slice | Bicep | Terraform | Status |
|---|---|---|---|
| 1. Common foundation | `bicep/esml-common/main/11-rgCommon.bicep`, `12-networkCommon.bicep`, `13-rgLevel.bicep` and the 41 modules they reach | `esml-common/` + `modules/` | **Done (v1.26)** |
| 2. Project stack `esml-genai-1` | `bicep/esml-genai-1/01`-`11` | | Next |
| 3. AI gateway (APIM), Kong, FinOps, policies, dashboards | `bicep/esml-common/ai-gateway`, ... | | Later |

Until a slice is done, its part of the factory is deployed with Bicep. The factory foundation from Terraform
and the projects from Bicep work together: both use the same names.

## Choose Terraform: the `iac` switch

`iac` in the factory configuration (`variables.json`, `dev`) picks the tool for the factory foundation:
`"iac": "bicep"` (the default) or `"iac": "terraform"`. Set it before the factory is first deployed; one tool
per factory, because switching needs a `terraform import`. A new scale set takes the factory's `iac`.

```json
"iac": "terraform",
"tfstateResourceGroup": "rg-aif-tfstate-sdc-001",
"tfstateStorageAccount": "staiftfstatesdc001",
"tfstateContainer": "tfstate",
"tfstateSubscriptionId": ""
```

| Key | GitHub variable of `infra-common-terraform.yml` | Default |
| --- | --- | --- |
| `tfstateResourceGroup` | `TFSTATE_RESOURCE_GROUP` | required with Terraform |
| `tfstateStorageAccount` | `TFSTATE_STORAGE_ACCOUNT` | required with Terraform |
| `tfstateContainer` | `TFSTATE_CONTAINER` | `tfstate` |
| `tfstateSubscriptionId` | `TFSTATE_SUBSCRIPTION_ID` | the target subscription |

With the Factory API (`esaf.init_factory(..., iac="terraform")`, `azurefactory esaf init-factory --iac terraform`),
the API installs `infra-common-terraform.yml` instead of `infra-common.yml`, sets those GitHub variables and runs
the factory common through the pipeline route. It refuses Terraform with Azure DevOps (only a GitHub Actions
template exists), with an accelerator that has no Terraform template (before v1.26), without the two required
state keys, or for a factory that already uses the other tool. Projects stay on Bicep until the Terraform
project slice ships. Deleting a scale set or the factory also removes its state blobs
(`aifactory/<subscription>/<common resource group>/...`). Keep the state account outside the factory, so it
survives the factory's deletion, and give the deployment identity `Storage Blob Data Contributor` on it.

## Layout

```
terraform/
  esml-common/            root module: one state per factory and environment
    config.tf             reads variables.json once and builds the parameters of 11, 12 and 13
    main.tf               stage_11 -> stage_12 -> stage_13, in the order infra-common.yml runs them
  modules/
    stage-11-rg-common/       11-rgCommon.bicep      (parameters.tf generated from the Bicep parameters)
    stage-12-network-common/  12-networkCommon.bicep
    stage-13-rg-level/        13-rgLevel.bicep
    naming/                   the Bicep naming convention, the only place names are built
    common-scopes/            private DNS and own-hub scopes of 13 (the root also uses it for providers)
    arm-unique-string/        ARM uniqueString() in plain Terraform (generated)
    <one module per Bicep module>   e.g. key-vault <- modules/keyVault.bicep
  parity_map.json         Bicep resource type@apiVersion -> Terraform resource; Bicep file -> module
  tools/                  generators of arm-unique-string/main.tf and stage-*/parameters.tf
  copy_to_local_settings/github-actions/infra-common-terraform.yml
```

**One root, not three.** 11, 12 and 13 all deploy at subscription scope into the same subscription, in a
fixed order. One root gives one plan, one state, and dependencies that Terraform orders by itself. Three roots
would need a state per stage and data lookups between them. Nothing (scope, provider or ordering) needs
separate roots. Each Bicep entry file is one stage module, called the way the workflow calls the template:
stage 12 runs only when `runNetworkingVar != 'false'` and `BYO_subnets != 'true'`, like step 02.

Each stage module takes one object, `parameters`, whose attributes are the Bicep parameters: same names, types,
defaults and allowed values. `tools/generate_stage_parameters.py` generates it from `bicep build`. Each stage
has a `deploy` map with one entry per Bicep `module` symbol. That entry is the Bicep `if`, and it is the only
`count` of the matching Terraform module.

## Providers

| Provider | Version | Used for |
|---|---|---|
| `hashicorp/azurerm` | 5.12.0 | Every resource with a 1:1 GA resource that can express what the Bicep sets |
| `azure/azapi` | 2.13.0 | The exact ARM type and API version of the Bicep, where azurerm cannot: see `reason` in `parity_map.json` |
| Terraform | >= 1.11 (CI: 1.17.1) | Write-only attributes and ephemeral values keep secrets out of plan and state |

The root pins exact provider versions; modules accept `>= x, < next major`. `parity_map.json` maps all
51 resource types (type@apiVersion) of the 11/12/13 closure: 31 to azurerm, 20 to azapi. Three of the azapi
ones use `azapi_update_resource`, because the resource always exists already: the Defender plans and the lake's
`default` blob and file services. They are PUT like the Bicep does and never deleted. Two of the azurerm
entries also use azapi in one branch: the regional private DNS zone and link when `allGlobal` is false. Most
azapi cases are properties azurerm 5.12.0 cannot set, such as service endpoint locations,
`ignoreMissingVnetServiceEndpoint`, the ACR trust policy, a storage key policy or Defender extensions. The rest
are control-plane writes into private Key Vaults, and resources without a standalone azurerm resource.

Three ARM functions are reproduced exactly:

* `uniqueString()`: `modules/arm-unique-string`, MurmurHash64A in plain Terraform arithmetic. azapi 2.13.0's
  `provider::azapi::unique_string()` is not used: it differs from ARM for many inputs whose length modulo 8 is
  5, 6 or 7, because it takes the absolute value of a negative intermediate instead of its two's-complement
  bits. The tests compare this module with the Bicep compiler's own `uniqueString`, on more than 80 inputs.
* `guid(a, b, ...)`: `uuidv5("11fb06fb-712d-4ddd-98c7-e71bbd588830", join("-", [a, b, ...]))`. Role
  assignments get the same names as the Bicep gives them.
* `resourceId()` and `existing`: ids are built as strings. Nothing is read at plan time except the common
  service principal's object id in the seeding Key Vault (see Secrets).

## Inputs: variables.json, once

`esml-common/config.tf` reads the same `variables.json` the Bicep workflow reads. It merges the sections the
way `bicep/scripts/apply-json-config-overrides.py` does: `dev`, then `stage_prod` and `test`/`prod` for later
environments. It then builds the parameters of 11, 12 and 13 exactly as `infra-common.yml` builds their
`--parameters`. There is no second hand-kept list of settings.

The root's variables are only what the Bicep job takes from GitHub secrets, GitHub variables or its own steps.
`test_stage_parity.py` replays the Bicep workflow on the same file and checks that the parameters are equal.

| Variable | Bicep workflow source |
|---|---|
| `config_file`, `environment` | the `config_file` input; the job (dev, test, prod) |
| `subscription_id` | `vars.AZURE_SUBSCRIPTION_ID` (or `<env>_sub_id`) |
| `tenant_id` | `secrets.TENANT_ID` (the file's `tenantId` wins, as in the Bicep job) |
| `seeding_keyvault_subscription_id`, `seeding_keyvault_name`, `seeding_keyvault_resource_group` | `secrets.AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID`, `vars.AIFACTORY_SEEDING_KEYVAULT_NAME`, `vars.AIFACTORY_SEEDING_KEYVAULT_RG` |
| `cidr_range`, `network_env` | `vars.CIDR_RANGE`; the "Initialize derived variables" step |
| `technical_admins_ad_object_id`, `technical_admins_email`, `ip_whitelist` | `secrets.PROJECT_MEMBERS`, `vars.PROJECT_MEMBERS_EMAILS`, `secrets.PROJECT_MEMBERS_IP_ADDRESS` |
| `admin_vm_exists`, `admin_password`, `key_vault_secret_expiry` | `admin-vm-exists.sh`; generated per run; `utcNow() + 1 year` |

## State

Backend `azurerm`, configured by the workflow (`-backend-config`). State lives in a storage container named by
the GitHub variables `TFSTATE_RESOURCE_GROUP`, `TFSTATE_STORAGE_ACCOUNT` and `TFSTATE_CONTAINER` (default
`tfstate`), plus `TFSTATE_SUBSCRIPTION_ID` (default: the target subscription). The key is
`aifactory/<subscription>/<common resource group>/<environment>/esml-common.tfstate`: one state per factory, scale
set and environment, also when `commonResourceGroup_param` is the same for every environment. The repository never holds state;
`.gitignore` excludes it.

## Secrets

* The admin VM password goes into the VM request and the Key Vault secret as write-only attributes
  (`sensitive_body`). It is not stored in state.
* `kvSecretsCmn` copies the common service principal from the seeding Key Vault into the common vault. It reads
  the values with ephemeral `azurerm_key_vault_secret` resources and writes them as write-only attributes, so
  they never reach the plan or the state. The Bicep resolves `getSecret()` inside ARM. Terraform reads the data
  plane instead, so the deployment identity needs `Key Vault Secrets User` on the seeding vault, and the vault's
  firewall must admit the runner. This applies only when the three `*Key` settings name real secrets, not
  `<optional>`.
* The Log Analytics shared key is an attribute of the workspace resource and is in state, as in any Terraform
  configuration of a workspace. Protect the state container (private endpoint or firewall, RBAC, no shared keys).

## Differences from the Bicep deployment

* **Existing factories.** Terraform manages only what its state holds. A factory first deployed with Bicep has to
  be imported (`terraform import`, or `import` blocks) before Terraform takes it over. Otherwise the first apply
  fails on resources that already exist. This slice targets new factories. Import support is a candidate for
  slice 2.
* **Removal.** Bicep `if` and `for` never delete. In Terraform, a setting that turns a module off destroys what it
  had created. Plans are printed before apply: read them.
* **Admin VM.** As in the Bicep, an existing VM is never PUT again (`admin_vm_exists`). A VM this state created
  ignores later changes to its own definition.
* **Deployment names.** ARM deployment names, such as `uniqueDetermenistic` in 12, have no Terraform
  counterpart. Resource names are identical.
* **Shared quirks.** Behaviour the Bicep has today is kept on purpose, for example the admin VM secrets expiring
  on 2025-01-10, or AMPLS sent with a regional location. Fix them in both places together.

## Tests

`environment_setup/unit-tests/test-terraform` (CI job "Terraform" in `.github/workflows/infrastructure-tests.yml`,
on Ubuntu and Windows). It runs offline, with no Azure login: `terraform fmt`, `init -backend=false` and
`validate`, plus `terraform console` against `bicep build` and `bicep build-params` output. It checks:

* the parity map: every Bicep resource type of the closure is mapped and implemented;
* names: `uniqueString`, the common resource group, Key Vaults, lake, ACR, Log Analytics, ADF, VM, vNet;
* parameters: Terraform equals the Bicep workflow replayed on the same variables.json;
* conditions: every Bicep module `if` equals its Terraform `count`, across scenarios that turn every condition
  both on and off;
* the GitHub Actions template mirrors `infra-common.yml`.

Regenerate the generated files after changing the Bicep parameters or the hash generator:

```bash
python environment_setup/aifactory/terraform/tools/generate_stage_parameters.py
```

```bash
python environment_setup/aifactory/terraform/tools/generate_arm_unique_string.py
```
