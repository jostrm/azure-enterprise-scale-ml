---
id: deploy-to-azure-portal
status: proposed
sources:
  - portal/generate_portal.py
  - portal/main.bicep
  - portal/README.md
  - bootstrap/lib/aifactory_scaleset_config.py
  - bootstrap/lib/hub_lock_foundation.py
  - bootstrap/lib/factory_enrollment.py
  - bootstrap/lib/registered_creation.py
  - bootstrap/lib/layout_router.sh
  - bootstrap/lib/create-new-aifactory-scaleset.sh
  - bootstrap/templates/azurefactory/register.json
  - environment_setup/azurefactory-cli/src/azurefactory/cli.py
  - environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml
  - environment_setup/aifactory/bicep/scripts/deploy-capacity-resource.py
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_portal_deploy_to_azure.py
  - environment_setup/unit-tests/test-bicep/unit/test_registered_prerequisites.py
  - environment_setup/unit-tests/test-bicep/unit/test_factory_deletion_access_hub.py
graph_symbols:
  - portal/generate_portal.py::function:build_plan
  - portal/generate_portal.py::function:capacity_values
  - bootstrap/lib/aifactory_scaleset_config.py::function:simple_mode_values
reviewed_source: 'release/v1.25 956a8f6e + portal-125 working tree; observed 2026-10-25'
---
# Deploy to Azure portal button (proposal)

Status: **proposed**. The package is tested offline and in CI only. It stays a proposal until a user confirms one successful deployment. Live Azure behaviour has not been observed.

The button deploys the Simple Mode preset (`private-ai-foundation-v2`) as compiled ARM linked templates, opened through the portal's CustomDeploymentBlade with a Form view (uiFormDefinition 2021-09-09). The v1.24 package is on branch `portal-124`; the v1.25 package is on `portal-125`. Both have the same layout: `portal/generate_portal.py`, `portal/main.bicep`, `portal/stages/*.json`, `portal/form.json` and the offline tests in `test_portal_deploy_to_azure.py`.

## How the parameters are derived

The generator replays what the GitHub workflows resolve for the Simple Mode preset: `apply_gha()` with tokenised deployment-time values, the job `env:` expressions, the `variables.json` override, each stage step's `if:` and `--parameters`, and, for v1.25 `63b`, the `PARAMETER_ALIASES` mapping of `deploy-capacity-resource.py` for the primary attempt only. Unknown shell values or parameters fail generation. The linked stages total about 7.4 MB, which is above ARM's 4 MB template limit if inlined; every stage is below 4 MB and 256 parameters.

## Decision: dedicated hub only

v1.25 can coordinate **shared** connectivity hubs across factories through Blob leases (`hub_lock_foundation.py`, container `hub-locks`, used by `registered_prerequisites`). An ARM deployment cannot acquire or hold those leases. The button therefore builds only the Simple Mode **integrated, factory-owned hub** in the factory's own common resource group: VNet `172.16.0.0/20`, private DNS zones and links, DNS Private Resolver, Bastion Developer, IP group, and optional VPN and Application Gateway. It never peers to, links to or writes into another hub. The test `test_hub_is_dedicated_and_never_joins_a_shared_hub` enforces this.

## Decision: portal factories are not registered with the Factory API

A portal-deployed factory **cannot be registered** with the Factory API afterwards. It stays a standalone Dev factory, and `portal/README.md` says so.

Evidence (repository source; the canonical API implementation is external and was not inspected):

- For v1.25 and later, `layout_router.sh` → `registered_creation.py --select-layout` routes creation to the API. The API owns catalog validation, projection, naming and review, and creates the factory itself; only `legacy124` uses the historical bootstrap.
- `azurefactory/register.json` holds explicit factory, scale-set and project projections, and an empty register is not deployed infrastructure ([[Bootstrap-and-Layouts]]). The in-repo SDK and CLI (`azurefactory-cli`) offer no route to adopt or import an existing factory. `enrollment` is add-only and binds lifecycle runners to resource groups of a factory already in the catalog; `factory_enrollment.py` never writes the consumer register.
- The portal uses a deterministic `deploymentRandom` and an empty salt, whereas registered creation resolves names and salts itself. Adopting a portal factory would need an API-reviewed migration, which does not exist.

Revisit this decision if the external API gains a reviewed "adopt existing factory" route.

## Form choices (portal-125 only)

Every optional `SIMPLE_MODE_RESOURCE_CATALOG` project item is a Yes/No choice. Foundry and its capability host require each other, so they form one choice. There are also Dev SKU choices for AI Search (basic, standard or standard2) and Storage (LRS or ZRS). portal-124 keeps the strict v1.24 preset, where only Application Insights is optional.

The generator builds a plan for the default selection, for each choice flipped (respecting catalog requirements), for all-on and all-off, and for each SKU value. Every value that varies must be explained by exactly one choice or its negation, and every stage that comes and goes must likewise depend on exactly one choice. The stages are `03b` (AI Search), `04b` (PostgreSQL), `05b` (Container Apps) and the two Foundry passes with their role modules. Anything else fails generation. `main.bicep` resolves requirement chains (depth at most 2) and passes each value from the choice.

## Replacements (v1.25 differences from portal-124)

- `63b` Search uses `deploy-capacity-resource.py` (Basic primary SKU). The portal replays only attempt 1; the form's Search region sets `aiSearchLocation`. There are no capacity or region retries.
- `admin-vm-exists.sh` and the `67` AML-AKS discovery are greenfield `false`.
- Order: `03-cognitive-services` runs before `03b-ai-search`.
- `CmnAIfactoryNaming.bicep` no longer takes `resolvedManagedIdentityNames`; the portal's Cosmos role module follows stage 09's call.

Other replacements are unchanged from v1.24 (see `portal/README.md`): `cidrSubnet()` instead of `subnetCalc_v2.ps1`, greenfield `*Exists=false`, no seeding-vault reads, an existing Entra group object ID, two Foundry passes, and portal modules for the Foundry Network Contributor and Cosmos data roles.

## Limitations

- `release/v1.25` (`956a8f6e`) and `main` (`d7cc1095`) differed by 57 files on 2026-10-25; the package targets the release branch.
- The registered (API) route builds Simple Mode configuration outside this repository. The portal follows the in-repo preset and workflows, and the two may diverge.
- `documentation/regions/aifactory-v125-region-availability.md` does not exist; regions are the CLI table intersected with Bastion Developer availability.
- First live run (portal-125, northeurope, 2026-10-25) failed in `hub-access`: Bastion Developer was created while the resolver subnet was still being added, and Azure answered that the VNet "was not found ... or is not in a Succeeded state". The hub writes now run one at a time (subnet, resolver, inbound endpoint, Bastion), and the seeding endpoint waits for hub-access, VPN Gateway and Application Gateway network. A rerun has not been observed yet.
- The second live run (same inputs) failed in `12-networkCommon` with `InUseSubnetCannotBeDeleted` on `snet-dns-private-resolver`. The stage PUTs the whole common VNet with only its own four subnets, so a redeploy tries to delete the subnets added later. The CLI has the same exposure unless `RUN_JOB1_NETWORKING=false`. ARM cannot test whether the VNet exists, so the form has a `commonVnetExists` switch (default No) that skips the stage on a redeploy. A successful redeploy has not been observed yet.
- The third live run (redeploy with `commonVnetExists=true`) skipped `12-networkCommon` as intended and failed in `02-core-infrastructure` with `CannotChangeSubnetOnExistingPrivateEndpoint` on the common ACR endpoint. The common job runs without the JSON override and puts that endpoint on `common_subnet_name` (`snet-esml-cmn-001`). The project job applies `variables.json`, whose `subnetCommon` is `snet-dev-esml-cmn-001`, a subnet Simple Mode never creates. Stages 02, 06 and 09 resolve the common subnet from it. Source shows the CLI route passes the same values (`aif_deploy_github` dispatches `infra-common.yml` without `use_json_config_override` and `infra-project.yml` with `config_file`), so the CLI has the same exposure. This has not been observed in a CLI run. The portal now empties `subnetCommon`, `subnetCommonScoring` and `subnetCommonPowerbiGw` for the project stages when `BYO_subnets` is false.
