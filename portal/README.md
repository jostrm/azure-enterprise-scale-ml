# Deploy to Azure: AI Factory v1.25 Simple Mode full bootstrap

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#blade/Microsoft_Azure_CreateUIDef/CustomDeploymentBlade/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fjostrm%2Fazure-enterprise-scale-ml%2Fportal-125%2Fportal%2Fazuredeploy.json/uiFormDefinitionUri/https%3A%2F%2Fraw.githubusercontent.com%2Fjostrm%2Fazure-enterprise-scale-ml%2Fportal-125%2Fportal%2Fform.json)

Status: **proposed**. The package is tested offline only. It becomes supported after one confirmed deployment in a supported region.

The button deploys the default selection of the v1.25 Simple Mode preset (`private-ai-foundation-v2`, `SIMPLE_MODE_RESOURCE_CATALOG` defaults): private networking, standalone topology `s` with an integrated access hub, Dev only, and project 001. It skips the GitHub repository, OIDC and pipeline steps; the portal deployment runs the stages itself.

| Resource group | Contents |
| --- | --- |
| `rg-<prefix>-bootstrap-<loc>-<nnn>` | Seeding Key Vault shell (RBAC, purge protection, public access disabled). The stages still reference it; no secret is written to it or read from it. |
| `<prefix>-esml-common-<loc>-dev-<nnn>` | Common VNet 172.16.0.0/20 (integrated hub), private DNS zones and links, DNS Private Resolver inbound endpoint, Bastion Developer, IP group, common Storage, Key Vaults, Container Registry Premium, Log Analytics. Optional: VPN Gateway and Application Gateway. |
| `<prefix>-esml-project001-<loc>-dev-<nnn>-rg` | Project Storage, Key Vault, managed identities, Microsoft Foundry account and default project with the standard-agent capability host, AI Search (Basic, the v1.25 primary capacity SKU), Cosmos DB, optional Application Insights. |

The hub is **dedicated**: it is integrated into this factory's own common VNet and resource group (Simple Mode `AIF_ACCESS_HUB_MODE=integrated`). The button never peers to, links to or writes into another connectivity hub. v1.25 coordinates shared hubs through Blob leases (`bootstrap/lib/hub_lock_foundation.py`, container `hub-locks`), and an ARM deployment cannot take those leases. The third resource group is the bootstrap/seeding group.

## Not registered with the Factory API

A portal-deployed factory **cannot be registered with the Factory API** later. Registered (`azurefactory/register.json`) factories are created through registered creation and the Factory API, which owns catalog validation, naming and review. The in-repo SDK has no route to adopt an existing factory. `azurefactory enrollment` binds lifecycle runners to resource groups of a factory that is already in the catalog; it does not import one. Use the button for a standalone Dev factory. If you need API lifecycle operations, create the factory with `01-start-v125-and-above.sh` / the Factory API instead.

No model deployments are created. Add models after you have validated quota.

## Before you press the button

- Owner on the target subscription, or Contributor plus User Access Administrator. The stages create role assignments.
- An existing Microsoft Entra security group for the project team. Paste its object ID; the deployment never writes to Entra ID.
- Pick a region from the drop-down. The list is the intersection of the v1.25 CLI region table and Bastion Developer availability ([source](https://learn.microsoft.com/azure/bastion/bastion-sku-comparison#regional-availability)).
- Resource providers are registered automatically by ARM when the deploying identity may register them. If your policy blocks that, register `Microsoft.CognitiveServices`, `Microsoft.Search`, `Microsoft.DocumentDB`, `Microsoft.App`, `Microsoft.Network`, `Microsoft.KeyVault`, `Microsoft.Storage`, `Microsoft.ContainerRegistry`, `Microsoft.OperationalInsights` and `Microsoft.Insights` first.
- Application Gateway only: register the `EnableApplicationGatewayNetworkIsolation` feature. You also need a custom hostname, a private HTTPS backend and an exportable PFX certificate in an RBAC Key Vault in this subscription.
- Use a fresh prefix and scale set number. Like Simple Mode, the button expects a greenfield scale set (`*Exists=false`).
- Optional Simple Mode services that are off by default in v1.25 (Azure ML, AKS, Databricks, Data Factory, Event Hubs, PostgreSQL, Container Apps) are not offered in the button.

## Command-line equivalent (what-if first)

```bash
TEMPLATE=https://raw.githubusercontent.com/jostrm/azure-enterprise-scale-ml/portal-125/portal/azuredeploy.json
az deployment sub what-if --name aif-portal-001 --location swedencentral --template-uri "$TEMPLATE" \
  --parameters location=swedencentral prefix=<prefix> scalesetNumber=001 costCenter=123456 \
               teamGroupObjectId=<group-object-id> teamGroupName=<group-name> teamMemberEmail=<you@example.org>
az deployment sub create --name aif-portal-001 --location swedencentral --template-uri "$TEMPLATE" \
  --parameters location=swedencentral prefix=<prefix> scalesetNumber=001 costCenter=123456 \
               teamGroupObjectId=<group-object-id> teamGroupName=<group-name> teamMemberEmail=<you@example.org>
```

`--template-uri` is required: the stages are linked with `templateLink.relativePath`, which ARM resolves only relative to a template URI.

## After deployment: verification checklist

- [ ] The three resource groups above exist.
- [ ] `az network private-endpoint list -g <project-rg> -o table` shows endpoints for Storage, Key Vault, Foundry, AI Search and Cosmos DB, and `-g <common-rg>` shows the common endpoints plus `pend-<seeding-vault>-to-vnt-esmlcmn-...`.
- [ ] The Foundry capability host reports `Succeeded`: `az rest --method get --url "https://management.azure.com<foundry-account-id>/capabilityHosts?api-version=2025-04-01-preview"`.
- [ ] No public endpoints: `publicNetworkAccess` is `Disabled` on Foundry, AI Search, Cosmos DB, Storage and Key Vaults. The only public IP is the optional VPN Gateway's transport IP.
- [ ] `az deployment sub show -n aif-portal-001 --query properties.outputs` returns the resolver inbound IP and resource group names.

### One manual step the CLI pipeline runs (`100a_approve_AI_Search_shared_private_links`)

ARM cannot discover the names of pending private endpoint connections. Approve AI Search's shared private links on the Foundry account and on the project storage account `*2001*`:

```bash
for id in <foundry-account-id> <storage-2001-id>; do
  for c in $(az network private-endpoint-connection list --id "$id" --query "[?properties.privateLinkServiceConnectionState.status=='Pending'].id" -o tsv); do
    az network private-endpoint-connection approve --id "$c" --description "AI Search shared private link"
  done
done
```

## How the package is built

`portal/generate_portal.py` is offline and deterministic. It replays the stage parameters that the v1.25 workflows (`infra-common.yml`, `infra-project-phase.yml`) resolve for the Simple Mode preset: `apply_gha()`, then GitHub variables, then workflow job env, then the `variables.json` override, then each stage's `--parameters`. It uses tokens for deployment-time values and writes:

- `generated/stage-parameters.json`: every stage's parameters (constants, token templates, and the names `main.bicep` wires).
- `form.json`: the portal Form view (uiFormDefinition 2021-09-09) with subscription and region pickers.
- `stages/*.json` and `azuredeploy.json`, when run with `--bicep <bicep 0.37.4>`.

```bash
python portal/generate_portal.py --bicep /path/to/bicep-0.37.4      # regenerate
python portal/generate_portal.py --check                             # fail on drift
python -m pytest environment_setup/unit-tests/test-bicep/unit/test_portal_deploy_to_azure.py
```

| CLI/pipeline step | Portal replacement |
| --- | --- |
| `subnetCalc_v2.ps1`, `genDynamicNetworkParamFile.ps1` | `cidrSubnet()` on the fixed Simple Mode /20; subnet IDs from the `31-network` outputs |
| `16_Check_Resource_Existence`, `17_Extract_aifactory_salt_random`, `admin-vm-exists.sh` | Greenfield: `*Exists=false`, no identities, empty random salt, no admin VM |
| `11_Generate_Random_Value` | `take(uniqueString(subscription, prefix, scale set, region), 10)`, stable across redeployments |
| Seeding Key Vault reads and SP secrets | No reads: every secret name is empty; the deploying user's identity runs ARM |
| `aif_ensure_team_group` (Entra write) | Existing group object ID entered in the form |
| `63b` `deploy-capacity-resource.py` (SKU and region retries) | Primary attempt only, with the script's own parameter mapping; Search region chosen in the form; no retry |
| `69a` / `69b` Foundry passes | Two linked deployments of `09-ai-foundry-2025-v4` with `dependsOn` |
| `69a-Grant-NetworkContributor-For-Injection`, `69c` Cosmos role | `stages/portal-foundry-injection-rbac.json`, `stages/portal-cosmos-foundry-rbac.json` |
| `aif_ensure_dns_private_resolver` | Resolver and inbound endpoint; the VNet DNS servers are not rewritten, because an ARM PUT of the VNet would replace its subnets |
| VPN Gateway, Application Gateway | Optional, off by default |
| GitHub/ADO repository, OIDC, workflow dispatch | Not part of the button |

