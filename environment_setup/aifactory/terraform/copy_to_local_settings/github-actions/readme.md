# GitHub Actions: Terraform

## infra-common-terraform.yml

Deploys the AI Factory common foundation (what `infra-common.yml` deploys with `11-rgCommon.bicep`,
`12-networkCommon.bicep` and `13-rgLevel.bicep`) with the Terraform root
`environment_setup/aifactory/terraform/esml-common`. Copy it into your repository's `.github/workflows/`, next to
the Bicep workflows. Run one or the other for a factory, never both.

It mirrors `infra-common.yml`:

* the same `workflow_dispatch` inputs (`deploy_dev`, `deploy_stage`, `deploy_prod`, `use_json_config_override`,
  `config_file`, `config_secret`, `deployment_id`, `config_hash`, `scale_set_suffix`);
* the same jobs, GitHub environments, OIDC `azure/login`, persona preflight, quota and policy preflight,
  required-configuration check, persona reconcile and region reports.

Only the three `az deployment sub create` steps are replaced:

1. **Set up Terraform**: `hashicorp/setup-terraform`, pinned to a commit, with Terraform 1.17.1.
2. **Terraform inputs**: runs the same encryption-at-host check as step 03. It sets the Terraform variables (the
   configuration file, and only what the Bicep job takes from secrets and GitHub variables). It authenticates the
   providers with the same identity (`ARM_USE_OIDC`).
3. **Terraform init (remote state)**: `azurerm` backend, key
   `aifactory/<subscription>/<common resource group>/<environment>/esml-common.tfstate`.
4. **01-03 terraform plan and apply**: the admin-VM check of step 03 (a VM this state already manages is kept,
   never treated as existing), a per-run admin password that exists only in this step, then
   `terraform plan -out=tfplan` and `terraform apply tfplan`, under the
   shared retry helper `bicep/scripts/modules/aif-retry.sh`. It retries transient ARM errors (throttling, 5xx,
   timeouts, dropped connections, `AnotherOperationInProgress`) with exponential backoff, at most 4 attempts.
   Every attempt plans again from the refreshed state, so a partly applied run continues where it stopped. A run
   still holding the state lock is waited for (`-lock-timeout=20m`).

All deployment inputs are read from the configuration file (`config_file`, default `aifactory/variables.json`;
the run-specific secret with `use_json_config_override`). In GitHub Environment mode the workflow loads that file
too, because Terraform does not read the per-setting GitHub variables.

## GitHub variables for the state

| Variable | Required | Meaning |
|---|---|---|
| `TFSTATE_RESOURCE_GROUP` | yes | Resource group of the state storage account |
| `TFSTATE_STORAGE_ACCOUNT` | yes | Storage account that holds the state (Entra ID auth, no shared keys) |
| `TFSTATE_CONTAINER` | no | Blob container, default `tfstate` |
| `TFSTATE_SUBSCRIPTION_ID` | no | Subscription of the state account, default the target subscription |

The deployment identity needs `Storage Blob Data Contributor` on the container. When the three common service
principal settings (`inputCommonSPIDKey`, `inputCommonSPSecretKey`, `commonServicePrincipleOIDKey`) name
secrets, it also needs `Key Vault Secrets User` on the seeding Key Vault: Terraform reads them on the data plane,
where the Bicep used ARM's `getSecret()`.

See `../../readme.md` for the design, the provider choice and the differences from the Bicep deployment.
