---
id: deploy-to-azure-portal
status: proposed
sources:
  - portal/generate_portal.py
  - portal/main.bicep
  - portal/README.md
  - bootstrap/lib/aifactory_scaleset_config.py
  - bootstrap/lib/aifactory_private_dns.py
  - bootstrap/lib/create-new-aifactory-scaleset.sh
  - environment_setup/aifactory/variables.json
  - environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-common.yml
  - environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml
  - environment_setup/aifactory/bicep/scripts/apply-json-config-overrides.py
  - environment_setup/aifactory/bicep/scripts/search-region-fallback.py
  - environment_setup/aifactory/bicep/scripts/resolve_managed_identities.py
  - environment_setup/aifactory/bicep/scripts/subnetCalc_v2.ps1
  - environment_setup/aifactory/bicep/scripts/genDynamicNetworkParamFile.ps1
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_portal_deploy_to_azure.py
  - environment_setup/unit-tests/test-bicep/unit/test_simple_bootstrap.py
graph_symbols:
  - portal/generate_portal.py::function:build_plan
  - portal/generate_portal.py::function:replay_bootstrap
  - bootstrap/lib/aifactory_scaleset_config.py::function:simple_mode_values
  - bootstrap/lib/aifactory_scaleset_config.py::function:apply_gha
reviewed_source: 'release/v1.24 dfad2e45 + portal-124 working tree; observed 2026-10-25'
---
# Deploy to Azure portal button (proposal)

Status: **proposed**. The package is tested offline and in CI. It stays a proposal until a user confirms one successful deployment in a supported region. Live Azure behaviour has not been observed.

## Mechanism

The mechanism is the same as Azure/AI-Landing-Zones' `portal` branch: a compiled ARM `azuredeploy.json` plus a Form view (uiFormDefinition 2021-09-09) `form.json`, opened through `portal.azure.com/#blade/Microsoft_Azure_CreateUIDef/CustomDeploymentBlade/uri/<template>/uiFormDefinitionUri/<form>`. The button serves raw files from the `portal-124` branch.

Every v1.24 stage entry point the Simple Mode chain deploys is subscription scope, except `31-network` and `createPrivateDnsZones`, which are resource-group scope. Compiled with Bicep 0.37.4, the linked stages total about 7.4 MB; `09-ai-foundry-2025-v4` alone is 2.54 MB and is deployed twice. ARM's template limit is 4 MB, so `portal/main.bicep` is a thin subscription-scope template (0.27 MB, 18 parameters). It creates the bootstrap resource group and calls each stage as `Microsoft.Resources/deployments` with `templateLink.relativePath`. Each stage is below 4 MB and 256 parameters; the largest parameter count is `01-foundation` with 127. Because `relativePath` resolves only against a template URI, CLI use needs `--template-uri`.

## No hand-copied values

`portal/generate_portal.py` replays the GitHub route of the v1.24 Simple Mode CLI offline:

1. `apply_gha()` runs on a scratch copy of `.env.template` and `variables.json`, with a CLI-shaped state whose deployment-time values are `__P_<name>__` tokens. This produces the `.env` (GitHub variables) and the consumer `variables.json`.
2. The workflow job `env:` blocks of `infra-common.yml` (`common-dev`) and `infra-project-phase.yml` (`deploy-project`) are evaluated with a GitHub Actions expression subset.
3. The project job applies the `00_Apply_JSON_Config_Override` overlay, then the greenfield values written by its own steps (`00_Resolve_Network_Env_Placeholders`, `17_Extract_aifactory_salt_random`, the 63a Search handoff and others).
4. Each stage step's `if:` is evaluated per phase (`infra`, `foundry`), and its `--parameters` are typed against the compiled template.

`main.bicep` fills the tokens with a single `fill()` function and wires only the network outputs, IDs and form choices. Tests fail on any drift from the preset, a disabled flag being enabled, a required parameter going unsupplied, or an unmapped shell value.

## Replacement table

| CLI or pipeline | Portal |
| --- | --- |
| `subnetCalc_v2.ps1` (projectType `all`), `simple_mode_hub_subnets` | `cidrSubnet()` on the fixed Simple Mode `172.16.0.0/20`; the plan matches the reserved hub subnets |
| `genDynamicNetworkParamFile.ps1` | `31-network` deployment outputs |
| Existence checks, salt recovery | Greenfield: `*Exists=false`, `resolvedManagedIdentityNames={}`, empty random salt |
| `deployment_random_value` | `take(uniqueString(subscription, prefix, scale set, region), 10)`. Resource names derive from it when the salt is empty, so it must stay stable across redeployments |
| SP secrets and seeding-vault reads | All secret names are empty; the seeding Key Vault exists as a private shell only |
| `aif_ensure_team_group` | Existing group object ID as input; no Entra writes |
| `63a` Search fallback | Search region chosen in the form; no retry |
| `69a`/`69b` | Two linked deployments of `09-ai-foundry-2025-v4` with `dependsOn` |
| `69a` Network Contributor, `69c` Cosmos data role | Portal modules. Cosmos and project names come from `CmnAIfactoryNaming.bicep` with the same inputs as stage 09 |
| App Gateway certificate vault role | Portal module scoped to the certificate vault |
| `aif_ensure_dns_private_resolver` | Resolver and inbound endpoint without rewriting the VNet DNS servers (an ARM VNet PUT would replace its subnets) |
| `100a` shared private link approval | Manual post-deployment step (ARM cannot discover pending connection names) |
| VPN Gateway, Application Gateway WAF_v2 | Optional, off by default |
| Repository, OIDC, workflow dispatch | Not in the button |

The region list is the v1.24 CLI region table intersected with Bastion Developer availability (`portal/data/bastion-developer-regions.json`, from Microsoft Learn). When `documentation/regions/aifactory-v124-region-availability.md` exists, its section 1 is intersected as well.

## Disagreements and limitations

- v1.24 Simple Mode has no separate connectivity resource group. The integrated hub lives in the common resource group (`aif_collect_answers`), and the third group is the bootstrap/seeding group.
- The branch `claude/busy-hopper-j9jfhu` and the v1.24 region page referenced by the task were not on the remote on 2026-10-25. The graph tooling was copied from `main`, and the region list falls back to the CLI ∩ Bastion Developer intersection.
- `SIMPLE_MODE_RESOURCE_CATALOG` marks VPN Gateway and Application Gateway as required. The button makes both optional and off by default, following the portal design (cost, 30-45 minutes, App Gateway inputs).
- No models are deployed, which matches the preset, so model SKU selection does not apply.
- First live run (portal-125, northeurope, 2026-10-25) failed in `hub-access`: Bastion Developer was created while the resolver subnet was still being added, and Azure answered that the VNet "was not found ... or is not in a Succeeded state". The hub writes now run one at a time (subnet, resolver, inbound endpoint, Bastion), and the seeding endpoint waits for hub-access, VPN Gateway and Application Gateway network. A rerun has not been observed yet.
- The second live run (same inputs) failed in `12-networkCommon` with `InUseSubnetCannotBeDeleted` on `snet-dns-private-resolver`. The stage PUTs the whole common VNet with only its own four subnets, so a redeploy tries to delete the subnets added later. The CLI has the same exposure unless `RUN_JOB1_NETWORKING=false`. ARM cannot test whether the VNet exists, so the form has a `commonVnetExists` switch (default No) that skips the stage on a redeploy. A successful redeploy has not been observed yet.
- The third live run (redeploy with `commonVnetExists=true`) skipped `12-networkCommon` as intended and failed in `02-core-infrastructure` with `CannotChangeSubnetOnExistingPrivateEndpoint` on the common ACR endpoint. The common job runs without the JSON override and puts that endpoint on `common_subnet_name` (`snet-esml-cmn-001`). The project job applies `variables.json`, whose `subnetCommon` is `snet-dev-esml-cmn-001`, a subnet Simple Mode never creates. Stages 02, 06 and 09 resolve the common subnet from it. Source shows the CLI route passes the same values (`aif_deploy_github` dispatches `infra-common.yml` without `use_json_config_override` and `infra-project.yml` with `config_file`), so the CLI has the same exposure. This has not been observed in a CLI run. The portal first emptied `subnetCommon`, `subnetCommonScoring` and `subnetCommonPowerbiGw` for the project stages when `BYO_subnets` is false. Since 2026-10-27 the source does it: `00_Resolve_Network_Env_Placeholders` in `infra-project-phase.yml` clears them after the JSON override, as ADO's `job-2-genai-services` does (main, release/v1.25, release/v1.24). The generator now replays that guard from the workflow (`byo_subnet_clears`) instead of correcting it, and `check_common_subnet` stops generation when project and common stages would resolve different common subnets.
