# Parameters — Advanced reference

Use [Standard parameters](standard.md) for the initial checklist. This reference
covers the **public configuration surface**, not every Bash local or internal
Bicep/ARM module parameter.

## Scope and authoritative sources

The generated tables include every unique key in these **shared templates**:

- `environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/.env.template`
- `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml`
- `environment_setup/aifactory/variables.json` — every section and key, including
  all Dev and Stage/Prod SKU fields.

They also cover external create-bootstrap environment inputs and the configuration
helper's CLI options, from `bootstrap/lib/create-new-aifactory-scaleset.sh`,
`bootstrap/lib/release_version.sh`, the GH/ADO update launchers, and
`bootstrap/lib/aifactory_scaleset_config.py`. Public Bash command switches are
documented below. Internal resume flags, generated state, shell implementation
locals, external service API schemas, and module-internal ARM inputs are excluded.
There is no separate checked-in bootstrap `.env` template in these sources:
bootstrap reads process environment inputs, then writes the selected route's files.
Do not confuse that input environment with the generated GitHub `.env`.

!!! note "Two distinct JSON contracts"
    The raw checked-in consumer template `environment_setup/aifactory/variables.json`
    currently has a **`dev` section only**.
    Stage/Prod SKU pairs such as `dev.skuAISearchStageProd` are present inside it;
    there is no checked-in top-level `stage_prod` section. The legacy bootstrap
    helper's `update_json()` updates `dev`. The generated inventory below reports
    that shared template exactly; it is **not the Azure Factory v2 output schema**.

    Each backend-generated **Azure Factory v2 project** has one `variables.json`
    with **direct top-level `dev` and `stage_prod` sections**, stored at
    `factories/<key>/scalesets/<immutable storage_suffix>/projects/projectNNN/variables.json`.
    Both sections retain the full configuration, with separate subscription and
    SKU values. They are not nested inside a wrapper or split across per-environment
    files. Review the selected project's two sections before CLI/API dispatch.

### Reading defaults and requirements

- **M — mandatory in the source template's deployment context.** A supplied
  default can satisfy the input; it does not mean you must edit every M row.
- **C — conditionally required.** Applies only to the selected environment,
  identity route, service or networking mode. For example, Stage service
  connections are not prerequisites for a Dev-only run.
- **O — optional override or feature switch.** O does not mean safe to enable
  without its dependencies. Optional switches remain O even if a preset fixes
  them on; the required private-agent service bundle is C for that architecture.
- Values are **actual assignments**, not the sometimes stale `<default>` text
  in comments. Empty strings and `<todo>` / `<optional>` placeholders are shown
  literally and are not usable credentials or resource IDs.
- YAML and GHA marker annotations occasionally differ. Each GHA row retains
  its own annotation; a JSON key inherits the YAML annotation where available.
  Untagged settings default to O, with route/service conditions described in text.
- Binding names come from shared workflow expressions, preflight `getval`
  mappings, bootstrap writers and explicitly reviewed template correspondences.
  **No automatic case conversion** is used.
  A binding may be a workflow fallback rather than an equivalent standalone input.

## Important cross-format semantics

### Networking and DNS

The shared template default is `shared-subscriptions` with
`common_vnet_cidr=172.16.XX.0/18` and network-aligned Dev/Stage/Prod selectors
**`0` / `64` / `128`**. Own-subscription `/20` planning uses **`0` / `16` / `32`**.
`XX` replaces the third octet in the VNet and subnet templates. Environments,
VPN client pools and existing networks must not overlap. Address intent does
not create peering or resize existing networks.

| `centralDnsZoneByPolicyInHub` | `enableAIFactoryHub` | Meaning |
|---|---|---|
| `false` | `false` | Standalone DNS/network intent |
| `false` | `true` | Own AI Factory hub intent |
| `true` | Either | External central-DNS hub takes precedence; supply its subscription/resource group |

The hub flag alone is configuration intent, not a deployment operation. JSON
stores these flags as booleans while YAML/GHA templates use string values.
The three public-access flags govern service access, not repository visibility
and not every telemetry endpoint. `enableAMPLS=false` does not provide
private-only Application Insights/Log Analytics ingestion.

### Models, SKUs and aliases

`modelGPTXSku` / `MODEL_GPTX_SKU` and
`default_model_sku` / `DEFAULT_MODEL_SKU` default to **`DataZoneStandard`**.
Model availability, version support, capacity and quota must be checked for
the selected region/subscription; a template value is not a capacity reservation.
Dev and Stage/Prod service SKUs remain separate fields.

AI Search has a particularly important fallback:
`skuAISearchDev` reads `SKU_AISEARCH_DEV`, then `ADMIN_AISEARCH_TIER`;
`skuAISearchStageProd` reads `SKU_AISEARCH_STAGEPROD`, then
`ADMIN_AISEARCH_TIER`. The shared `ADMIN_AISEARCH_TIER=basic` can therefore
override the workflow's final Stage/Prod `standard` fallback.
`ADMIN_AI_SEARCH_TIER` is another spelling consumed by preflight, not a
safe rename of every workflow input. Likewise, semantic tier and Azure ML
principal-ID compatibility spellings coexist in the template.

ADO has separate Dev/Stage/Prod seeding-vault coordinates and service connections.
GHA commonly uses one seeding-vault variable name with environment-specific
overrides. Review the collision table rather than copying one value into all
environments. Some source defaults genuinely differ, including resource naming,
Hybrid Benefit, user RBAC restrictions, placeholders and tag macros.

### Identity, secrets and lifecycle

Secret-name inputs identify entries in the seeding Key Vault; they are **not**
secret values. Federated managed-identity/OIDC bootstrap can leave legacy
service-principal secret-name fields empty. A seeding-vault shell may still be
required. Existing-SP and PAT routes require secrets only when selected; keep
them out of committed files, logs and command history.

Deletion and debug switches are public template inputs and therefore included.
Their presence is not a recommendation to enable them. Review the exact target,
backups, policy/RBAC permissions, network reachability and the deployment plan.
A complete configuration reference is not a guarantee of deployment success.

## Bash create and update contract

Run these entrypoints from the generated consumer checkout, using Bash/Git Bash.
They use the existing deployment engine and route configuration.

| Entrypoint | Public switch | Meaning |
|---|---|---|
| `GHA-create-new-aifactory-scaleset.sh`, `ADO-create-new-aifactory-scaleset.sh` | `--repo-root PATH` | Explicit legacy consumer root |
| Create | `--aifactory-version VERSION` | Explicit source version, e.g. `main`, `124`, `125`, `1.100`, `10.2` |
| Create | `--dry-run` | Collect/validate without mutation; not an offline preview or supported simple-mode launch |
| Create | `--prepare-only` | Prepare Azure, identity, configuration and automation without completing deployment |
| Create | `--no-wait` | Dispatch without waiting; incompatible with the simple-mode dependent chain |
| Create | `--non-interactive` | Read answers from process environment |
| Create | `--yes` | Accept the execution summary |
| Create/update | `--help`, `-h` | Show entrypoint help |
| `ALL-create-new-aifactory-scaleset.sh` | `--orchestrator ado\|gha` | Select one route, then forward create options |
| `GH-update-aifactory-and-run-project.sh`, `GHA-update-aifactory-and-run-project.sh`, `ADO-update-aifactory-and-run-project.sh` | `--project-only` | Dispatch project only; skip factory/template updates |
| Update | `--aifactory-version VERSION` | Choose update source version explicitly |

Create and update default to `main` unless an explicit version selector is
provided; project-only is not an upgrade operation. Current create validation
accepts **`AIF_NETWORK_MODE=priv` only**, despite legacy help also mentioning
`h`/`pub`. Its general region prompt defaults to **`swedencentral`**, whereas
the shared configuration templates default to **`eastus2`**.
Initial legacy bootstrap deploys Dev only and seeds Stage/Prod subscription
values from Dev; that is not a reviewed multi-environment network plan.

Register-managed targets are a distinct contract: these legacy launchers do
not initialize or modify `azurefactory/register.json`. Use the corresponding
lifecycle CLI/API with an explicit, reviewed target manifest instead.
Legacy create explicitly rejects `AIF_CREATE_PROJECTS` and `AIF_PROJECT_MODE`;
they are not supported substitutes for a scoped lifecycle manifest.

## Simple-mode technical contract

`AIF_SIMPLE_MODE=true` opts the GHA create entrypoint into contract v2,
`private-ai-foundation-v2`. Use `--non-interactive --yes --repo-root PATH` and
wait for the full common → access hub → project → private HTTPS gateway chain.
Use the following **offline, read-only** preview instead of a deployment dry run:

```bash
python bootstrap/lib/aifactory_scaleset_config.py --simple-mode-manifest
```

Provide tenant/subscription, region, prefix, repository and initial team identity
inputs, plus a published `AIF_SUBMODULE_REF`. Existing Azure/GitHub authentication
is required. Prefix validation accepts 2–16 lowercase letters, digits or hyphens.
The default suffix is `001`; the cost-center default is `123456`.

Fixed settings are `AIF_TOPOLOGY=s`, `AIF_NETWORK_MODE=priv`,
`AIF_ACCESS_HUB_MODE=i`, `AIF_IDENTITY_MODE=c`, `AIF_SEEDING_MODE=c`,
`AIF_SEED_PROJECT_SP=false`, `AIF_SETUP_HUB_ACCESS=true`,
`AIF_CONFIGURE_VPN_CLIENT=false`, `AIF_DEV_VNET_CIDR=172.16.0.0/20`,
and `AIF_PROJECT_NUMBER=001`.

The current schema keeps project Storage, Key Vault, managed identities,
Foundry, its capability host, **Basic AI Search** and Cosmos DB required.
`AIF_SIMPLE_PROJECT_RESOURCES_JSON=[]` removes optional Application Insights,
**not** those required dependencies. Model deployment toggles remain off.
This is not a preloaded-model or runnable-agent guarantee.

Gateway inputs are all required for this contract:

| Environment input | Helper/API input | Constraint |
|---|---|---|
| `AIF_APP_GATEWAY_HOSTNAME` | `--app-gateway-hostname` / `app_gateway_hostname` | Custom frontend FQDN covered by certificate DNS SAN |
| `AIF_APP_GATEWAY_BACKEND_FQDN` | `--app-gateway-backend-fqdn` / `app_gateway_backend_fqdn` | Distinct private RFC1918 HTTPS backend, reachable from the new VNet, trusted TLS, unauthenticated `GET /` returns 200–399 |
| `AIF_APP_GATEWAY_CERT_SECRET_ID` | `--app-gateway-certificate-secret-id` / `app_gateway_certificate_secret_id` | Versionless `https://<vault>.vault.azure.net/secrets/<name>` URI of an enabled, valid, exportable PFX certificate in an RBAC-enabled Dev-subscription vault |

No certificate secret value is embedded in these inputs. The private-network
Application Gateway subscription feature must already be registered.
Gateway/resolver/application subnets are reserved before project allocation:
`172.16.1.0/27`, `172.16.1.32/28`, `172.16.2.0/24`. Conflicting existing
allocations are rejected, not moved or deleted.

The access hub includes billable VPN Gateway and DNS Private Resolver resources.
VPN transport uses a public IP; Azure service access remains independently
controlled. The exported VPN profile is a sensitive connection artifact; connect
the client manually. Bastion Developer requires regional support, has no
automatic paid-SKU fallback, and does not create an admin VM.

`GITHUB_REPOSITORY_VISIBILITY=private|public` defaults to **private** for this
contract, unlike the generic `.env.template` repository default. An existing
repository must be empty and match the requested visibility. Review generated
code and non-secret metadata before publication. Ignore rules for `.env`,
populated configuration, certificates and VPN files are not a general-purpose
secret sanitizer.

## Maintaining the reference

The generator reads only the named shared sources. It has no dependency on a
separate configuration application or consumer workspace. From repository root:

```bash
python documentation/gh-io/tools/generate_parameters.py
python documentation/gh-io/tools/generate_parameters.py --check
```

The check compares the exact source-qualified union with generated row markers,
rejects duplicate JSON keys/reference rows and detects stale defaults,
descriptions, aliases and inventory counts. Repeated source assignments are
reported, not silently represented as multiple settings.

Targeted regression tests:

```bash
python -m unittest discover -s environment_setup/unit-tests/test-bicep/unit -p test_parameter_documentation.py -v
```

<!-- BEGIN GENERATED PARAMETERS -->

## Source coverage

| Source | Unique public keys |
|---|---:|
| `yaml` | 342 |
| `env` | 341 |
| `bootstrap` | 78 |
| `helper` | 14 |
| `state` | 42 |
| `json.dev` | 347 |

Counts are source-qualified: a spelling present in YAML and JSON is covered in each source, not counted as two settings. Repeated template assignments are consolidated below (last assignment wins).

- Source duplicate: `env:ADMIN_COMMON_RESOURCE_SUFFIX`, lines 130, 363; one reference row.
- Source duplicate: `env:ADMIN_PRJ_RESOURCE_SUFFIX`, lines 131, 364; one reference row.
- Source duplicate: `env:USE_COMMON_ACR_OVERRIDE`, lines 365, 389; one reference row.

## YAML and variables.json reference

Exact YAML keys are under `variables:`; JSON paths are `<section>.<key>`. **Y** = YAML assignment; **J.section** = JSON value. JSON quoting and scalar types are preserved. A missing source is explicitly marked. GHA names include workflow bindings/fallbacks and explicitly reviewed template counterparts; they are not automatically interchangeable and inclusion does not guarantee every workflow consumes them.

### Services and feature switches

| YAML / JSON key | GHA binding(s) | M/C/O | Source defaults | Description / conditions |
|---|---|---|---|---|
| <!-- parameter yaml:AMLStudioUIPrivate --><!-- parameter json.dev:AMLStudioUIPrivate -->`AMLStudioUIPrivate` | `AML_STUDIO_UI_PRIVATE` | O | Y: `"true"`<br>J.dev: `"true"` | AML Studio UI private access otherwise: false, only data plane is private; control plane is public. |
| <!-- parameter yaml:ENABLE_APIM --><!-- parameter json.dev:ENABLE_APIM -->`ENABLE_APIM` | `ENABLE_APIM` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy APIM Azure OpenAI pool, token guard, 429-aware backend circuit breakers, and API policy. |
| <!-- parameter yaml:ENABLE_KONG --><!-- parameter json.dev:ENABLE_KONG -->`ENABLE_KONG` | `ENABLE_KONG` | O | Y: `"false"`<br>J.dev: `"false"` | Deploys Kong as an optional private edge proxy to APIM. |
| <!-- parameter yaml:acr_SKU --><!-- parameter json.dev:acr_SKU -->`acr_SKU` | `ACR_SKU` | M | Y: `"Premium"`<br>J.dev: `"Premium"` | ACR SKU mandatory: ACR SKU ensure: Premium required for private endpoints and CMK support. |
| <!-- parameter yaml:acr_adminUserEnabled --><!-- parameter json.dev:acr_adminUserEnabled -->`acr_adminUserEnabled` | `ACR_ADMIN_USER_ENABLED` | O | Y: `"false"`<br>J.dev: `"false"` | ACR admin user enabled recommended: false, disable admin user for security. otherwise: true, enable for simpler dev access. |
| <!-- parameter yaml:acr_dedicated --><!-- parameter json.dev:acr_dedicated -->`acr_dedicated` | `ACR_DEDICATED` | M | Y: `"true"`<br>J.dev: `"true"` | ACR dedicated (Premium tier) mandatory: ACR dedicated (Premium tier) ensure: must be true when using private endpoints or CMK. |
| <!-- parameter yaml:addAIFoundry --><!-- parameter json.dev:addAIFoundry -->`addAIFoundry` | `ADD_AI_FOUNDRY` | O | Y: `"false"`<br>J.dev: `"false"` | Add new AI Foundry instance with new name otherwise: true, provisions a new AI Foundry with a new random name (for debugging or re-run) to get a fresh start. Still you should delete the old instance. |
| <!-- parameter yaml:addAIFoundryHub --><!-- parameter json.dev:addAIFoundryHub -->`addAIFoundryHub` | `ADD_AI_FOUNDRY_HUB` | O | Y: `"false"`<br>J.dev: `"false"` | DEPRECATED. Do not enable. keep-as-is: DEPRECATED. Do not enable. |
| <!-- parameter yaml:addAISearch --><!-- parameter json.dev:addAISearch -->`addAISearch` | `ADD_AI_SEARCH` | O | Y: `"false"`<br>J.dev: `"false"` | Add new AI Search instance otherwise: false, CreateIfNotExists logic. |
| <!-- parameter yaml:addAzureMachineLearning --><!-- parameter json.dev:addAzureMachineLearning -->`addAzureMachineLearning` | `ADD_AZURE_MACHINE_LEARNING` | O | Y: `"false"`<br>J.dev: `"false"` | Add new Azure ML workspace |
| <!-- parameter yaml:addBastionHost --><!-- parameter json.dev:addBastionHost -->`addBastionHost` | `ADD_BASTION_HOST` | O | Y: `"false"`<br>J.dev: `"false"` | Add Bastion Host in common RG |
| <!-- parameter yaml:apimGatewayAggregateTpm --><!-- parameter json.dev:apimGatewayAggregateTpm -->`apimGatewayAggregateTpm` | `APIM_GATEWAY_AGGREGATE_TPM` | C | Y: `""`<br>J.dev: `""` | 80-90% of the summed TPM across all GPT-5.5 backends. Required by the separate AI gateway workflow when APIM is enabled. |
| <!-- parameter yaml:apimGatewayApiId --><!-- parameter json.dev:apimGatewayApiId -->`apimGatewayApiId` | `APIM_GATEWAY_API_ID` | O | Y: `"azure-openai-gpt55"`<br>J.dev: `"azure-openai-gpt55"` | Apim gateway api id. |
| <!-- parameter yaml:apimGatewayApiPath --><!-- parameter json.dev:apimGatewayApiPath -->`apimGatewayApiPath` | `APIM_GATEWAY_API_PATH` | O | Y: `"openai"`<br>J.dev: `"openai"` | Apim gateway api path. |
| <!-- parameter yaml:apimGatewayAssignOpenAIUserRole --><!-- parameter json.dev:apimGatewayAssignOpenAIUserRole -->`apimGatewayAssignOpenAIUserRole` | `APIM_GATEWAY_ASSIGN_OPENAI_USER_ROLE` | O | Y: `"false"`<br>J.dev: `"false"` | Requires roleAssignments/write in every backend subscription. |
| <!-- parameter yaml:apimGatewayBackendPoolName --><!-- parameter json.dev:apimGatewayBackendPoolName -->`apimGatewayBackendPoolName` | `APIM_GATEWAY_BACKEND_POOL_NAME` | O | Y: `"aoai-gpt55-pool"`<br>J.dev: `"aoai-gpt55-pool"` | Apim gateway backend pool name. |
| <!-- parameter yaml:apimGatewayBackendsJson --><!-- parameter json.dev:apimGatewayBackendsJson -->`apimGatewayBackendsJson` | `APIM_GATEWAY_BACKENDS_JSON` | C | Y: `"[]"`<br>J.dev: `"[]"` | JSON array; see esml-common/ai-gateway/apim/README.md. Required by the separate AI gateway workflow when APIM is enabled. |
| <!-- parameter yaml:apimGatewayCallerTpm --><!-- parameter json.dev:apimGatewayCallerTpm -->`apimGatewayCallerTpm` | `APIM_GATEWAY_CALLER_TPM` | O | Y: `"10000"`<br>J.dev: `"10000"` | Fair-use TPM allocation per APIM subscription. |
| <!-- parameter yaml:apimGatewayResourceGroup --><!-- parameter json.dev:apimGatewayResourceGroup -->`apimGatewayResourceGroup` | `APIM_GATEWAY_RESOURCE_GROUP` | C | Y: `""`<br>J.dev: `""` | Resource group containing the existing APIM service. Required by the separate AI gateway workflow when APIM is enabled. |
| <!-- parameter yaml:apimGatewayRetryCount --><!-- parameter json.dev:apimGatewayRetryCount -->`apimGatewayRetryCount` | `APIM_GATEWAY_RETRY_COUNT` | O | Y: `"2"`<br>J.dev: `"2"` | Apim gateway retry count. |
| <!-- parameter yaml:apimGatewayServiceName --><!-- parameter json.dev:apimGatewayServiceName -->`apimGatewayServiceName` | `APIM_GATEWAY_SERVICE_NAME` | C | Y: `""`<br>J.dev: `""` | Existing APIM service with system-assigned managed identity enabled. Required by the separate AI gateway workflow when APIM is enabled. |
| <!-- parameter yaml:apimGatewaySku --><!-- parameter json.dev:apimGatewaySku -->`apimGatewaySku` | `APIM_GATEWAY_SKU` | O | Y: `"StandardV2"`<br>J.dev: `"StandardV2"` | AI gateway SKU: BasicV2=dev/test; StandardV2=production default with VNet integration; PremiumV2=private inbound/outbound, zones, and high scale. Classic Developer/Basic/Standard/Premium are supported but cannot be migrated to v2 in place. Consumption is unsupported because APIM backend circuit breakers are unavailable. |
| <!-- parameter yaml:apimGatewaySkuCapacity --><!-- parameter json.dev:apimGatewaySkuCapacity -->`apimGatewaySkuCapacity` | `APIM_GATEWAY_SKU_CAPACITY` | O | Y: `1`<br>J.dev: `1` | BasicV2/StandardV2 scale to 10 units; PremiumV2 scales to 30 units. Set capacity based on APIM gateway CPU/memory metrics. |
| <!-- parameter yaml:apimGatewaySubscriptionId --><!-- parameter json.dev:apimGatewaySubscriptionId -->`apimGatewaySubscriptionId` | `APIM_GATEWAY_SUBSCRIPTION_ID` | O | Y: `""`<br>J.dev: `""` | Subscription containing APIM. Empty uses the environment subscription. |
| <!-- parameter yaml:cleanFoundryCaphost --><!-- parameter json.dev:cleanFoundryCaphost -->`cleanFoundryCaphost` | `CLEAN_FOUNDRY_CAPHOST` | O | Y: `"false"`<br>J.dev: `"false"` | Clean up capability host on deletion otherwise: false, leaves capability host and its resources (such as VMs) in place when deleting the Foundry project. |
| <!-- parameter yaml:databricksOID --><!-- parameter json.dev:databricksOID -->`databricksOID` | `DATABRICKS_OID` | C | Y: `"<optional>_ObjectID"`<br>J.dev: `"<optional>_ObjectID"` | Databricks object ID mandatory: if enableDatabricks:'true' ensure: find Databricks object ID in Entra ID. |
| <!-- parameter yaml:databricksPrivate --><!-- parameter json.dev:databricksPrivate -->`databricksPrivate` | `DATABRICKS_PRIVATE` | O | Y: `"true"`<br>J.dev: `"true"` | Databricks private control plane otherwise: false, only data plane is private; control plane is public. |
| <!-- parameter yaml:disable_whitelisting_for_build_agents --><!-- parameter json.dev:disable_whitelisting_for_build_agents -->`disable_whitelisting_for_build_agents` | `DISABLE_WHITELISTING_FOR_BUILD_AGENTS` | O | Y: `"false"`<br>J.dev: `"false"` | Disable runner IP whitelisting otherwise: true, skip whitelisting (use only if runner already has network access). |
| <!-- parameter yaml:elasticCompanyName --><!-- parameter json.dev:elasticCompanyName -->`elasticCompanyName` | `ELASTIC_COMPANY_NAME` | C | Y: `"Organization"`<br>J.dev: `"Organization"` | Elastic Cloud company name mandatory: if enableElasticsearch:'true' |
| <!-- parameter yaml:elasticDeploymentSize --><!-- parameter json.dev:elasticDeploymentSize -->`elasticDeploymentSize` | `ELASTIC_DEPLOYMENT_SIZE` | O | Y: `"small"`<br>J.dev: `"small"` | Elasticsearch deployment size otherwise: "medium" or "large". |
| <!-- parameter yaml:elasticEmail --><!-- parameter json.dev:elasticEmail -->`elasticEmail` | `ELASTIC_EMAIL` | C | Y: `"admin@example.com"`<br>J.dev: `"admin@example.com"` | Elastic Cloud account email mandatory: if enableElasticsearch:'true' ensure: valid email address. |
| <!-- parameter yaml:elasticFirstName --><!-- parameter json.dev:elasticFirstName -->`elasticFirstName` | `ELASTIC_FIRST_NAME` | C | Y: `"AI"`<br>J.dev: `"AI"` | Elastic Cloud contact first name mandatory: if enableElasticsearch:'true' |
| <!-- parameter yaml:elasticLastName --><!-- parameter json.dev:elasticLastName -->`elasticLastName` | `ELASTIC_LAST_NAME` | C | Y: `"Factory"`<br>J.dev: `"Factory"` | Elastic Cloud contact last name mandatory: if enableElasticsearch:'true' |
| <!-- parameter yaml:elasticSku --><!-- parameter json.dev:elasticSku -->`elasticSku` | `ELASTIC_SKU` | O | Y: `"ess-consumption-2024_Monthly"`<br>J.dev: `"ess-consumption-2024_Monthly"` | Elastic Cloud SKU |
| <!-- parameter yaml:elasticType --><!-- parameter json.dev:elasticType -->`elasticType` | `ELASTIC_TYPE` | O | Y: `"ElasticCloud"`<br>J.dev: `"ElasticCloud"` | Elasticsearch deployment type otherwise: "SelfManagedOnAKS" (future support). |
| <!-- parameter yaml:enableAFoundryCaphost --><!-- parameter json.dev:enableAFoundryCaphost -->`enableAFoundryCaphost` | `ENABLE_FOUNDRY_CAPHOST` | C | Y: `"true"`<br>J.dev: `"true"` | Required for this private Foundry standard-agent architecture. Cannot be disabled; binds Cosmos DB thread storage, AI Search vector storage, and project Storage. mandatory: Required for this private Foundry standard-agent architecture. Cannot be disabled; binds Cosmos DB thread storage, AI Search vector storage, and project Storage. Required together for the standard private-agent capability-host architecture; not universal across all deployment paths. |
| <!-- parameter yaml:enableAIDocIntelligence --><!-- parameter json.dev:enableAIDocIntelligence -->`enableAIDocIntelligence` | `ENABLE_AI_DOC_INTELLIGENCE` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure AI Document Intelligence |
| <!-- parameter yaml:enableAIFactoryCreatedDefaultProjectForAIFv2 --><!-- parameter json.dev:enableAIFactoryCreatedDefaultProjectForAIFv2 -->`enableAIFactoryCreatedDefaultProjectForAIFv2` | `ENABLE_AIFACTORY_CREATED_DEFAULT_PROJECT_FOR_AIFV2` | O | Y: `"true"`<br>J.dev: `"true"` | AI Factory default project for AIFv2 otherwise: false, Azure creates a default project with additional CosmosDB, Storage, AI Search, and connections. |
| <!-- parameter yaml:enableAIFactoryHub --><!-- parameter json.dev:enableAIFactoryHub -->`enableAIFactoryHub` | `ENABLE_AI_FACTORY_HUB` | O | Y: `"false"`<br>J.dev: `false` | Own AI Factory Hub intent |
| <!-- parameter yaml:enableAIFoundry --><!-- parameter json.dev:enableAIFoundry -->`enableAIFoundry` | `ENABLE_AI_FOUNDRY` | C | Y: `"true"`<br>J.dev: `"true"` | Enable AI Foundry mandatory: Enable AI Foundry recommended: AI Foundry with default project; enterprise-grade private networking, BYOvNet, existing infra. GA. Required together for the standard private-agent capability-host architecture; not universal across all deployment paths. |
| <!-- parameter yaml:enableAIFoundryHub --><!-- parameter json.dev:enableAIFoundryHub -->`enableAIFoundryHub` | `ENABLE_AI_FOUNDRY_HUB` | O | Y: `"false"`<br>J.dev: `"false"` | DEPRECATED. AI Foundry Hub (V1) service. Do not enable. Use enableAIFoundry instead. keep-as-is: DEPRECATED. AI Foundry Hub (V1) service. Do not enable. Use enableAIFoundry instead. |
| <!-- parameter yaml:enableAISearch --><!-- parameter json.dev:enableAISearch -->`enableAISearch` | `ENABLE_AI_SEARCH` | C | Y: `"true"`<br>J.dev: `"true"` | Required capability-host vector store for private Foundry standard agents. mandatory: Required capability-host vector store for private Foundry standard agents. Required together for the standard private-agent capability-host architecture; not universal across all deployment paths. |
| <!-- parameter yaml:enableAISearchSharedPrivateLink --><!-- parameter json.dev:enableAISearchSharedPrivateLink -->`enableAISearchSharedPrivateLink` | `ENABLE_AI_SEARCH_SHARED_PRIVATE_LINK` | O | Y: `"true"`<br>J.dev: `"true"` | AI Search shared private link otherwise: false, creates a private endpoint in the project vNet. |
| <!-- parameter yaml:enableAIServices --><!-- parameter json.dev:enableAIServices -->`enableAIServices` | `ENABLE_AI_SERVICES` | O | Y: `"false"`<br>J.dev: `"false"` | DEPRECATED. Standalone AI Services account with Azure OpenAI endpoint. Do not enable. Use enableAIFoundry instead. keep-as-is: DEPRECATED. Standalone AI Services account with Azure OpenAI endpoint. Do not enable. Use enableAIFoundry instead. |
| <!-- parameter yaml:enableAKS --><!-- parameter json.dev:enableAKS -->`enableAKS` | `ENABLE_AKS` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy standalone AKS cluster in project RG |
| <!-- parameter yaml:enableAMPLS --><!-- parameter json.dev:enableAMPLS -->`enableAMPLS` | `ENABLE_AMPLS` | O | Y: `"false"`<br>J.dev: `"false"` | Enable AMPLS in Hub otherwise: true, AMPLS created in Hub subscription; AppInsights in private/private mode. |
| <!-- parameter yaml:enableAdminVM --><!-- parameter json.dev:enableAdminVM -->`enableAdminVM` | `ENABLE_ADMIN_VM` | O | Y: `"false"`<br>J.dev: `"false"` | Enable Admin VM in common RG |
| <!-- parameter yaml:enableAksForAzureML --><!-- parameter json.dev:enableAksForAzureML -->`enableAksForAzureML` | `ENABLE_AKS_FOR_AZURE_ML` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy AKS for Azure ML inference |
| <!-- parameter yaml:enableAppInsightsDashboard --><!-- parameter json.dev:enableAppInsightsDashboard -->`enableAppInsightsDashboard` | `ENABLE_APPINSIGHTS_DASHBOARD` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Application Insights dashboard |
| <!-- parameter json.dev:enableApplicationInsights -->`enableApplicationInsights` | `ENABLE_APPLICATION_INSIGHTS` | O | Y: absent<br>J.dev: `"true"` | Workspace-based project Application Insights |
| <!-- parameter yaml:enableAzureAIVision --><!-- parameter json.dev:enableAzureAIVision -->`enableAzureAIVision` | `ENABLE_AZURE_AI_VISION` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure AI Vision |
| <!-- parameter yaml:enableAzureMachineLearning --><!-- parameter json.dev:enableAzureMachineLearning -->`enableAzureMachineLearning` | `ENABLE_AZURE_MACHINE_LEARNING` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure ML workspace |
| <!-- parameter yaml:enableAzureOpenAI --><!-- parameter json.dev:enableAzureOpenAI -->`enableAzureOpenAI` | `ENABLE_AZURE_OPENAI` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy standalone Azure OpenAI |
| <!-- parameter yaml:enableAzureSpeech --><!-- parameter json.dev:enableAzureSpeech -->`enableAzureSpeech` | `ENABLE_AZURE_SPEECH` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure AI Speech |
| <!-- parameter yaml:enableBing --><!-- parameter json.dev:enableBing -->`enableBing` | `ENABLE_BING` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Bing Search |
| <!-- parameter yaml:enableBingCustomSearch --><!-- parameter json.dev:enableBingCustomSearch -->`enableBingCustomSearch` | `ENABLE_BING_CUSTOM_SEARCH` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Bing Custom Search |
| <!-- parameter yaml:enableBotService --><!-- parameter json.dev:enableBotService -->`enableBotService` | `ENABLE_BOT_SERVICE` | O | Y: `"true"`<br>J.dev: `"true"` | Deploy Azure Bot Service keep-as-is: Required for Microsoft Foundry agent scenarios. |
| <!-- parameter yaml:enableContainerApps --><!-- parameter json.dev:enableContainerApps -->`enableContainerApps` | `ENABLE_CONTAINER_APPS` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure Container Apps |
| <!-- parameter yaml:enableContentSafety --><!-- parameter json.dev:enableContentSafety -->`enableContentSafety` | `ENABLE_CONTENT_SAFETY` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure AI Content Safety |
| <!-- parameter yaml:enableCosmosDB --><!-- parameter json.dev:enableCosmosDB -->`enableCosmosDB` | `ENABLE_COSMOS_DB` | C | Y: `"true"`<br>J.dev: `"true"` | Required capability-host thread and agent-history store for private Foundry standard agents. mandatory: Required capability-host thread and agent-history store for private Foundry standard agents. Required together for the standard private-agent capability-host architecture; not universal across all deployment paths. |
| <!-- parameter yaml:enableDatabricks --><!-- parameter json.dev:enableDatabricks -->`enableDatabricks` | `ENABLE_DATABRICKS` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Databricks workspace |
| <!-- parameter yaml:enableDatafactory --><!-- parameter json.dev:enableDatafactory -->`enableDatafactory` | `ENABLE_DATAFACTORY` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure Data Factory in project RG |
| <!-- parameter yaml:enableDatafactoryCommon --><!-- parameter json.dev:enableDatafactoryCommon -->`enableDatafactoryCommon` | `ENABLE_DATAFACTORY_COMMON` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure Data Factory in common RG |
| <!-- parameter yaml:enableDefenderforAIResourceLevel --><!-- parameter json.dev:enableDefenderforAIResourceLevel -->`enableDefenderforAIResourceLevel` | `ENABLE_DEFENDER_FOR_AI_RESOURCE_LEVEL` | O | Y: `"false"`<br>J.dev: `"false"` | Defender for AI at resource level otherwise: true, enable Microsoft Defender for AI at per-resource level. |
| <!-- parameter yaml:enableDefenderforAISubLevel --><!-- parameter json.dev:enableDefenderforAISubLevel -->`enableDefenderforAISubLevel` | `ENABLE_DEFENDER_FOR_AI_SUB_LEVEL` | O | Y: `"false"`<br>J.dev: `"false"` | Defender for AI at subscription level otherwise: true, enable Microsoft Defender for AI at subscription level. |
| <!-- parameter yaml:enableDeleteForDisabledResources --><!-- parameter json.dev:enableDeleteForDisabledResources -->`enableDeleteForDisabledResources` | `ENABLE_DELETE_FOR_DISABLED_RESOURCES` | O | Y: `"false"`<br>J.dev: `"false"` | Delete disabled services otherwise: false, keeps all existing resources regardless of ENABLE_* flags. |
| <!-- parameter yaml:enableElasticsearch --><!-- parameter json.dev:enableElasticsearch -->`enableElasticsearch` | `ENABLE_ELASTICSEARCH` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Elasticsearch keep-as-is: Elastic Cloud managed service. |
| <!-- parameter yaml:enableEventHubs --><!-- parameter json.dev:enableEventHubs -->`enableEventHubs` | `ENABLE_EVENT_HUBS` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure Event Hubs |
| <!-- parameter yaml:enableFunction --><!-- parameter json.dev:enableFunction -->`enableFunction` | `ENABLE_FUNCTION` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure Function App |
| <!-- parameter yaml:enableLogicApps --><!-- parameter json.dev:enableLogicApps -->`enableLogicApps` | `ENABLE_LOGIC_APPS` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure Logic Apps |
| <!-- parameter yaml:enablePostgreSQL --><!-- parameter json.dev:enablePostgreSQL -->`enablePostgreSQL` | `ENABLE_POSTGRESQL` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure PostgreSQL |
| <!-- parameter yaml:enableRedisCache --><!-- parameter json.dev:enableRedisCache -->`enableRedisCache` | `ENABLE_REDIS_CACHE` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure Cache for Redis |
| <!-- parameter yaml:enableRetries --><!-- parameter json.dev:enableRetries -->`enableRetries` | `ENABLE_RETRIES` | O | Y: `"false"`<br>J.dev: `"false"` | Enable automatic job retries otherwise: true, enable automatic retries on failure for GenAI services deployment. |
| <!-- parameter yaml:enableSQLDatabase --><!-- parameter json.dev:enableSQLDatabase -->`enableSQLDatabase` | `ENABLE_SQL_DATABASE` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure SQL Database |
| <!-- parameter yaml:enableWebApp --><!-- parameter json.dev:enableWebApp -->`enableWebApp` | `ENABLE_WEBAPP`, `ENABLE_WEB_APP` (not in .env template) | O | Y: `"false"`<br>J.dev: `"false"` | Deploy Azure Web App |
| <!-- parameter yaml:foundryApiManagementResourceId --><!-- parameter json.dev:foundryApiManagementResourceId -->`foundryApiManagementResourceId` | `FOUNDRY_API_MANAGEMENT_RESOURCE_ID` | O | Y: `""`<br>J.dev: `""` | APIM resource ID for Foundry integration otherwise: provide existing API Management resource ID to integrate with Microsoft Foundry. |
| <!-- parameter yaml:foundryDeploymentType --><!-- parameter json.dev:foundryDeploymentType -->`foundryDeploymentType` | `FOUNDRY_DEPLOYMENT_TYPE` | O | Y: `"2"`<br>J.dev: `"2"` | &lt;deprecated&gt;Retained for configuration compatibility. AI Foundry now always uses the second-option account deployment. |
| <!-- parameter yaml:kongGatewayApimHost --><!-- parameter json.dev:kongGatewayApimHost -->`kongGatewayApimHost` | `KONG_GATEWAY_APIM_HOST` | C | Y: `""`<br>J.dev: `""` | APIM gateway hostname without protocol/path. Required by the separate AI gateway workflow when Kong is enabled; the consumer API key is an environment secret. |
| <!-- parameter yaml:kongGatewayCpu --><!-- parameter json.dev:kongGatewayCpu -->`kongGatewayCpu` | `KONG_GATEWAY_CPU` | O | Y: `2`<br>J.dev: `2` | Kong gateway cpu. |
| <!-- parameter yaml:kongGatewayImage --><!-- parameter json.dev:kongGatewayImage -->`kongGatewayImage` | `KONG_GATEWAY_IMAGE` | O | Y: `"kong/kong-gateway:3.9"`<br>J.dev: `"kong/kong-gateway:3.9"` | Kong gateway image. |
| <!-- parameter yaml:kongGatewayMemoryGb --><!-- parameter json.dev:kongGatewayMemoryGb -->`kongGatewayMemoryGb` | `KONG_GATEWAY_MEMORY_GB` | O | Y: `4`<br>J.dev: `4` | Kong gateway memory gb. |
| <!-- parameter yaml:serviceSettingDeployProjectVM --><!-- parameter json.dev:serviceSettingDeployProjectVM -->`serviceSettingDeployProjectVM` | `SERVICE_SETTING_DEPLOY_PROJECT_VM` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy VM in project resource group otherwise: true, deploy a jumpbox VM for use with Azure Bastion. |
| <!-- parameter yaml:updateAIFoundry --><!-- parameter json.dev:updateAIFoundry -->`updateAIFoundry` | `UPDATE_AI_FOUNDRY` | O | Y: `"false"`<br>J.dev: `"false"` | Update AI Foundry properties otherwise: true, re-run to update AI Foundry properties and RBAC. |

### Networking, DNS and existing resources

| YAML / JSON key | GHA binding(s) | M/C/O | Source defaults | Description / conditions |
|---|---|---|---|---|
| <!-- parameter yaml:BYOContributorRoleID --><!-- parameter json.dev:BYOContributorRoleID -->`BYOContributorRoleID` | `BYO_CONTRIBUTOR_ROLE_ID` | O | Y: `"b24988ac-6180-42a0-ab88-20f7382dd24c"`<br>J.dev: `"b24988ac-6180-42a0-ab88-20f7382dd24c"` | Contributor role ID keep-as-is: Azure built-in Contributor. otherwise: provide a custom role ID for finer-grained access control. |
| <!-- parameter yaml:BYO_subnets --><!-- parameter json.dev:BYO_subnets -->`BYO_subnets` | `BYO_SUBNETS` | O | Y: `"false"`<br>J.dev: `"false"` | Bring your own subnets otherwise: true, uses pre-existing subnets defined by the BYO subnet variables below. |
| <!-- parameter yaml:acr_IP_whitelist --><!-- parameter json.dev:acr_IP_whitelist -->`acr_IP_whitelist` | `ACR_IP_WHITELIST` | O | Y: `""`<br>J.dev: `""` | ACR IP allowlist otherwise: provide comma-separated IPv4 addresses if ACR network restrictions are needed. |
| <!-- parameter yaml:allowPublicAccessWhenBehindVnet --><!-- parameter json.dev:allowPublicAccessWhenBehindVnet -->`allowPublicAccessWhenBehindVnet` | `ALLOW_PUBLIC_ACCESS_WHEN_BEHIND_VNET` (not in .env template) | O | Y: `"true"`<br>J.dev: `"true"` | Public UI access when behind vNet recommended: false to enable fully private networking. |
| <!-- parameter yaml:byoASEv3 --><!-- parameter json.dev:byoASEv3 -->`byoASEv3` | `BYO_ASEV3` | O | Y: `"false"`<br>J.dev: `"false"` | Use BYO App Service Environment v3 otherwise: true, use an existing ASEv3 specified in byoAseFullResourceId. |
| <!-- parameter yaml:byoAseAppServicePlanResourceId --><!-- parameter json.dev:byoAseAppServicePlanResourceId -->`byoAseAppServicePlanResourceId` | `BYO_ASE_APP_SERVICE_PLAN_RESOURCE_ID` | O | Y: `""`<br>J.dev: `""` | BYO App Service Plan resource ID otherwise: provide full ARM resource ID of an existing App Service Plan within the ASEv3. |
| <!-- parameter yaml:byoAseFullResourceId --><!-- parameter json.dev:byoAseFullResourceId -->`byoAseFullResourceId` | `BYO_ASE_FULL_RESOURCE_ID` | C | Y: `"subscriptions/...yourASEnameS2"`<br>J.dev: `"subscriptions/...yourASEnameS2"` | BYO ASEv3 ARM resource ID. Note - remove leading slash / in Resource ID mandatory: if byoASEv3:'true' ensure: full ARM resource ID of the existing ASEv3. |
| <!-- parameter yaml:centralDnsZoneByPolicyInHub --><!-- parameter json.dev:centralDnsZoneByPolicyInHub -->`centralDnsZoneByPolicyInHub` | `CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB` | O | Y: `"false"`<br>J.dev: `false` | Centralized DNS via Hub policy otherwise: true, uses central private DNS zones in HUB resource group managed by Azure Policy. |
| <!-- parameter yaml:common_bastion_subnet_cidr --><!-- parameter json.dev:common_bastion_subnet_cidr -->`common_bastion_subnet_cidr` | `COMMON_BASTION_SUBNET_CIDR` | M | Y: `"172.16.XX.192/26"`<br>J.dev: `"172.16.XX.192/26"` | Bastion subnet CIDR mandatory: Bastion subnet CIDR keep-as-is: XX replaced by dev_cidr_range. ensure: within common_vnet_cidr. |
| <!-- parameter yaml:common_bastion_subnet_name --><!-- parameter json.dev:common_bastion_subnet_name -->`common_bastion_subnet_name` | `COMMON_BASTION_SUBNET_NAME` | M | Y: `"AzureBastionSubnet"`<br>J.dev: `"AzureBastionSubnet"` | Bastion subnet name mandatory: Bastion subnet name keep-as-is: Required name for Azure Bastion. ensure: within common_vnet_cidr. |
| <!-- parameter yaml:common_pbi_subnet_cidr --><!-- parameter json.dev:common_pbi_subnet_cidr -->`common_pbi_subnet_cidr` | `COMMON_PBI_SUBNET_CIDR` | M | Y: `"172.16.XX.128/26"`<br>J.dev: `"172.16.XX.128/26"` | Power BI gateway subnet CIDR mandatory: Power BI gateway subnet CIDR keep-as-is: XX replaced by dev_cidr_range. ensure: within common_vnet_cidr. |
| <!-- parameter yaml:common_pbi_subnet_name --><!-- parameter json.dev:common_pbi_subnet_name -->`common_pbi_subnet_name` | `COMMON_PBI_SUBNET_NAME` | M | Y: `"snet-esml-cmn-pbi-001"`<br>J.dev: `"snet-esml-cmn-pbi-001"` | Power BI gateway subnet name mandatory: Power BI gateway subnet name ensure: within common_vnet_cidr. |
| <!-- parameter yaml:common_subnet_cidr --><!-- parameter json.dev:common_subnet_cidr -->`common_subnet_cidr` | `COMMON_SUBNET_CIDR` | M | Y: `"172.16.XX.0/26"`<br>J.dev: `"172.16.XX.0/26"` | Common subnet CIDR mandatory: Common subnet CIDR keep-as-is: XX replaced by dev_cidr_range. ensure: within common_vnet_cidr. |
| <!-- parameter yaml:common_subnet_name --><!-- parameter json.dev:common_subnet_name -->`common_subnet_name` | `COMMON_SUBNET_NAME` (not in .env template), `SUBNET_COMMON_BASE` | O | Y: `"snet-esml-cmn-001"`<br>J.dev: `"snet-esml-cmn-001"` | Common subnet name |
| <!-- parameter yaml:common_subnet_scoring_cidr --><!-- parameter json.dev:common_subnet_scoring_cidr -->`common_subnet_scoring_cidr` | `COMMON_SUBNET_SCORING_CIDR` | M | Y: `"172.16.XX.64/26"`<br>J.dev: `"172.16.XX.64/26"` | Scoring subnet CIDR mandatory: Scoring subnet CIDR keep-as-is: XX replaced by dev_cidr_range. ensure: within common_vnet_cidr. |
| <!-- parameter yaml:common_vnet_cidr --><!-- parameter json.dev:common_vnet_cidr -->`common_vnet_cidr` | `COMMON_VNET_CIDR` | M | Y: `"172.16.XX.0/18"`<br>J.dev: `"172.16.XX.0/18"` | Common vNet CIDR mandatory: Common vNet CIDR keep-as-is: XX is the network-aligned per-environment octet; Dev/Stage/Prod must not overlap. Address intent only, not actual peering. |
| <!-- parameter yaml:dev_cidr_range --><!-- parameter json.dev:dev_cidr_range -->`dev_cidr_range` | `DEV_CIDR_RANGE` | M | Y: `"0"`<br>J.dev: `"0"` | DEV network-aligned XX value mandatory: DEV network-aligned XX value keep-as-is: VNet 172.16.0.0/18. |
| <!-- parameter yaml:disableAgentNetworkInjection --><!-- parameter json.dev:disableAgentNetworkInjection -->`disableAgentNetworkInjection` | `DISABLE_AGENT_NETWORK_INJECTION` | O | Y: `"false"`<br>J.dev: `"false"` | Disable agent network injection keep-as-is: false, requires Container Apps subnet in 172.16.0.0/12 or 192.168.0.0/16. otherwise: true, disables network injection. |
| <!-- parameter yaml:disableSubnetJoinAction --><!-- parameter json.dev:disableSubnetJoinAction -->`disableSubnetJoinAction` | `DISABLE_SUBNET_JOIN_ACTION` | O | Y: `"false"`<br>J.dev: `"false"` | Disable VNet subnet join RBAC recommended: false, grants Network Contributor role for subnet join actions (required for APIM, Container Apps, AKS). otherwise: true, skip if subnet permissions managed externally. |
| <!-- parameter yaml:enablePublicAccessWithPerimeter --><!-- parameter json.dev:enablePublicAccessWithPerimeter -->`enablePublicAccessWithPerimeter` | `ENABLE_PUBLIC_ACCESS_WITH_PERIMETER` | O | Y: `"true"`<br>J.dev: `"true"` | Public access with network perimeter recommended: false to enable fully private networking. |
| <!-- parameter yaml:enablePublicGenAIAccess --><!-- parameter json.dev:enablePublicGenAIAccess -->`enablePublicGenAIAccess` | `ENABLE_PUBLIC_GENAI_ACCESS` | O | Y: `"true"`<br>J.dev: `"true"` | Public GenAI access (control plane) recommended: false to enable fully private networking. |
| <!-- parameter yaml:kongGatewaySubnetCidr --><!-- parameter json.dev:kongGatewaySubnetCidr -->`kongGatewaySubnetCidr` | `KONG_GATEWAY_SUBNET_CIDR` | C | Y: `""`<br>J.dev: `""` | Dedicated, unused /28 or larger subnet. Required by the separate AI gateway workflow when Kong is enabled; the consumer API key is an environment secret. |
| <!-- parameter yaml:kongGatewaySubnetName --><!-- parameter json.dev:kongGatewaySubnetName -->`kongGatewaySubnetName` | `KONG_GATEWAY_SUBNET_NAME` | O | Y: `"snet-kong-001"`<br>J.dev: `"snet-kong-001"` | Kong gateway subnet name. |
| <!-- parameter yaml:kongGatewayVnetName --><!-- parameter json.dev:kongGatewayVnetName -->`kongGatewayVnetName` | `KONG_GATEWAY_VNET_NAME` | C | Y: `""`<br>J.dev: `""` | Kong gateway vnet name. Required by the separate AI gateway workflow when Kong is enabled; the consumer API key is an environment secret. |
| <!-- parameter yaml:kongGatewayVnetResourceGroup --><!-- parameter json.dev:kongGatewayVnetResourceGroup -->`kongGatewayVnetResourceGroup` | `KONG_GATEWAY_VNET_RESOURCE_GROUP` | C | Y: `""`<br>J.dev: `""` | Kong gateway vnet resource group. Required by the separate AI gateway workflow when Kong is enabled; the consumer API key is an environment secret. |
| <!-- parameter yaml:network_env_dev --><!-- parameter json.dev:network_env_dev -->`network_env_dev` | `DEV_NETWORK_ENV` | O | Y: `"dev-"`<br>J.dev: `"dev-"` | DEV environment prefix for BYO subnets otherwise: set to empty string if not using environment-prefixed naming. |
| <!-- parameter yaml:network_env_prod --><!-- parameter json.dev:network_env_prod -->`network_env_prod` | `PROD_NETWORK_ENV` | O | Y: `"prd-"`<br>J.dev: `"prd-"` | PROD environment prefix for BYO subnets otherwise: "prod-", "pr-", or empty string. |
| <!-- parameter yaml:network_env_stage --><!-- parameter json.dev:network_env_stage -->`network_env_stage` | `STAGE_NETWORK_ENV` | O | Y: `"tst2-"`<br>J.dev: `"tst2-"` | STAGE environment prefix for BYO subnets otherwise: "test-", "tst-", or empty string. |
| <!-- parameter yaml:privDnsResourceGroup_param --><!-- parameter json.dev:privDnsResourceGroup_param -->`privDnsResourceGroup_param` | `PRIV_DNS_RESOURCE_GROUP_PARAM` | C | Y: `"<todo>_ResourceGroup_name"`<br>J.dev: `"<todo>_ResourceGroup_name"` | Hub DNS resource group mandatory: if centralDnsZoneByPolicyInHub:'true' ensure: Hub connectivity resource group where central private DNS zones are deployed. |
| <!-- parameter yaml:privDnsSubscription_param --><!-- parameter json.dev:privDnsSubscription_param -->`privDnsSubscription_param` | `PRIV_DNS_SUBSCRIPTION_PARAM` | C | Y: `"<todo>_SubscriptionID"`<br>J.dev: `"<todo>_SubscriptionID"` | Hub DNS subscription ID mandatory: if centralDnsZoneByPolicyInHub:'true' ensure: Hub connectivity subscription ID where central private DNS zones are deployed. |
| <!-- parameter yaml:prod_cidr_range --><!-- parameter json.dev:prod_cidr_range -->`prod_cidr_range` | `PROD_CIDR_RANGE` | M | Y: `"128"`<br>J.dev: `"128"` | PROD network-aligned XX value mandatory: PROD network-aligned XX value keep-as-is: VNet 172.16.128.0/18. |
| <!-- parameter yaml:project_IP_whitelist --><!-- parameter json.dev:project_IP_whitelist -->`project_IP_whitelist` | `PROJECT_IP_WHITELIST` (not in .env template), `PROJECT_MEMBERS_IP_ADDRESS` | C | Y: `""`<br>J.dev: `""` | Project UI IP allowlist mandatory: if using IP-whitelisting networking mode ensure: comma-separated IPv4 addresses without spaces, e.g. "10.123.456.10,124.56.78.0/24". |
| <!-- parameter yaml:runNetworkingVar --><!-- parameter json.dev:runNetworkingVar -->`runNetworkingVar` | `RUN_JOB1_NETWORKING` | M | Y: `"true"`<br>J.dev: `"true"` | Run networking module mandatory: Run networking module keep-as-is: true when creating or updating a project. otherwise: false, to skip networking on service-only updates. |
| <!-- parameter yaml:scaling-mode --><!-- parameter json.dev:scaling-mode -->`scaling-mode` | `SCALING_MODE` | O | Y: `"shared-subscriptions"`<br>J.dev: `"shared-subscriptions"` | Address-planning preset: own-subscriptions or shared-subscriptions. Does not create subscriptions, resize networks, or establish peering. |
| <!-- parameter yaml:subnetCommon --><!-- parameter json.dev:subnetCommon -->`subnetCommon` | `SUBNET_COMMON` | C | Y: `"snet-dev-esml-cmn-001"`<br>J.dev: `"snet-dev-esml-cmn-001"` | BYO common subnet name mandatory: if BYO_subnets:'true' ensure: subnet exists in your vNet. |
| <!-- parameter yaml:subnetCommonPowerbiGw --><!-- parameter json.dev:subnetCommonPowerbiGw -->`subnetCommonPowerbiGw` | `SUBNET_COMMON_POWERBI_GW` | C | Y: `"snet-esml-cmn-pbi-001"`<br>J.dev: `"snet-esml-cmn-pbi-001"` | BYO Power BI gateway subnet name mandatory: if BYO_subnets:'true' ensure: subnet exists. |
| <!-- parameter yaml:subnetCommonScoring --><!-- parameter json.dev:subnetCommonScoring -->`subnetCommonScoring` | `SUBNET_COMMON_SCORING` | C | Y: `"snet-<network_env>esml-cmn-001-scoring"`<br>J.dev: `"snet-<network_env>esml-cmn-001-scoring"` | BYO scoring subnet name mandatory: if BYO_subnets:'true' ensure: subnet exists. |
| <!-- parameter yaml:subnetProjACA --><!-- parameter json.dev:subnetProjACA -->`subnetProjACA` | `SUBNET_PROJ_ACA` | C | Y: `"snt-prj<xxx>-aca"`<br>J.dev: `"snt-prj<xxx>-aca"` | ContainerApps subnet. BYO project Container Apps subnet mandatory: if BYO_subnets:'true' ensure: subnet exists and CIDR is in 172.16.0.0/12 or 192.168.0.0/16 if disableAgentNetworkInjection:'false'. |
| <!-- parameter yaml:subnetProjACA2 --><!-- parameter json.dev:subnetProjACA2 -->`subnetProjACA2` | `SUBNET_PROJ_ACA2` | C | Y: `"snt-prj<xxx>-aca-002"`<br>J.dev: `"snt-prj<xxx>-aca-002"` | Agent subnet. BYO project secondary Container Apps subnet mandatory: if BYO_subnets:'true' AND enableAIFoundry:'true' AND disableAgentNetworkInjection is 'false' |
| <!-- parameter yaml:subnetProjAKS --><!-- parameter json.dev:subnetProjAKS -->`subnetProjAKS` | `SUBNET_PROJ_AKS` | C | Y: `"snt-prj<xxx>-aks"`<br>J.dev: `"snt-prj<xxx>-aks"` | BYO project AKS subnet name mandatory: if BYO_subnets:'true' ensure: subnet exists. |
| <!-- parameter yaml:subnetProjAKS2 --><!-- parameter json.dev:subnetProjAKS2 -->`subnetProjAKS2` | `SUBNET_PROJ_AKS2` | C | Y: `"snt-<network_env>prj<xxx>-aks2"`<br>J.dev: `"snt-<network_env>prj<xxx>-aks2"` | BYO project secondary AKS subnet mandatory: if BYO_subnets:'true' ensure: subnet exists. |
| <!-- parameter yaml:subnetProjDatabricksPrivate --><!-- parameter json.dev:subnetProjDatabricksPrivate -->`subnetProjDatabricksPrivate` | `SUBNET_PROJ_DATABRICKS_PRIVATE`, `SUBNET_PROJ_DBX_PRIVATE` (not in .env template) | C | Y: `"snt-prj<xxx>-dbxpriv"`<br>J.dev: `"snt-prj<xxx>-dbxpriv"` | BYO Databricks private subnet mandatory: if BYO_subnets:'true' and enableDatabricks:'true'. |
| <!-- parameter yaml:subnetProjDatabricksPublic --><!-- parameter json.dev:subnetProjDatabricksPublic -->`subnetProjDatabricksPublic` | `SUBNET_PROJ_DATABRICKS_PUBLIC`, `SUBNET_PROJ_DBX_PUBLIC` (not in .env template) | C | Y: `"snt-prj001-dbxpub"`<br>J.dev: `"snt-prj001-dbxpub"` | BYO Databricks public subnet mandatory: if BYO_subnets:'true' and enableDatabricks:'true'. |
| <!-- parameter yaml:subnetProjGenAI --><!-- parameter json.dev:subnetProjGenAI -->`subnetProjGenAI` | `SUBNET_PROJ_GENAI` | C | Y: `"snt-dev-prj<xxx>-genai"`<br>J.dev: `"snt-dev-prj<xxx>-genai"` | BYO project GenAI subnet name mandatory: if BYO_subnets:'true' ensure: subnet exists. |
| <!-- parameter yaml:subnetProjWebapp --><!-- parameter json.dev:subnetProjWebapp -->`subnetProjWebapp` | `SUBNET_PROJ_WEBAPP` | C | Y: `"snt-prj<xxx>-webapp"`<br>J.dev: `"snt-prj<xxx>-webapp"` | App Service/Function VNet integration subnet (delegated to Microsoft.Web/serverFarms) mandatory: if BYO_subnets:'true' AND (enableWebApp:'true' OR enableFunction:'true') ensure: subnet exists. |
| <!-- parameter yaml:test_cidr_range --><!-- parameter json.dev:test_cidr_range -->`test_cidr_range` | `STAGE_CIDR_RANGE` | M | Y: `"64"`<br>J.dev: `"64"` | STAGE network-aligned XX value mandatory: STAGE network-aligned XX value keep-as-is: VNet 172.16.64.0/18. |
| <!-- parameter yaml:vnetNameBase --><!-- parameter json.dev:vnetNameBase -->`vnetNameBase` | `VNET_NAME_BASE` | O | Y: `"vnt-esmlcmn"`<br>J.dev: `"vnt-esmlcmn"` | Common vNet base name otherwise: ignored if vnetNameFull_param is set (BYOvNet). |
| <!-- parameter yaml:vnetNameFull_param --><!-- parameter json.dev:vnetNameFull_param -->`vnetNameFull_param` | `VNET_NAME_FULL_PARAM` | O | Y: `""`<br>J.dev: `""` | BYO vNet full name otherwise: provide the full name of your existing vNet. |
| <!-- parameter yaml:vnetResourceGroupBase --><!-- parameter json.dev:vnetResourceGroupBase -->`vnetResourceGroupBase` | `VNET_RESOURCE_GROUP_BASE` | O | Y: `"esml-common"`<br>J.dev: `"esml-common"` | Common vNet resource group base otherwise: ignored if vnetResourceGroup_param is set (BYOvNet). |
| <!-- parameter yaml:vnetResourceGroup_param --><!-- parameter json.dev:vnetResourceGroup_param -->`vnetResourceGroup_param` | `VNET_RESOURCE_GROUP_PARAM` | O | Y: `""`<br>J.dev: `""` | BYO vNet resource group otherwise: provide the full RG name of your existing vNet. |

### Factory, project, naming and orchestration

| YAML / JSON key | GHA binding(s) | M/C/O | Source defaults | Description / conditions |
|---|---|---|---|---|
| <!-- parameter json.dev:GITHUB_NEW_REPO -->`GITHUB_NEW_REPO` | `GITHUB_NEW_REPO` | M | Y: absent<br>J.dev: `""` | New GitHub repository path mandatory: New GitHub repository path ensure: format: |
| <!-- parameter json.dev:GITHUB_NEW_REPO_VISIBILITY -->`GITHUB_NEW_REPO_VISIBILITY` | `GITHUB_NEW_REPO_VISIBILITY` | O | Y: absent<br>J.dev: `"public"` | New repository visibility otherwise: private or internal. |
| <!-- parameter json.dev:GITHUB_TEMPLATE_REPO -->`GITHUB_TEMPLATE_REPO` | `GITHUB_TEMPLATE_REPO` | O | Y: absent<br>J.dev: `"azure/enterprise-scale-aifactory"` | GitHub template repository keep-as-is: Leave as-is if BYO repo. |
| <!-- parameter json.dev:GITHUB_USERNAME -->`GITHUB_USERNAME` | `GITHUB_USERNAME` | M | Y: absent<br>J.dev: `""` | GitHub username or org mandatory: GitHub username or org |
| <!-- parameter json.dev:GITHUB_USE_SSH -->`GITHUB_USE_SSH` | `GITHUB_USE_SSH` | O | Y: absent<br>J.dev: `"false"` | Use SSH for git operations otherwise: true, use SSH instead of HTTPS. |
| <!-- parameter yaml:aca_w_registry_image --><!-- parameter json.dev:aca_w_registry_image -->`aca_w_registry_image` | `ACA_W_REGISTRY_IMAGE` | O | Y: `"mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"`<br>J.dev: `"mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"` | Container Apps default image otherwise: replace with your own ACR image. |
| <!-- parameter yaml:adminUsername --><!-- parameter json.dev:adminUsername -->`adminUsername` | `ADMIN_USERNAME` | O | Y: `"esmladmin"`<br>J.dev: `"esmladmin"` | VM admin username |
| <!-- parameter yaml:admin_aiSearchTier --><!-- parameter json.dev:admin_aiSearchTier -->`admin_aiSearchTier` | `ADMIN_AISEARCH_TIER`, `ADMIN_AI_SEARCH_TIER` | M | Y: `"basic"`<br>J.dev: `"basic"` | AI Search SKU tier mandatory: AI Search SKU tier ensure: 'free' is not allowed when using private endpoints. ['free', 'basic', 'standard', 'standard2', 'standard3', 'storage_optimized_l1', 'storage_optimized_l2'] |
| <!-- parameter yaml:admin_aifactoryPrefixRG --><!-- parameter json.dev:admin_aifactoryPrefixRG -->`admin_aifactoryPrefixRG` | `AIFACTORY_PREFIX` | O | Y: `"mrvel-1-"`<br>J.dev: `"mrvel-1-"` | AI Factory resource group prefix keep-as-is: Max 6 chars. otherwise: set your company prefix, e.g. "acme-ai-", "contoso-". |
| <!-- parameter yaml:admin_aifactorySuffixRG --><!-- parameter json.dev:admin_aifactorySuffixRG -->`admin_aifactorySuffixRG` | `AIFACTORY_SUFFIX` | M | Y: `"-001"`<br>J.dev: `"-001"` | AI Factory scaleset suffix mandatory: AI Factory scaleset suffix keep-as-is: For 1st scaleset. otherwise: increment to '-002', '-003' for additional scalesets. |
| <!-- parameter yaml:admin_commonResourceSuffix --><!-- parameter json.dev:admin_commonResourceSuffix -->`admin_commonResourceSuffix` | `ADMIN_COMMON_RESOURCE_SUFFIX` | O | Y: `"-001"`<br>J.dev: `"-001"` | Common resources suffix otherwise: change to reprovision new services in the same common RG while keeping old ones. |
| <!-- parameter yaml:admin_hybridBenefit --><!-- parameter json.dev:admin_hybridBenefit -->`admin_hybridBenefit` | `ADMIN_HYBRID_BENEFIT` | O | Y: `"false"`<br>J.dev: `"false"` | Azure Hybrid Benefit for VMs otherwise: true, if you have eligible Windows licenses with Software Assurance (pay-as-you-go avoided). |
| <!-- parameter yaml:admin_ip_fw --><!-- parameter json.dev:admin_ip_fw -->`admin_ip_fw` | `ADMIN_IP_FW` | O | Y: `""`<br>J.dev: `""` | Leave empty. Will be automatically set by the pipeline to the build agent IP. keep-as-is: Leave empty. Will be automatically set by the pipeline to the build agent IP. |
| <!-- parameter yaml:admin_keyvaultSoftDeleteDays --><!-- parameter json.dev:admin_keyvaultSoftDeleteDays -->`admin_keyvaultSoftDeleteDays` | `KEYVAULT_SOFT_DELETE` | C | Y: `7`<br>J.dev: `7` | Key Vault soft delete days mandatory: if cmk:'true' (purge protection required). otherwise: 90 days recommended; 0 to disable. |
| <!-- parameter yaml:admin_location --><!-- parameter json.dev:admin_location -->`admin_location` | `AIFACTORY_LOCATION` | M | Y: `"eastus2"`<br>J.dev: `"eastus2"` | Azure region mandatory: Azure region |
| <!-- parameter yaml:admin_locationSuffix --><!-- parameter json.dev:admin_locationSuffix -->`admin_locationSuffix` | `AIFACTORY_LOCATION_SHORT` | M | Y: `"eus2"`<br>J.dev: `"eus2"` | Region short name mandatory: Region short name |
| <!-- parameter yaml:admin_prjResourceSuffix --><!-- parameter json.dev:admin_prjResourceSuffix -->`admin_prjResourceSuffix` | `ADMIN_PRJ_RESOURCE_SUFFIX` | O | Y: `"-001"`<br>J.dev: `"-001"` | Project resources suffix otherwise: change to reprovision new services in the same project RG while keeping old ones. |
| <!-- parameter yaml:admin_projectType --><!-- parameter json.dev:admin_projectType -->`admin_projectType` | `PROJECT_TYPE` | M | Y: `"all"`<br>J.dev: `"all"` |  |
| <!-- parameter yaml:admin_semanticSearchTier --><!-- parameter json.dev:admin_semanticSearchTier -->`admin_semanticSearchTier` | `ADMIN_SEMANTIC_SEARCH_TIER`, `AISEARCH_SEMANTIC_TIER` | M | Y: `"free"`<br>J.dev: `"free"` | Semantic search tier mandatory: Semantic search tier |
| <!-- parameter yaml:aiSearchLocation --><!-- parameter json.dev:aiSearchLocation -->`aiSearchLocation` | `AI_SEARCH_LOCATION` | O | Y: `""`<br>J.dev: `""` | AI Search region override. Empty keeps the project region; use another supported region only when regional Search capacity is unavailable. |
| <!-- parameter yaml:aifactory-dash-01 --><!-- parameter json.dev:aifactory-dash-01 -->`aifactory-dash-01` | `AIFACTORY_DASHBOARD_URL` | O | Y: `""`<br>J.dev: `""` | Existing Azure Portal AI Factory dashboard URL; never deploys a dashboard. |
| <!-- parameter yaml:aifactory_branch_chosen --><!-- parameter json.dev:aifactory_branch_chosen -->`aifactory_branch_chosen` | `AIFACTORY_BRANCH_CHOSEN` | O | Y: `"release/v1.24"`<br>J.dev: `"release/v1.24"` | Submodule release branch |
| <!-- parameter yaml:aifactory_salt --><!-- parameter json.dev:aifactory_salt -->`aifactory_salt` | `AIFACTORY_SALT` | O | Y: `""`<br>J.dev: `""` | Leave empty, 5 characters.  A deteministic unique value, from COMMON RG |
| <!-- parameter yaml:aifactory_salt_random --><!-- parameter json.dev:aifactory_salt_random -->`aifactory_salt_random` | `AIFACTORY_SALT_RANDOM` | O | Y: `""`<br>J.dev: `""` | Leave empty. 10-character unique random value derived from User-Assigned Managed Identity. Auto-populated by the pipeline. keep-as-is: Leave empty. 10-character unique random value derived from User-Assigned Managed Identity. Auto-populated by the pipeline. |
| <!-- parameter yaml:aifactory_version_major --><!-- parameter json.dev:aifactory_version_major -->`aifactory_version_major` | `AIFACTORY_VERSION_MAJOR` | O | Y: `"1"`<br>J.dev: `"1"` | AI Factory major version keep-as-is: Used to determine which bicep files to use. |
| <!-- parameter yaml:aifactory_version_minor --><!-- parameter json.dev:aifactory_version_minor -->`aifactory_version_minor` | `AIFACTORY_VERSION_MINOR` | O | Y: `"24"`<br>J.dev: `"24"` | AI Factory minor version keep-as-is: 2025-09-20: 24 = release/v1.24 |
| <!-- parameter yaml:aseSku --><!-- parameter json.dev:aseSku -->`aseSku` | `ASE_SKU` | O | Y: `"IsolatedV2"`<br>J.dev: `"IsolatedV2"` | App Service Environment SKU keep-as-is: Used only if byoASEv3:'true' or a dedicated ASE is provisioned. |
| <!-- parameter yaml:aseSkuCode --><!-- parameter json.dev:aseSkuCode -->`aseSkuCode` | `ASE_SKU_CODE` | O | Y: `"I1v2"`<br>J.dev: `"I1v2"` | App Service Environment SKU code |
| <!-- parameter yaml:aseSkuWorkers --><!-- parameter json.dev:aseSkuWorkers -->`aseSkuWorkers` | `ASE_SKU_WORKERS` | O | Y: `1`<br>J.dev: `1` | App Service Environment worker count |
| <!-- parameter yaml:bastion_custom_name --><!-- parameter json.dev:bastion_custom_name -->`bastion_custom_name` | `BASTION_CUSTOM_NAME` | O | Y: `""`<br>J.dev: `""` | Bastion name override for common RG RBAC keep-as-is: Empty uses the standard Bastion naming convention. |
| <!-- parameter yaml:bastion_subscription_resource_group --><!-- parameter json.dev:bastion_subscription_resource_group -->`bastion_subscription_resource_group` | `BASTION_SUBSCRIPTION_RESOURCE_GROUP` | O | Y: `""`<br>J.dev: `""` | Bastion resource group override for common RG RBAC keep-as-is: Empty uses the common resource group. |
| <!-- parameter yaml:bingCustomSearchSku --><!-- parameter json.dev:bingCustomSearchSku -->`bingCustomSearchSku` | `BING_CUSTOM_SEARCH_SKU` | O | Y: `"G2"`<br>J.dev: `"G2"` | Bing Custom Search SKU keep-as-is: ['G2'] G2 is custom search with grounding. |
| <!-- parameter yaml:commonLakeNamePrefixMax8chars --><!-- parameter json.dev:commonLakeNamePrefixMax8chars -->`commonLakeNamePrefixMax8chars` | `COMMON_LAKE_NAME_PREFIX_MAX8CHARS` (not in .env template), `LAKE_PREFIX` | O | Y: `"mrvel"`<br>J.dev: `"mrvel"` | Data lake storage name prefix keep-as-is: Max 8 characters. |
| <!-- parameter yaml:commonResourceGroup_param --><!-- parameter json.dev:commonResourceGroup_param -->`commonResourceGroup_param` | `COMMON_RESOURCE_GROUP_PARAM` | O | Y: `""`<br>J.dev: `""` | BYO common resource group name otherwise: provide a custom name for the common resource group. |
| <!-- parameter yaml:cosmosKind --><!-- parameter json.dev:cosmosKind -->`cosmosKind` | `COSMOS_KIND` | O | Y: `"GlobalDocumentDB"`<br>J.dev: `"GlobalDocumentDB"` | Cosmos DB kind otherwise: "MongoDB". |
| <!-- parameter yaml:datalakeName_param --><!-- parameter json.dev:datalakeName_param -->`datalakeName_param` | `DATALAKE_NAME_PARAM` | O | Y: `""`<br>J.dev: `""` | BYO data lake storage account name otherwise: provide a custom storage account name. |
| <!-- parameter yaml:dev_admin_bicep_input_keyvault_subscription --><!-- parameter json.dev:dev_admin_bicep_input_keyvault_subscription -->`dev_admin_bicep_input_keyvault_subscription` | `AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID` | M | Y: `"<todo>_SubID"`<br>J.dev: `"<todo>_SubID"` | DEV seeding KV subscription ID mandatory: DEV seeding KV subscription ID ensure: subscription where the DEV seeding Key Vault resides. |
| <!-- parameter yaml:dev_admin_bicep_kv_fw --><!-- parameter json.dev:dev_admin_bicep_kv_fw -->`dev_admin_bicep_kv_fw` | `AIFACTORY_SEEDING_KEYVAULT_NAME` | M | Y: `"<todo>_Name_Dev"`<br>J.dev: `"<todo>_Name_Dev"` | DEV seeding KV name mandatory: DEV seeding KV name ensure: Key Vault name storing secrets mapped to PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID. |
| <!-- parameter yaml:dev_admin_bicep_kv_fw_rg --><!-- parameter json.dev:dev_admin_bicep_kv_fw_rg -->`dev_admin_bicep_kv_fw_rg` | `AIFACTORY_SEEDING_KEYVAULT_RG` | M | Y: `"<todo>_ResourceGroup_DEV"`<br>J.dev: `"<todo>_ResourceGroup_DEV"` | DEV seeding KV resource group mandatory: DEV seeding KV resource group ensure: resource group where the DEV seeding Key Vault resides. |
| <!-- parameter yaml:dev_sub_id --><!-- parameter json.dev:dev_sub_id -->`dev_sub_id` | `DEV_SUBSCRIPTION_ID` | M | Y: `"<todo>_SubID"`<br>J.dev: `"<todo>_SubID"` | DEV subscription ID mandatory: DEV subscription ID |
| <!-- parameter yaml:functionRuntime --><!-- parameter json.dev:functionRuntime -->`functionRuntime` | `FUNCTION_RUNTIME` | O | Y: `"dotnet"`<br>J.dev: `"dotnet"` | Azure Function runtime otherwise: "python", "node", "java", "powershell". |
| <!-- parameter yaml:functionVersion --><!-- parameter json.dev:functionVersion -->`functionVersion` | `FUNCTION_VERSION` | O | Y: `"v7.0"`<br>J.dev: `"v7.0"` | Azure Function runtime version |
| <!-- parameter yaml:kvNameFromCOMMON_param --><!-- parameter json.dev:kvNameFromCOMMON_param -->`kvNameFromCOMMON_param` | `KV_NAME_FROM_COMMON_PARAM` | O | Y: `""`<br>J.dev: `""` | BYO common Key Vault name otherwise: provide a custom Key Vault name. |
| <!-- parameter yaml:lakeContainerName --><!-- parameter json.dev:lakeContainerName -->`lakeContainerName` | `LAKE_CONTAINER_NAME` | O | Y: `"lake3"`<br>J.dev: `"lake3"` | Data lake container name |
| <!-- parameter yaml:org-department-id --><!-- parameter json.dev:org-department-id -->`org-department-id` | `ORG_DEPARTMENT_ID` | O | Y: `""`<br>J.dev: `""` | Project organizational department ID keep-as-is: Text, max 128 characters, not necessarily a GUID; identical across environments. No identity or authentication effect. |
| <!-- parameter yaml:org-department-name --><!-- parameter json.dev:org-department-name -->`org-department-name` | `ORG_DEPARTMENT_NAME` | O | Y: `""`<br>J.dev: `""` | Project organizational department name keep-as-is: Unicode text, max 200 characters; identical across environments, independent of cost center. No factory inheritance or Azure tag writes. |
| <!-- parameter yaml:postGresAdminEmails --><!-- parameter json.dev:postGresAdminEmails -->`postGresAdminEmails` | `POSTGRES_ADMIN_EMAILS` | C | Y: `"email_adress_only"`<br>J.dev: `"email_adress_only"` | PostgreSQL admin emails mandatory: if enablePostgreSQL:'true' ensure: valid comma-separated email addresses. |
| <!-- parameter yaml:prod_admin_bicep_input_keyvault_subscription --><!-- parameter json.dev:prod_admin_bicep_input_keyvault_subscription -->`prod_admin_bicep_input_keyvault_subscription` | `AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID` | C | Y: `"<todo>_SubID"`<br>J.dev: `"<todo>_SubID"` | PROD seeding KV subscription ID mandatory: PROD seeding KV subscription ID ensure: subscription where the PROD seeding Key Vault resides. Required when deploying that environment. |
| <!-- parameter yaml:prod_admin_bicep_kv_fw --><!-- parameter json.dev:prod_admin_bicep_kv_fw -->`prod_admin_bicep_kv_fw` | `AIFACTORY_SEEDING_KEYVAULT_NAME` | C | Y: `"<todo>_Name_Prod"`<br>J.dev: `"<todo>_Name_Prod"` | PROD seeding KV name mandatory: PROD seeding KV name ensure: Key Vault name storing secrets mapped to PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID. Required when deploying that environment. |
| <!-- parameter yaml:prod_admin_bicep_kv_fw_rg --><!-- parameter json.dev:prod_admin_bicep_kv_fw_rg -->`prod_admin_bicep_kv_fw_rg` | `AIFACTORY_SEEDING_KEYVAULT_RG` | C | Y: `"<todo>_ResourceGroup_Prod"`<br>J.dev: `"<todo>_ResourceGroup_Prod"` | PROD seeding KV resource group mandatory: PROD seeding KV resource group ensure: resource group where the PROD seeding Key Vault resides. Required when deploying that environment. |
| <!-- parameter yaml:prod_sub_id --><!-- parameter json.dev:prod_sub_id -->`prod_sub_id` | `PROD_SUBSCRIPTION_ID` | C | Y: `"<todo>_SubID"`<br>J.dev: `"<todo>_SubID"` | PROD subscription ID recommended: separate subscription from DEV. otherwise: can reuse dev_sub_id. Required when deploying that environment. |
| <!-- parameter yaml:projectPrefix --><!-- parameter json.dev:projectPrefix -->`projectPrefix` | `PROJECT_PREFIX` | O | Y: `"esml-"`<br>J.dev: `"esml-"` | Project resource group prefix |
| <!-- parameter yaml:projectSuffix --><!-- parameter json.dev:projectSuffix -->`projectSuffix` | `PROJECT_SUFFIX` | O | Y: `"-rg"`<br>J.dev: `"-rg"` | Project resource group suffix |
| <!-- parameter yaml:project_number_000 --><!-- parameter json.dev:project_number_000 -->`project_number_000` | `PROJECT_NUMBER` | M | Y: `"001"`<br>J.dev: `"001"` | Project number mandatory: Project number keep-as-is: For 1st project. otherwise: increment to '002', '003', etc. |
| <!-- parameter yaml:tag_costcenter --><!-- parameter json.dev:tag_costcenter -->`tag_costcenter` | `CostCenter` (not in .env template), `TAG_COSTCENTER` | O | Y: `"1234"`<br>J.dev: `"1234"` | Project cost center tag keep-as-is: Metadata for per-project cost tracking on resource group level. |
| <!-- parameter yaml:tag_costceter_common --><!-- parameter json.dev:tag_costceter_common -->`tag_costceter_common` | `TAG_COSTCETER_COMMON` | O | Y: `"9999"`<br>J.dev: `"9999"` | Common cost center tag keep-as-is: Metadata for Resource group cost tracking. |
| <!-- parameter yaml:tag_repository --><!-- parameter json.dev:tag_repository -->`tag_repository` | `TAG_REPOSITORY` | O | Y: `"aifactory"`<br>J.dev: `"aifactory"` | Repository name tag |
| <!-- parameter yaml:tag_repository_branch --><!-- parameter json.dev:tag_repository_branch -->`tag_repository_branch` | `TAG_REPOSITORY_BRANCH` | O | Y: `"aifactory-001"`<br>J.dev: `"aifactory-001"` | Repository branch tag otherwise: per scaleset 'aifactory-002', or per project 'aifactory-001/project001-main'. |
| <!-- parameter yaml:tags --><!-- parameter json.dev:tags -->`tags` | `TAGS` | O | Y: `"{\"CostCenter\":\"$(tag_costceter_common)\",\"Description\":\"AI Factory common\",\"AIF-Repo\":\"$(tag_repository)\",\"AIF-Branch\":\"$(tag_repository_branch)\",\"AIF-Version\":\"$(aifactory_version_major).$(aifactory_version_minor)\",\"AIF-Submodule-Chosen-Branch\":\"$(aifactory_branch_chosen)\",\"AIF-Scaleset\":\"$(admin_aifactorySuffixRG)\",\"AIF-Environment\":\"$(dev_test_prod)\",\"AIF-Project Owners\":\"$(technical_admins_email)\",\"AIFactory project\":\"$(project_number_000)\",\"AIF-Networking\":\"$(allowPublicAccessWhenBehindVnet),$(enablePublicGenAIAccess),$(enablePublicAccessWithPerimeter)\",\"AIF-enableAIFactoryCreatedDefaultProjectForAIFv2\":\"$(enableAIFactoryCreatedDefaultProjectForAIFv2)\",\"AIF-disableAgentNetworkInjection\":\"$(disableAgentNetworkInjection)\",\"AIF-byoASEv3\":\"$(byoASEv3)\",\"AIF-BYO_subnets\":\"$(BYO_subnets)\"}"`<br>J.dev: `"{\"CostCenter\":\"$(tag_costceter_common)\",\"Description\":\"AI Factory common\",\"AIF-Repo\":\"$(tag_repository)\",\"AIF-Branch\":\"$(tag_repository_branch)\",\"AIF-Version\":\"$(aifactory_version_major).$(aifactory_version_minor)\",\"AIF-Submodule-Chosen-Branch\":\"$(aifactory_branch_chosen)\",\"AIF-Scaleset\":\"$(admin_aifactorySuffixRG)\",\"AIF-Environment\":\"$(dev_test_prod)\",\"AIF-Project Owners\":\"$(technical_admins_email)\",\"AIFactory project\":\"$(project_number_000)\",\"AIF-Networking\":\"$(allowPublicAccessWhenBehindVnet),$(enablePublicGenAIAccess),$(enablePublicAccessWithPerimeter)\",\"AIF-enableAIFactoryCreatedDefaultProjectForAIFv2\":\"$(enableAIFactoryCreatedDefaultProjectForAIFv2)\",\"AIF-disableAgentNetworkInjection\":\"$(disableAgentNetworkInjection)\",\"AIF-byoASEv3\":\"$(byoASEv3)\",\"AIF-BYO_subnets\":\"$(BYO_subnets)\"}"` | Common resource tags as a JSON string; Azure DevOps macro expressions are preserved. |
| <!-- parameter yaml:tagsProject --><!-- parameter json.dev:tagsProject -->`tagsProject` | `TAGS_PROJECT` | O | Y: `"{\"CostCenter\":\"$(tag_costcenter)\",\"Description\":\"RAG Chat 1\",\"AIF-Branch\":\"$(tag_repository_branch)/project$(project_number_000)\",\"AIF-Scaleset\":\"$(admin_aifactorySuffixRG)\",\"AIF-Environment\":\"$(dev_test_prod)\",\"AIF-Project Owners\":\"$(technical_admins_email)\",\"AIFactory project\":\"$(project_number_000)\",\"AIF-Networking\":\"$(allowPublicAccessWhenBehindVnet),$(enablePublicGenAIAccess),$(enablePublicAccessWithPerimeter)\",\"AIF-enableAIFactoryCreatedDefaultProjectForAIFv2\":\"$(enableAIFactoryCreatedDefaultProjectForAIFv2)\",\"AIF-disableAgentNetworkInjection\":\"$(disableAgentNetworkInjection)\",\"AIF-byoASEv3\":\"$(byoASEv3)\",\"AIF-BYO_subnets\":\"$(BYO_subnets)\"}"`<br>J.dev: `"{\"CostCenter\":\"$(tag_costcenter)\",\"Description\":\"RAG Chat 1\",\"AIF-Branch\":\"$(tag_repository_branch)/project$(project_number_000)\",\"AIF-Scaleset\":\"$(admin_aifactorySuffixRG)\",\"AIF-Environment\":\"$(dev_test_prod)\",\"AIF-Project Owners\":\"$(technical_admins_email)\",\"AIFactory project\":\"$(project_number_000)\",\"AIF-Networking\":\"$(allowPublicAccessWhenBehindVnet),$(enablePublicGenAIAccess),$(enablePublicAccessWithPerimeter)\",\"AIF-enableAIFactoryCreatedDefaultProjectForAIFv2\":\"$(enableAIFactoryCreatedDefaultProjectForAIFv2)\",\"AIF-disableAgentNetworkInjection\":\"$(disableAgentNetworkInjection)\",\"AIF-byoASEv3\":\"$(byoASEv3)\",\"AIF-BYO_subnets\":\"$(BYO_subnets)\"}"` | Project resource tags as a JSON string; Azure DevOps macro expressions are preserved. |
| <!-- parameter yaml:test_admin_bicep_input_keyvault_subscription --><!-- parameter json.dev:test_admin_bicep_input_keyvault_subscription -->`test_admin_bicep_input_keyvault_subscription` | `AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID` | C | Y: `"<todo>_SubID"`<br>J.dev: `"<todo>_SubID"` | STAGE seeding KV subscription ID mandatory: STAGE seeding KV subscription ID ensure: subscription where the STAGE seeding Key Vault resides. Required when deploying that environment. |
| <!-- parameter yaml:test_admin_bicep_kv_fw --><!-- parameter json.dev:test_admin_bicep_kv_fw -->`test_admin_bicep_kv_fw` | `AIFACTORY_SEEDING_KEYVAULT_NAME` | C | Y: `"<todo>_Name_Test"`<br>J.dev: `"<todo>_Name_Test"` | STAGE seeding KV name mandatory: STAGE seeding KV name ensure: Key Vault name storing secrets mapped to PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID. Required when deploying that environment. |
| <!-- parameter yaml:test_admin_bicep_kv_fw_rg --><!-- parameter json.dev:test_admin_bicep_kv_fw_rg -->`test_admin_bicep_kv_fw_rg` | `AIFACTORY_SEEDING_KEYVAULT_RG` | C | Y: `"<todo>_ResourceGroup_Test"`<br>J.dev: `"<todo>_ResourceGroup_Test"` | STAGE seeding KV resource group mandatory: STAGE seeding KV resource group ensure: resource group where the STAGE seeding Key Vault resides. Required when deploying that environment. |
| <!-- parameter yaml:test_sub_id --><!-- parameter json.dev:test_sub_id -->`test_sub_id` | `STAGE_SUBSCRIPTION_ID` | C | Y: `"<todo>_SubID"`<br>J.dev: `"<todo>_SubID"` | STAGE subscription ID recommended: separate subscription from DEV. otherwise: can reuse dev_sub_id. Required when deploying that environment. |
| <!-- parameter yaml:useCommonACR --><!-- parameter json.dev:useCommonACR -->`useCommonACR` | `USE_COMMON_ACR_FOR_PROJECTS` | O | Y: `"true"`<br>J.dev: `"true"` | Use shared ACR across projects otherwise: false, each project gets its own ACR (higher cost). |
| <!-- parameter yaml:useCommonACR_override --><!-- parameter json.dev:useCommonACR_override -->`useCommonACR_override` | `USE_COMMON_ACR_FOR_PROJECTS`, `USE_COMMON_ACR_OVERRIDE` | O | Y: `"true"`<br>J.dev: `"true"` | Use shared ACR override otherwise: false, each project gets its own ACR (higher cost). |
| <!-- parameter yaml:webAppRuntime --><!-- parameter json.dev:webAppRuntime -->`webAppRuntime` | `WEBAPP_RUNTIME` | O | Y: `"python"`<br>J.dev: `"python"` | Azure Web App runtime otherwise: "dotnet", "node", "java". |
| <!-- parameter yaml:webAppRuntimeVersion --><!-- parameter json.dev:webAppRuntimeVersion -->`webAppRuntimeVersion` | `WEBAPP_RUNTIME_VERSION` | O | Y: `"3.11"`<br>J.dev: `"3.11"` | Azure Web App runtime version |

### Operations, diagnostics and lifecycle

| YAML / JSON key | GHA binding(s) | M/C/O | Source defaults | Description / conditions |
|---|---|---|---|---|
| <!-- parameter yaml:adminVMBuildAgentName --><!-- parameter json.dev:adminVMBuildAgentName -->`adminVMBuildAgentName` | No verified binding | O | Y: `""`<br>J.dev: `""` | Azure DevOps agent name override keep-as-is: Leave empty for the Bicep-generated admin VM name; set to an existing VM agent name such as vm-test when reusing one. |
| <!-- parameter yaml:adminVMBuildAgentPool --><!-- parameter json.dev:adminVMBuildAgentPool -->`adminVMBuildAgentPool` | No verified binding | O | Y: `"Default"`<br>J.dev: `"Default"` | Azure DevOps pool hosting the admin VM agent keep-as-is: Change only when the agent is registered in a custom pool. |
| <!-- parameter yaml:debugEnableCleaning --><!-- parameter json.dev:debugEnableCleaning -->`debugEnableCleaning` | `DEBUG_ENABLE_CLEANING` | O | Y: `"false"`<br>J.dev: `"false"` | Enable error cleanup tasks otherwise: true, enables cleanup tasks (71-73) that delete resources on deployment failures. Use only when debugging. |
| <!-- parameter yaml:debug_disable_05_build_acr_image --><!-- parameter json.dev:debug_disable_05_build_acr_image -->`debug_disable_05_build_acr_image` | `DEBUG_DISABLE_05_BUILD_ACR_IMAGE` | O | Y: `"false"`<br>J.dev: `"false"` | Skip ACR image build step otherwise: true, skip. Cannot be disabled if enableContainerApps:'true'. |
| <!-- parameter yaml:debug_disable_10_aifactory_dashboards --><!-- parameter json.dev:debug_disable_10_aifactory_dashboards -->`debug_disable_10_aifactory_dashboards` | `DEBUG_DISABLE_10_AIFACTORY_DASHBOARDS` | O | Y: `"true"`<br>J.dev: `"true"` | Skip AI Factory dashboards step |
| <!-- parameter yaml:debug_disable_61_foundation --><!-- parameter json.dev:debug_disable_61_foundation -->`debug_disable_61_foundation` | `DEBUG_DISABLE_61_FOUNDATION` | O | Y: `"false"`<br>J.dev: `"false"` | Skip foundation step otherwise: true, skip: Resource groups, User-Assigned Managed Identities, VMs. |
| <!-- parameter yaml:debug_disable_62_core_infrastructure --><!-- parameter json.dev:debug_disable_62_core_infrastructure -->`debug_disable_62_core_infrastructure` | `DEBUG_DISABLE_62_CORE_INFRASTRUCTURE` | O | Y: `"false"`<br>J.dev: `"false"` | Skip core infrastructure step otherwise: true, skip: Application Insights, Key Vault, Storage, ACR. |
| <!-- parameter yaml:debug_disable_63_cognitive_services --><!-- parameter json.dev:debug_disable_63_cognitive_services -->`debug_disable_63_cognitive_services` | `DEBUG_DISABLE_63_COGNITIVE_SERVICES` | O | Y: `"false"`<br>J.dev: `"false"` | Skip cognitive services step otherwise: true, skip: AI Search, OpenAI, Vision, Speech, etc. |
| <!-- parameter yaml:debug_disable_64_databases --><!-- parameter json.dev:debug_disable_64_databases -->`debug_disable_64_databases` | `DEBUG_DISABLE_64_DATABASES` | O | Y: `"false"`<br>J.dev: `"false"` | Skip databases step otherwise: true, skip: Cosmos DB, SQL Database, etc. |
| <!-- parameter yaml:debug_disable_65_compute_services --><!-- parameter json.dev:debug_disable_65_compute_services -->`debug_disable_65_compute_services` | `DEBUG_DISABLE_65_COMPUTE_SERVICES` | O | Y: `"false"`<br>J.dev: `"false"` | Skip compute services step otherwise: true, skip: Container Apps, Web App, Function App. |
| <!-- parameter yaml:debug_disable_66_ai_platform --><!-- parameter json.dev:debug_disable_66_ai_platform -->`debug_disable_66_ai_platform` | `DEBUG_DISABLE_66_AI_PLATFORM` | O | Y: `"false"`<br>J.dev: `"false"` | Skip AI platform step otherwise: true, skip: AI Foundry Hub (V1) with default project and connections. |
| <!-- parameter yaml:debug_disable_67_data_ml_platform --><!-- parameter json.dev:debug_disable_67_data_ml_platform -->`debug_disable_67_data_ml_platform` | `DEBUG_DISABLE_67_ML_PLATFORM` | O | Y: `"false"`<br>J.dev: `"false"` | Skip ML platform step otherwise: true, skip: Azure Machine Learning, Data Factory, Databricks. |
| <!-- parameter yaml:debug_disable_68_integration --><!-- parameter json.dev:debug_disable_68_integration -->`debug_disable_68_integration` | `DEBUG_DISABLE_68_INTEGRATION` | O | Y: `"false"`<br>J.dev: `"false"` | Skip integration step otherwise: true, skip: Logic Apps, Event Hubs. |
| <!-- parameter yaml:debug_disable_69_aifoundry_2025 --><!-- parameter json.dev:debug_disable_69_aifoundry_2025 -->`debug_disable_69_aifoundry_2025` | `DEBUG_DISABLE_69_AIFOUNDRY_2025` | O | Y: `"false"`<br>J.dev: `"false"` | Skip AI Foundry V2 step otherwise: true, skip: AI Foundry V2 including RBAC and default project. |
| <!-- parameter yaml:debug_disable_validation_tasks --><!-- parameter json.dev:debug_disable_validation_tasks -->`debug_disable_validation_tasks` | `DEBUG_DISABLE_VALIDATION_TASKS` | O | Y: `"false"`<br>J.dev: `"false"` | Disable validation tasks otherwise: true, skip subnet validation, submodule check, DNS zones check to speed up re-runs. |
| <!-- parameter yaml:deleteAllForProject --><!-- parameter json.dev:deleteAllForProject -->`deleteAllForProject` | `DELETE_ALL_FOR_PROJECT` | O | Y: `"false"`<br>J.dev: `"false"` | ULTRA DELETE MODE - Delete ALL resources in project RG and networking resources (subnets, NSGs) in common RG. Use with extreme caution! |
| <!-- parameter yaml:deleteAllServicesForProject --><!-- parameter json.dev:deleteAllServicesForProject -->`deleteAllServicesForProject` | `DELETE_ALL_SERVICES_FOR_PROJECT` | O | Y: `"false"`<br>J.dev: `"false"` | Delete all project services otherwise: true, deletes all services in project RG in step 04 then quits pipeline (Key Vault retained by default; set deleteKeyvaultAlso:'true' to also delete it). |
| <!-- parameter yaml:deleteKeyvaultAlso --><!-- parameter json.dev:deleteKeyvaultAlso -->`deleteKeyvaultAlso` | `DELETE_KEYVAULT_ALSO` | O | Y: `"false"`<br>J.dev: `"false"` | Also delete Key Vault when deleteAllServicesForProject:'true' recommended: false, retains Key Vault as a safety net (secrets, CMK keys, RBAC). otherwise: true, also deletes the project Key Vault. |
| <!-- parameter yaml:diagnosticSettingLevel --><!-- parameter json.dev:diagnosticSettingLevel -->`diagnosticSettingLevel` | `DIAGNOSTIC_SETTING_LEVEL` | O | Y: `"gold"`<br>J.dev: `"gold"` | Diagnostics level otherwise: silver or bronze for less verbose (lower cost) logging. |
| <!-- parameter yaml:maxRetryAttempts --><!-- parameter json.dev:maxRetryAttempts -->`maxRetryAttempts` | `MAX_RETRY_ATTEMPTS` | O | Y: `"2"`<br>J.dev: `"2"` | Max total retry attempts keep-as-is: Total attempts (1 original + N retries). Valid values: 1, 2, or 3. |
| <!-- parameter yaml:policyExemptionAssignmentIds --><!-- parameter json.dev:policyExemptionAssignmentIds -->`policyExemptionAssignmentIds` | `POLICY_EXEMPTION_ASSIGNMENT_IDS` | O | Y: `"[]"`<br>J.dev: `"[]"` | JSON array of policy assignment IDs (deployIfNotExists or auditIfNotExists) to exempt on the VNet RG otherwise: e.g. '["/subscriptions/ |
| <!-- parameter yaml:policyExemptionDefinitionReferenceIds --><!-- parameter json.dev:policyExemptionDefinitionReferenceIds -->`policyExemptionDefinitionReferenceIds` | `POLICY_EXEMPTION_DEFINITION_REFERENCE_IDS` | O | Y: `"[]"`<br>J.dev: `"[]"` | JSON array of policyDefinitionReferenceIds within an initiative to narrow the exemption keep-as-is: Leave empty to exempt the full assignment. |
| <!-- parameter yaml:retryMinutes --><!-- parameter json.dev:retryMinutes -->`retryMinutes` | `RETRY_MINUTES` | O | Y: `"5"`<br>J.dev: `"5"` | Retry wait (minutes) 1st attempt keep-as-is: Minutes between 1st and 2nd retry. |
| <!-- parameter yaml:retryMinutesExtended --><!-- parameter json.dev:retryMinutesExtended -->`retryMinutesExtended` | `RETRY_MINUTES_EXTENDED` | O | Y: `"15"`<br>J.dev: `"15"` | Retry wait (minutes) 2nd attempt keep-as-is: Minutes between 2nd and 3rd retry. |
| <!-- parameter yaml:selfHostedRunnerLabel --><!-- parameter json.dev:selfHostedRunnerLabel -->`selfHostedRunnerLabel` | `SELF_HOSTED_RUNNER_LABEL` | O | Y: `"aifactory-admin-vm"`<br>J.dev: `"aifactory-admin-vm"` | GitHub self-hosted runner label |
| <!-- parameter yaml:useSelfHostedBuildAgent --><!-- parameter json.dev:useSelfHostedBuildAgent -->`useSelfHostedBuildAgent` | `USE_SELF_HOSTED_BUILD_AGENT` | O | Y: `"false"`<br>J.dev: `"false"` | Use a self-hosted build agent/runner keep-as-is: ADO uses adminVMBuildAgentPool/adminVMBuildAgentName; GHA uses selfHostedRunnerLabel. |

### Per-environment SKUs and compute sizing

| YAML / JSON key | GHA binding(s) | M/C/O | Source defaults | Description / conditions |
|---|---|---|---|---|
| <!-- parameter yaml:adminVMSize -->`adminVMSize` | `ADMIN_VM_SIZE` | O | Y: `"Standard_D2s_v5"`<br>J.dev: absent | Admin VM size keep-as-is: Override when the regional SKU is unavailable. |
| <!-- parameter yaml:admin_aks_gpu_sku_dev_override --><!-- parameter json.dev:admin_aks_gpu_sku_dev_override -->`admin_aks_gpu_sku_dev_override` | `ADMIN_AKS_GPU_SKU_DEV_OVERRIDE` | O | Y: `"Standard_D4s_v5"`<br>J.dev: `"Standard_D4s_v5"` | AKS system node VM SKU for DEV ensure: use an AKS-supported system-pool SKU; configure GPU workloads in a separate user pool. |
| <!-- parameter yaml:admin_aks_gpu_sku_test_prod_override --><!-- parameter json.dev:admin_aks_gpu_sku_test_prod_override -->`admin_aks_gpu_sku_test_prod_override` | `ADMIN_AKS_GPU_SKU_TEST_PROD_OVERRIDE` | O | Y: `"Standard_DS13-2_v2"`<br>J.dev: `"Standard_DS13-2_v2"` | AKS node VM SKU for TEST/PROD |
| <!-- parameter yaml:admin_aks_nodes_dev_override --><!-- parameter json.dev:admin_aks_nodes_dev_override -->`admin_aks_nodes_dev_override` | `ADMIN_AKS_NODES_DEV_OVERRIDE` | O | Y: `2`<br>J.dev: `2` | AKS system node count for DEV |
| <!-- parameter yaml:admin_aks_nodes_testProd_override --><!-- parameter json.dev:admin_aks_nodes_testProd_override -->`admin_aks_nodes_testProd_override` | `ADMIN_AKS_NODES_TEST_PROD_OVERRIDE` | O | Y: `3`<br>J.dev: `3` | AKS node count for TEST/PROD |
| <!-- parameter yaml:admin_aks_version_override --><!-- parameter json.dev:admin_aks_version_override -->`admin_aks_version_override` | `ADMIN_AKS_VERSION_OVERRIDE` | O | Y: `"1.35.7"`<br>J.dev: `"1.35.7"` | AKS Kubernetes version ensure: version has standard support in your region. |
| <!-- parameter yaml:admin_aml_cluster_maxNodes_dev_override --><!-- parameter json.dev:admin_aml_cluster_maxNodes_dev_override -->`admin_aml_cluster_maxNodes_dev_override` | `ADMIN_AML_CLUSTER_MAX_NODES_DEV_OVERRIDE` | O | Y: `3`<br>J.dev: `3` | AML cluster max nodes for DEV |
| <!-- parameter yaml:admin_aml_cluster_maxNodes_testProd_override --><!-- parameter json.dev:admin_aml_cluster_maxNodes_testProd_override -->`admin_aml_cluster_maxNodes_testProd_override` | `ADMIN_AML_CLUSTER_MAX_NODES_TEST_PROD_OVERRIDE` | O | Y: `5`<br>J.dev: `5` | AML cluster max nodes for TEST/PROD |
| <!-- parameter yaml:admin_aml_cluster_sku_dev_override --><!-- parameter json.dev:admin_aml_cluster_sku_dev_override -->`admin_aml_cluster_sku_dev_override` | `ADMIN_AML_CLUSTER_SKU_DEV_OVERRIDE` | O | Y: `"Standard_DS3_v2"`<br>J.dev: `"Standard_DS3_v2"` | AML cluster VM SKU for DEV |
| <!-- parameter yaml:admin_aml_cluster_sku_testProd_override --><!-- parameter json.dev:admin_aml_cluster_sku_testProd_override -->`admin_aml_cluster_sku_testProd_override` | `ADMIN_AML_CLUSTER_SKU_TEST_PROD_OVERRIDE` | O | Y: `"Standard_D13_v2"`<br>J.dev: `"Standard_D13_v2"` | AML cluster VM SKU for TEST/PROD |
| <!-- parameter yaml:admin_aml_computeInstance_dev_sku_override --><!-- parameter json.dev:admin_aml_computeInstance_dev_sku_override -->`admin_aml_computeInstance_dev_sku_override` | `ADMIN_AML_COMPUTE_INSTANCE_DEV_SKU_OVERRIDE` | O | Y: `"Standard_DS11_v2"`<br>J.dev: `"Standard_DS11_v2"` | AML compute instance SKU for DEV |
| <!-- parameter yaml:admin_aml_computeInstance_testProd_sku_override --><!-- parameter json.dev:admin_aml_computeInstance_testProd_sku_override -->`admin_aml_computeInstance_testProd_sku_override` | `ADMIN_AML_COMPUTE_INSTANCE_TEST_PROD_SKU_OVERRIDE` | O | Y: `"Standard_ND96amsr_A100_v4"`<br>J.dev: `"Standard_ND96amsr_A100_v4"` | AML compute instance SKU for TEST/PROD otherwise: change to a lower-cost SKU to save cost. |
| <!-- parameter yaml:aksAzureFirewallPrivateIp --><!-- parameter json.dev:aksAzureFirewallPrivateIp -->`aksAzureFirewallPrivateIp` | `AKS_AZURE_FIREWALL_PRIVATE_IP` | C | Y: `""`<br>J.dev: `""` | AKS Azure Firewall private IP mandatory: if aksOutboundType:'userDefinedRouting' ensure: IP within the Azure Firewall subnet range. |
| <!-- parameter yaml:aksEnablePrivateCluster --><!-- parameter json.dev:aksEnablePrivateCluster -->`aksEnablePrivateCluster` | `AKS_ENABLE_PRIVATE_CLUSTER` | O | Y: `"true"`<br>J.dev: `"true"` | Enable private AKS cluster otherwise: false for public access. |
| <!-- parameter yaml:aksOutboundType --><!-- parameter json.dev:aksOutboundType -->`aksOutboundType` | `AKS_OUTBOUND_TYPE` | O | Y: `"loadBalancer"`<br>J.dev: `"loadBalancer"` | AKS outbound traffic type otherwise: userDefinedRouting, if you have Azure Firewall and UDR configured. |
| <!-- parameter yaml:aksPrivateDNSZone --><!-- parameter json.dev:aksPrivateDNSZone -->`aksPrivateDNSZone` | `AKS_PRIVATE_DNS_ZONE` | O | Y: `"system"`<br>J.dev: `"system"` | AKS private DNS zone otherwise: "none" or full resource ID of a private DNS zone. |
| <!-- parameter yaml:aksSkuName --><!-- parameter json.dev:aksSkuName -->`aksSkuName` | `AKS_SKU_NAME` | O | Y: `"Base"`<br>J.dev: `"Base"` | AKS SKU name otherwise: "Standard" for production workloads. |
| <!-- parameter yaml:skuAISearchDev --><!-- parameter json.dev:skuAISearchDev -->`skuAISearchDev` | `ADMIN_AISEARCH_TIER`, `SKU_AISEARCH_DEV` (not in .env template) | O | Y: `"basic"`<br>J.dev: `"basic"` | AI Search SKU Dev ['free','basic','standard','standard2','standard3','storage_optimized_l1','storage_optimized_l2'] ('free' not allowed with private endpoints) |
| <!-- parameter yaml:skuAISearchStageProd --><!-- parameter json.dev:skuAISearchStageProd -->`skuAISearchStageProd` | `ADMIN_AISEARCH_TIER`, `SKU_AISEARCH_STAGEPROD` (not in .env template) | O | Y: `"standard"`<br>J.dev: `"standard"` | AI Search SKU Stage/Prod |
| <!-- parameter yaml:skuAIServicesDev --><!-- parameter json.dev:skuAIServicesDev -->`skuAIServicesDev` | `SKU_AISERVICES_DEV` | O | Y: `"S0"`<br>J.dev: `"S0"` | Azure AI Services (multi-service account) SKU Dev |
| <!-- parameter yaml:skuAIServicesStageProd --><!-- parameter json.dev:skuAIServicesStageProd -->`skuAIServicesStageProd` | `SKU_AISERVICES_STAGEPROD` | O | Y: `"S0"`<br>J.dev: `"S0"` | Azure AI Services (multi-service account) SKU Stage/Prod |
| <!-- parameter yaml:skuAksDev --><!-- parameter json.dev:skuAksDev -->`skuAksDev` | `SKU_AKS_DEV` | O | Y: `"Standard_D4s_v5"`<br>J.dev: `"Standard_D4s_v5"` | AKS dev node VM size keep-as-is: empty=template default Standard_B4ms. |
| <!-- parameter yaml:skuAksStageProd --><!-- parameter json.dev:skuAksStageProd -->`skuAksStageProd` | `SKU_AKS_STAGEPROD` | O | Y: `""`<br>J.dev: `""` | AKS test/prod node VM size keep-as-is: empty=template default Standard_DS13-2_v2. |
| <!-- parameter yaml:skuAzureMLDev --><!-- parameter json.dev:skuAzureMLDev -->`skuAzureMLDev` | `SKU_AZUREML_DEV` | O | Y: `"basic"`<br>J.dev: `"basic"` | Azure ML workspace SKU Dev ['basic','standard'] |
| <!-- parameter yaml:skuAzureMLStageProd --><!-- parameter json.dev:skuAzureMLStageProd -->`skuAzureMLStageProd` | `SKU_AZUREML_STAGEPROD` | O | Y: `"basic"`<br>J.dev: `"basic"` | Azure ML workspace SKU Stage/Prod |
| <!-- parameter yaml:skuBingDev --><!-- parameter json.dev:skuBingDev -->`skuBingDev` | `SKU_BING_DEV` | O | Y: `"G2"`<br>J.dev: `"G2"` | Bing Custom Search SKU Dev ['G2'] |
| <!-- parameter yaml:skuBingStageProd --><!-- parameter json.dev:skuBingStageProd -->`skuBingStageProd` | `SKU_BING_STAGEPROD` | O | Y: `"G2"`<br>J.dev: `"G2"` | Bing Custom Search SKU Stage/Prod |
| <!-- parameter yaml:skuBotServiceDev --><!-- parameter json.dev:skuBotServiceDev -->`skuBotServiceDev` | `SKU_BOTSERVICE_DEV` | O | Y: `"S1"`<br>J.dev: `"S1"` | Bot Service SKU Dev ['F0','S1'] |
| <!-- parameter yaml:skuBotServiceStageProd --><!-- parameter json.dev:skuBotServiceStageProd -->`skuBotServiceStageProd` | `SKU_BOTSERVICE_STAGEPROD` | O | Y: `"S1"`<br>J.dev: `"S1"` | Bot Service SKU Stage/Prod |
| <!-- parameter yaml:skuContentSafetyDev --><!-- parameter json.dev:skuContentSafetyDev -->`skuContentSafetyDev` | `SKU_CONTENTSAFETY_DEV` | O | Y: `"S0"`<br>J.dev: `"S0"` | Content Safety SKU Dev |
| <!-- parameter yaml:skuContentSafetyStageProd --><!-- parameter json.dev:skuContentSafetyStageProd -->`skuContentSafetyStageProd` | `SKU_CONTENTSAFETY_STAGEPROD` | O | Y: `"S0"`<br>J.dev: `"S0"` | Content Safety SKU Stage/Prod |
| <!-- parameter yaml:skuDatabricksDev --><!-- parameter json.dev:skuDatabricksDev -->`skuDatabricksDev` | `SKU_DATABRICKS_DEV` | O | Y: `"premium"`<br>J.dev: `"premium"` | Databricks SKU Dev ['trial','premium'] |
| <!-- parameter yaml:skuDatabricksStageProd --><!-- parameter json.dev:skuDatabricksStageProd -->`skuDatabricksStageProd` | `SKU_DATABRICKS_STAGEPROD` | O | Y: `"premium"`<br>J.dev: `"premium"` | Databricks SKU Stage/Prod |
| <!-- parameter yaml:skuDocIntelligenceDev --><!-- parameter json.dev:skuDocIntelligenceDev -->`skuDocIntelligenceDev` | `SKU_DOCINTELLIGENCE_DEV` | O | Y: `"S0"`<br>J.dev: `"S0"` | Document Intelligence SKU Dev |
| <!-- parameter yaml:skuDocIntelligenceStageProd --><!-- parameter json.dev:skuDocIntelligenceStageProd -->`skuDocIntelligenceStageProd` | `SKU_DOCINTELLIGENCE_STAGEPROD` | O | Y: `"S0"`<br>J.dev: `"S0"` | Document Intelligence SKU Stage/Prod |
| <!-- parameter yaml:skuElasticDev --><!-- parameter json.dev:skuElasticDev -->`skuElasticDev` | `ELASTIC_SKU`, `SKU_ELASTIC_DEV` | O | Y: `"ess-consumption-2024_Monthly"`<br>J.dev: `"ess-consumption-2024_Monthly"` | Elastic Cloud SKU Dev |
| <!-- parameter yaml:skuElasticStageProd --><!-- parameter json.dev:skuElasticStageProd -->`skuElasticStageProd` | `ELASTIC_SKU`, `SKU_ELASTIC_STAGEPROD` | O | Y: `"ess-consumption-2024_Monthly"`<br>J.dev: `"ess-consumption-2024_Monthly"` | Elastic Cloud SKU Stage/Prod |
| <!-- parameter yaml:skuEventHubsDev --><!-- parameter json.dev:skuEventHubsDev -->`skuEventHubsDev` | `SKU_EVENTHUBS_DEV` | O | Y: `"Basic"`<br>J.dev: `"Basic"` | Event Hubs tier Dev ['Basic','Standard','Premium'] |
| <!-- parameter yaml:skuEventHubsStageProd --><!-- parameter json.dev:skuEventHubsStageProd -->`skuEventHubsStageProd` | `SKU_EVENTHUBS_STAGEPROD` | O | Y: `"Basic"`<br>J.dev: `"Basic"` | Event Hubs tier Stage/Prod |
| <!-- parameter yaml:skuFunctionDev --><!-- parameter json.dev:skuFunctionDev -->`skuFunctionDev` | `SKU_FUNCTION_DEV` | O | Y: `"EP1"`<br>J.dev: `"EP1"` | Function plan SKU Dev |
| <!-- parameter yaml:skuFunctionStageProd --><!-- parameter json.dev:skuFunctionStageProd -->`skuFunctionStageProd` | `SKU_FUNCTION_STAGEPROD` | O | Y: `"EP1"`<br>J.dev: `"EP1"` | Function plan SKU Stage/Prod |
| <!-- parameter yaml:skuLogicAppsDev --><!-- parameter json.dev:skuLogicAppsDev -->`skuLogicAppsDev` | `SKU_LOGICAPPS_DEV` | O | Y: `"WS1"`<br>J.dev: `"WS1"` | Logic Apps plan SKU Dev ['WS1','WS2','WS3','EP1','EP2','EP3','P1V2','P2V2','P3V2','P1V3','P2V3','P3V3'] |
| <!-- parameter yaml:skuLogicAppsStageProd --><!-- parameter json.dev:skuLogicAppsStageProd -->`skuLogicAppsStageProd` | `SKU_LOGICAPPS_STAGEPROD` | O | Y: `"WS1"`<br>J.dev: `"WS1"` | Logic Apps plan SKU Stage/Prod |
| <!-- parameter yaml:skuOpenAIDev --><!-- parameter json.dev:skuOpenAIDev -->`skuOpenAIDev` | `SKU_OPENAI_DEV` | O | Y: `"S0"`<br>J.dev: `"S0"` | Azure OpenAI SKU Dev |
| <!-- parameter yaml:skuOpenAIStageProd --><!-- parameter json.dev:skuOpenAIStageProd -->`skuOpenAIStageProd` | `SKU_OPENAI_STAGEPROD` | O | Y: `"S0"`<br>J.dev: `"S0"` | Azure OpenAI SKU Stage/Prod |
| <!-- parameter yaml:skuPostgreSQLDev --><!-- parameter json.dev:skuPostgreSQLDev -->`skuPostgreSQLDev` | `SKU_POSTGRESQL_DEV` | O | Y: `"Standard_B1ms"`<br>J.dev: `"Standard_B1ms"` | PostgreSQL compute SKU Dev |
| <!-- parameter yaml:skuPostgreSQLStageProd --><!-- parameter json.dev:skuPostgreSQLStageProd -->`skuPostgreSQLStageProd` | `SKU_POSTGRESQL_STAGEPROD` | O | Y: `"Standard_B1ms"`<br>J.dev: `"Standard_B1ms"` | PostgreSQL compute SKU Stage/Prod |
| <!-- parameter yaml:skuRedisDev --><!-- parameter json.dev:skuRedisDev -->`skuRedisDev` | `SKU_REDIS_DEV` | O | Y: `"Standard"`<br>J.dev: `"Standard"` | Redis SKU Dev ['Basic','Standard','Premium'] |
| <!-- parameter yaml:skuRedisStageProd --><!-- parameter json.dev:skuRedisStageProd -->`skuRedisStageProd` | `SKU_REDIS_STAGEPROD` | O | Y: `"Standard"`<br>J.dev: `"Standard"` | Redis SKU Stage/Prod |
| <!-- parameter yaml:skuSQLDatabaseDev --><!-- parameter json.dev:skuSQLDatabaseDev -->`skuSQLDatabaseDev` | `SKU_SQLDATABASE_DEV` | O | Y: `"S0"`<br>J.dev: `"S0"` | Azure SQL DB (DTU model) SKU Dev |
| <!-- parameter yaml:skuSQLDatabaseStageProd --><!-- parameter json.dev:skuSQLDatabaseStageProd -->`skuSQLDatabaseStageProd` | `SKU_SQLDATABASE_STAGEPROD` | O | Y: `"S0"`<br>J.dev: `"S0"` | Azure SQL DB (DTU model) SKU Stage/Prod |
| <!-- parameter yaml:skuSpeechDev --><!-- parameter json.dev:skuSpeechDev -->`skuSpeechDev` | `SKU_SPEECH_DEV` | O | Y: `"S0"`<br>J.dev: `"S0"` | Azure AI Speech SKU Dev |
| <!-- parameter yaml:skuSpeechStageProd --><!-- parameter json.dev:skuSpeechStageProd -->`skuSpeechStageProd` | `SKU_SPEECH_STAGEPROD` | O | Y: `"S0"`<br>J.dev: `"S0"` | Azure AI Speech SKU Stage/Prod |
| <!-- parameter yaml:skuStorageAccountDev --><!-- parameter json.dev:skuStorageAccountDev -->`skuStorageAccountDev` | `SKU_STORAGEACCOUNT_DEV` | O | Y: `"Standard_LRS"`<br>J.dev: `"Standard_LRS"` | Project Storage Account SKU Dev ['Standard_LRS','Standard_GRS','Standard_RAGRS','Standard_ZRS','Premium_LRS','Premium_ZRS','Standard_GZRS','Standard_RAGZRS'] |
| <!-- parameter yaml:skuStorageAccountStageProd --><!-- parameter json.dev:skuStorageAccountStageProd -->`skuStorageAccountStageProd` | `SKU_STORAGEACCOUNT_STAGEPROD` | O | Y: `"Standard_LRS"`<br>J.dev: `"Standard_LRS"` | Project Storage Account SKU Stage/Prod |
| <!-- parameter yaml:skuTierAksDev --><!-- parameter json.dev:skuTierAksDev -->`skuTierAksDev` | `SKU_TIER_AKS_DEV` | O | Y: `"Standard"`<br>J.dev: `"Standard"` | AKS SKU tier Dev |
| <!-- parameter yaml:skuTierAksStageProd --><!-- parameter json.dev:skuTierAksStageProd -->`skuTierAksStageProd` | `SKU_TIER_AKS_STAGEPROD` | O | Y: `"Standard"`<br>J.dev: `"Standard"` | AKS SKU tier Stage/Prod |
| <!-- parameter yaml:skuTierAzureMLDev --><!-- parameter json.dev:skuTierAzureMLDev -->`skuTierAzureMLDev` | `SKU_TIER_AZUREML_DEV` | O | Y: `"basic"`<br>J.dev: `"basic"` | Azure ML workspace tier Dev |
| <!-- parameter yaml:skuTierAzureMLStageProd --><!-- parameter json.dev:skuTierAzureMLStageProd -->`skuTierAzureMLStageProd` | `SKU_TIER_AZUREML_STAGEPROD` | O | Y: `"basic"`<br>J.dev: `"basic"` | Azure ML workspace tier Stage/Prod |
| <!-- parameter yaml:skuTierFunctionDev --><!-- parameter json.dev:skuTierFunctionDev -->`skuTierFunctionDev` | `SKU_TIER_FUNCTION_DEV` | O | Y: `"ElasticPremium"`<br>J.dev: `"ElasticPremium"` | Function plan tier Dev |
| <!-- parameter yaml:skuTierFunctionStageProd --><!-- parameter json.dev:skuTierFunctionStageProd -->`skuTierFunctionStageProd` | `SKU_TIER_FUNCTION_STAGEPROD` | O | Y: `"ElasticPremium"`<br>J.dev: `"ElasticPremium"` | Function plan tier Stage/Prod |
| <!-- parameter yaml:skuTierPostgreSQLDev --><!-- parameter json.dev:skuTierPostgreSQLDev -->`skuTierPostgreSQLDev` | `SKU_TIER_POSTGRESQL_DEV` | O | Y: `"Burstable"`<br>J.dev: `"Burstable"` | PostgreSQL tier Dev ['Burstable','GeneralPurpose','MemoryOptimized'] |
| <!-- parameter yaml:skuTierPostgreSQLStageProd --><!-- parameter json.dev:skuTierPostgreSQLStageProd -->`skuTierPostgreSQLStageProd` | `SKU_TIER_POSTGRESQL_STAGEPROD` | O | Y: `"Burstable"`<br>J.dev: `"Burstable"` | PostgreSQL tier Stage/Prod |
| <!-- parameter yaml:skuTierSQLDatabaseDev --><!-- parameter json.dev:skuTierSQLDatabaseDev -->`skuTierSQLDatabaseDev` | `SKU_TIER_SQLDATABASE_DEV` | O | Y: `"Standard"`<br>J.dev: `"Standard"` | Azure SQL DB tier Dev ['Basic','Standard','Premium'] |
| <!-- parameter yaml:skuTierSQLDatabaseStageProd --><!-- parameter json.dev:skuTierSQLDatabaseStageProd -->`skuTierSQLDatabaseStageProd` | `SKU_TIER_SQLDATABASE_STAGEPROD` | O | Y: `"Standard"`<br>J.dev: `"Standard"` | Azure SQL DB tier Stage/Prod |
| <!-- parameter yaml:skuTierWebAppDev --><!-- parameter json.dev:skuTierWebAppDev -->`skuTierWebAppDev` | `SKU_TIER_WEBAPP_DEV` | O | Y: `"PremiumV3"`<br>J.dev: `"PremiumV3"` | Web App plan tier Dev |
| <!-- parameter yaml:skuTierWebAppStageProd --><!-- parameter json.dev:skuTierWebAppStageProd -->`skuTierWebAppStageProd` | `SKU_TIER_WEBAPP_STAGEPROD` | O | Y: `"PremiumV3"`<br>J.dev: `"PremiumV3"` | Web App plan tier Stage/Prod |
| <!-- parameter yaml:skuVisionDev --><!-- parameter json.dev:skuVisionDev -->`skuVisionDev` | `SKU_VISION_DEV` | O | Y: `"S1"`<br>J.dev: `"S1"` | Azure AI Vision SKU Dev |
| <!-- parameter yaml:skuVisionStageProd --><!-- parameter json.dev:skuVisionStageProd -->`skuVisionStageProd` | `SKU_VISION_STAGEPROD` | O | Y: `"S1"`<br>J.dev: `"S1"` | Azure AI Vision SKU Stage/Prod |
| <!-- parameter yaml:skuWebAppDev --><!-- parameter json.dev:skuWebAppDev -->`skuWebAppDev` | `SKU_WEBAPP_DEV` | O | Y: `"P1v3"`<br>J.dev: `"P1v3"` | Web App plan SKU Dev |
| <!-- parameter yaml:skuWebAppStageProd --><!-- parameter json.dev:skuWebAppStageProd -->`skuWebAppStageProd` | `SKU_WEBAPP_STAGEPROD` | O | Y: `"P1v3"`<br>J.dev: `"P1v3"` | Web App plan SKU Stage/Prod |

### Identity, access and encryption

| YAML / JSON key | GHA binding(s) | M/C/O | Source defaults | Description / conditions |
|---|---|---|---|---|
| <!-- parameter yaml:apimGatewayManagedIdentityPrincipalId --><!-- parameter json.dev:apimGatewayManagedIdentityPrincipalId -->`apimGatewayManagedIdentityPrincipalId` | `APIM_GATEWAY_MANAGED_IDENTITY_PRINCIPAL_ID` | C | Y: `""`<br>J.dev: `""` | APIM system-assigned managed identity object ID. Required when assigning the OpenAI user role to the APIM managed identity. |
| <!-- parameter yaml:azureDevOpsTenantId --><!-- parameter json.dev:azureDevOpsTenantId -->`azureDevOpsTenantId` | No verified binding | M | Y: `"<todo>_AzureDevOpsTenantId"`<br>J.dev: `"<todo>_AzureDevOpsTenantId"` | Microsoft Entra tenant ID connected to the Azure DevOps organization. This can differ from tenantId used for Azure deployments. mandatory: Microsoft Entra tenant ID connected to the Azure DevOps organization. This can differ from tenantId used for Azure deployments. |
| <!-- parameter yaml:azure_machinelearning_sp_oid --><!-- parameter json.dev:azure_machinelearning_sp_oid -->`azure_machinelearning_sp_oid` | `AZURE_MACHINELEARNING_SP_OID`, `TENANT_AZUREML_OID` | C | Y: `"<todo>_ObjectID"`<br>J.dev: `"<todo>_ObjectID"` | Azure ML service principal OID mandatory: Azure ML service principal OID ensure: find in Entra ID as "Azure Machine Learning" app (AppId: 0736f41a-0425-4b46-bdb5-1563eff02385). otherwise: optional if enableAIFoundry:'false'. |
| <!-- parameter yaml:cmk --><!-- parameter json.dev:cmk -->`cmk` | `CMK` | O | Y: `"false"`<br>J.dev: `"false"` | Customer Managed Key encryption otherwise: true, enable CMK for Key Vault, Storage accounts, etc. |
| <!-- parameter yaml:cmkDisableForAISearch --><!-- parameter json.dev:cmkDisableForAISearch -->`cmkDisableForAISearch` | `CMK_DISABLE_FOR_AI_SEARCH` | O | Y: `"true"`<br>J.dev: `"true"` | Disable CMK for AI Search otherwise: true, disables CMK encryption for Azure AI Search even when cmk:'true'. Reason: Foundry runtime creates indexes without providing CMK info, causing failures. |
| <!-- parameter yaml:cmkDisableForFoundry --><!-- parameter json.dev:cmkDisableForFoundry -->`cmkDisableForFoundry` | `CMK_DISABLE_FOR_FOUNDRY` | O | Y: `"true"`<br>J.dev: `"true"` | Disable CMK for AI Foundry otherwise: true, disables CMK encryption for AI Foundry account even when cmk:'true'. Reason: Foundry does not respect AI Search CMK contract at runtime. |
| <!-- parameter yaml:cmkKeyName --><!-- parameter json.dev:cmkKeyName -->`cmkKeyName` | `CMK_KEY_NAME` | C | Y: `"<todo>_aifactory-cmk-key"`<br>J.dev: `"<todo>_aifactory-cmk-key"` | CMK key name in seeding KV mandatory: if cmk:'true' ensure: key name in your Seeding Keyvault to use for CMK encryption. |
| <!-- parameter yaml:cmkKeyVersion --><!-- parameter json.dev:cmkKeyVersion -->`cmkKeyVersion` | `CMK_KEY_VERSION` | O | Y: `""`<br>J.dev: `""` | CMK key version otherwise: pin to a specific GUID version string. |
| <!-- parameter yaml:commonServicePrincipleOIDKey --><!-- parameter json.dev:commonServicePrincipleOIDKey -->`commonServicePrincipleOIDKey` | `COMMON_SERVICE_PRINCIPLE_OID_KEY` | C | Y: `"<optional>esml-common-sp-oid"`<br>J.dev: `"<optional>esml-common-sp-oid"` | Seeding KV secret name for common SP OID ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter yaml:debug_disable_100_rbac_security --><!-- parameter json.dev:debug_disable_100_rbac_security -->`debug_disable_100_rbac_security` | `DEBUG_DISABLE_100_RBAC_SECURITY` | O | Y: `"false"`<br>J.dev: `"false"` | Skip RBAC and security step otherwise: true, skip RBAC and security step for all services (steps 61-99). |
| <!-- parameter yaml:dev_seeding_kv_service_connection --><!-- parameter json.dev:dev_seeding_kv_service_connection -->`dev_seeding_kv_service_connection` | No verified binding | M | Y: `"<todo>_ado_service_connection"`<br>J.dev: `"<todo>_ado_service_connection"` | ADO service connection for DEV seeding KV mandatory: ADO service connection for DEV seeding KV ensure: name matches your service connection for the DEV seeding KV subscription. otherwise: can be same as dev_service_connection. |
| <!-- parameter yaml:dev_service_connection --><!-- parameter json.dev:dev_service_connection -->`dev_service_connection` | No verified binding | M | Y: `"<todo>_ado_service_connection"`<br>J.dev: `"<todo>_ado_service_connection"` | ADO service connection for DEV mandatory: ADO service connection for DEV ensure: name matches your Azure DevOps service connection for the DEV subscription. |
| <!-- parameter yaml:disableContributorAccessForUsers --><!-- parameter json.dev:disableContributorAccessForUsers -->`disableContributorAccessForUsers` | `DISABLE_CONTRIBUTOR_ACCESS_FORUSERS`, `DISABLE_CONTRIBUTOR_ACCESS_FOR_USERS` (not in .env template) | O | Y: `"false"`<br>J.dev: `"false"` | Disable Contributor for project users recommended: false, enables users to create artifacts (managed online endpoints etc). otherwise: true, restrict Contributor access. |
| <!-- parameter yaml:disableLocalAuth --><!-- parameter json.dev:disableLocalAuth -->`disableLocalAuth` | `DISABLE_LOCAL_AUTH` | O | Y: `"true"`<br>J.dev: `"true"` | Disable local API key ("admin account") auth on Cognitive/AI Services & Foundry, AAD-only recommended: true, disables key auth (many orgs forbid keys). otherwise: false, allow local API keys. |
| <!-- parameter yaml:disableRBACAdminOnRGForUsers --><!-- parameter json.dev:disableRBACAdminOnRGForUsers -->`disableRBACAdminOnRGForUsers` | `DISABLE_RBAC_ADMIN_ON_RG_FORUSERS`, `DISABLE_RBAC_ADMIN_ON_RG_FOR_USERS` (not in .env template) | O | Y: `"true"`<br>J.dev: `"true"` | Disable RBAC Admin on RG for project users recommended: true, restricts users from assigning RBAC at resource group scope. |
| <!-- parameter yaml:groups_coreteam_members --><!-- parameter json.dev:groups_coreteam_members -->`groups_coreteam_members` | `GROUPS_CORETEAM_MEMBERS` | C | Y: `"<aif001sdc_coreteam_admin_p080>,<aif001sdc_coreteam_dataops_p081>,<aif001sdc_coreteam_dataops_fabric_p082>"`<br>J.dev: `"<aif001sdc_coreteam_admin_p080>,<aif001sdc_coreteam_dataops_p081>,<aif001sdc_coreteam_dataops_fabric_p082>"` | Core team AD group ObjectIDs mandatory: if use_ad_groups:'true' |
| <!-- parameter yaml:groups_project_members_esml --><!-- parameter json.dev:groups_project_members_esml -->`groups_project_members_esml` | `GROUPS_PROJECT_MEMBERS_ESML` | C | Y: `"<aif001sdc_prj001_team_lead_p001>,<aif001sdc_prj001_team_member_ds_p002>,<aif001sdc_prj001_team_member_fend_p003>"`<br>J.dev: `"<aif001sdc_prj001_team_lead_p001>,<aif001sdc_prj001_team_member_ds_p002>,<aif001sdc_prj001_team_member_fend_p003>"` | ESML project team AD group ObjectIDs mandatory: if use_ad_groups:'true' |
| <!-- parameter yaml:groups_project_members_genai_1 --><!-- parameter json.dev:groups_project_members_genai_1 -->`groups_project_members_genai_1` | `GROUPS_PROJECT_MEMBERS_GENAI_1` | C | Y: `"<aif001sdc_prj002_team_lead_p011>,<aif001sdc_prj002_genai_team_member_aifoundry_p012>,<aif002sdc_prj001_genai_team_member_agentic_p013>,<aif001sdc_prj001_genai_team_member_dataops_p014>,<aif001sdc_prj001_team_member_fend_p015>"`<br>J.dev: `"<aif001sdc_prj002_team_lead_p011>,<aif001sdc_prj002_genai_team_member_aifoundry_p012>,<aif002sdc_prj001_genai_team_member_agentic_p013>,<aif001sdc_prj001_genai_team_member_dataops_p014>,<aif001sdc_prj001_team_member_fend_p015>"` | GenAI-1 project team AD group ObjectIDs mandatory: if use_ad_groups:'true' |
| <!-- parameter yaml:inputCommonSPIDKey --><!-- parameter json.dev:inputCommonSPIDKey -->`inputCommonSPIDKey` | `INPUT_COMMON_SPID_KEY` | C | Y: `"<optional>esml-common-sp-id"`<br>J.dev: `"<optional>esml-common-sp-id"` | Seeding KV secret name for common SP App ID ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter yaml:inputCommonSPSecretKey --><!-- parameter json.dev:inputCommonSPSecretKey -->`inputCommonSPSecretKey` | `INPUT_COMMON_SP_SECRET_KEY` | C | Y: `"<optional>esml-common-sp-secret"`<br>J.dev: `"<optional>esml-common-sp-secret"` | Seeding KV secret name for common SP secret ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter yaml:personas_core_team --><!-- parameter json.dev:personas_core_team -->`personas_core_team` | `PERSONAS_CORE_TEAM` | O | Y: `"p080_coreteam_it_admin,coreteam_dataops,p081_coreteam_dataops_fabric, p103_coreteam_team_process_ops"`<br>J.dev: `"p080_coreteam_it_admin,coreteam_dataops,p081_coreteam_dataops_fabric, p103_coreteam_team_process_ops"` | Core team personas keep-as-is: Mapped to group_coreteam_members. |
| <!-- parameter yaml:personas_project_esml --><!-- parameter json.dev:personas_project_esml -->`personas_project_esml` | `PERSONAS_PROJECT_ESML` | O | Y: `"p001_esml_team_lead,p002_esml_team_member_datascientist,p003_esml_team_member_front_end,p101_esml_team_process_ops"`<br>J.dev: `"p001_esml_team_lead,p002_esml_team_member_datascientist,p003_esml_team_member_front_end,p101_esml_team_process_ops"` | ESML project personas keep-as-is: Mapped to groups_project_members_esml and PROJECT_TYPE=esml. |
| <!-- parameter yaml:personas_project_genai_1 --><!-- parameter json.dev:personas_project_genai_1 -->`personas_project_genai_1` | `PERSONAS_PROJECT_GENAI_1` | O | Y: `"p011_genai_team_lead,p012_genai_team_member_aifoundry,p013_genai_team_member_agentic,p014_genai_team_member_dataops,p015_genai_team_member_frontend,p102_esml_team_process_ops"`<br>J.dev: `"p011_genai_team_lead,p012_genai_team_member_aifoundry,p013_genai_team_member_agentic,p014_genai_team_member_dataops,p015_genai_team_member_frontend,p102_esml_team_process_ops"` | GenAI-1 project personas keep-as-is: Mapped to groups_project_members_genai_1 and PROJECT_TYPE=genai-1. |
| <!-- parameter yaml:prod_seeding_kv_service_connection --><!-- parameter json.dev:prod_seeding_kv_service_connection -->`prod_seeding_kv_service_connection` | No verified binding | C | Y: `"<todo>_ado_service_connection"`<br>J.dev: `"<todo>_ado_service_connection"` | ADO service connection for PROD seeding KV mandatory: ADO service connection for PROD seeding KV ensure: name matches your service connection for the PROD seeding KV subscription. otherwise: can be same as prod_service_connection. Required when deploying that environment. |
| <!-- parameter yaml:prod_service_connection --><!-- parameter json.dev:prod_service_connection -->`prod_service_connection` | No verified binding | C | Y: `"<todo>_ado_service_connection"`<br>J.dev: `"<todo>_ado_service_connection"` | ADO service connection for PROD mandatory: ADO service connection for PROD ensure: name matches your Azure DevOps service connection for the PROD subscription. Required when deploying that environment. |
| <!-- parameter yaml:project_service_principal_AppID_seeding_kv_name --><!-- parameter json.dev:project_service_principal_AppID_seeding_kv_name -->`project_service_principal_AppID_seeding_kv_name` | `PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID` | C | Y: `"<optional>esml-project001-sp-id"`<br>J.dev: `"<optional>esml-project001-sp-id"` | Project SP App ID secret name in seeding KV ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter yaml:project_service_principal_OID_seeding_kv_name --><!-- parameter json.dev:project_service_principal_OID_seeding_kv_name -->`project_service_principal_OID_seeding_kv_name` | `PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_OID` | C | Y: `"<optional>esml-project001-sp-oid"`<br>J.dev: `"<optional>esml-project001-sp-oid"` | Project SP OID secret name in seeding KV ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter yaml:project_service_principal_Secret_seeding_kv_name --><!-- parameter json.dev:project_service_principal_Secret_seeding_kv_name -->`project_service_principal_Secret_seeding_kv_name` | `PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_S` | C | Y: `"<optional>esml-project001-sp-secret"`<br>J.dev: `"<optional>esml-project001-sp-secret"` | Project SP secret name in seeding KV ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter yaml:technical_admins_ad_object_id --><!-- parameter json.dev:technical_admins_ad_object_id -->`technical_admins_ad_object_id` | `PROJECT_MEMBERS` | M | Y: `"<todo>_EntraID_ObjectID"`<br>J.dev: `"<todo>_EntraID_ObjectID"` | Project team Entra ID object ID(s) mandatory: Project team Entra ID object ID(s) ensure: comma-separated ObjectIDs of users or AD groups for the project team. |
| <!-- parameter yaml:technical_admins_email --><!-- parameter json.dev:technical_admins_email -->`technical_admins_email` | `AIF-Project Owners` (not in .env template), `PROJECT_MEMBERS_EMAILS` | O | Y: `"<todo>_email_or_securitygroup_name"`<br>J.dev: `"<todo>_email_or_securitygroup_name"` | Project team contact email or group name recommended: set for better project tracking. |
| <!-- parameter yaml:tenantId --><!-- parameter json.dev:tenantId -->`tenantId` | `TENANT_ID` | M | Y: `"<todo>_TenantId"`<br>J.dev: `"<todo>_TenantId"` | Azure tenant ID mandatory: Azure tenant ID ensure: find in Azure Portal &gt; Entra ID &gt; Overview (Directory ID). |
| <!-- parameter yaml:test_seeding_kv_service_connection --><!-- parameter json.dev:test_seeding_kv_service_connection -->`test_seeding_kv_service_connection` | No verified binding | C | Y: `"<todo>_ado_service_connection"`<br>J.dev: `"<todo>_ado_service_connection"` | ADO service connection for STAGE seeding KV mandatory: ADO service connection for STAGE seeding KV ensure: name matches your service connection for the STAGE seeding KV subscription. otherwise: can be same as test_service_connection. Required when deploying that environment. |
| <!-- parameter yaml:test_service_connection --><!-- parameter json.dev:test_service_connection -->`test_service_connection` | No verified binding | C | Y: `"<todo>_ado_service_connection"`<br>J.dev: `"<todo>_ado_service_connection"` | ADO service connection for STAGE mandatory: ADO service connection for STAGE ensure: name matches your Azure DevOps service connection for the STAGE subscription. Required when deploying that environment. |
| <!-- parameter yaml:updateKeyvaultRbac --><!-- parameter json.dev:updateKeyvaultRbac -->`updateKeyvaultRbac` | `UPDATE_KEYVAULT_RBAC` | O | Y: `"false"`<br>J.dev: `"false"` | Update Key Vault RBAC otherwise: true, re-run to update RBAC properties. |
| <!-- parameter yaml:use_ad_groups --><!-- parameter json.dev:use_ad_groups -->`use_ad_groups` | `USE_AD_GROUPS` | O | Y: `"true"`<br>J.dev: `"true"` | Use AD groups for project members otherwise: false, use individual ObjectIDs and simple mode Personas. |

### Models and deployments

| YAML / JSON key | GHA binding(s) | M/C/O | Source defaults | Description / conditions |
|---|---|---|---|---|
| <!-- parameter yaml:default_embedding_capacity --><!-- parameter json.dev:default_embedding_capacity -->`default_embedding_capacity` | `DEFAULT_EMBEDDING_CAPACITY` | O | Y: `25`<br>J.dev: `25` | Embedding model TPM capacity (K) keep-as-is: 25 = 25K tokens per minute. |
| <!-- parameter yaml:default_gpt_4o_version --><!-- parameter json.dev:default_gpt_4o_version -->`default_gpt_4o_version` | `DEFAULT_GPT_4O_VERSION` | O | Y: `"2024-11-20"`<br>J.dev: `"2024-11-20"` | gpt-4o version otherwise: "2024-08-06". |
| <!-- parameter yaml:default_gpt_54_mini_version --><!-- parameter json.dev:default_gpt_54_mini_version -->`default_gpt_54_mini_version` | `DEFAULT_GPT_54_MINI_VERSION` | O | Y: `"2026-03-17"`<br>J.dev: `"2026-03-17"` | Version for the separately named GPT-5.4-mini deployment toggle. |
| <!-- parameter yaml:default_gpt_capacity --><!-- parameter json.dev:default_gpt_capacity -->`default_gpt_capacity` | `DEFAULT_GPT_CAPACITY` | O | Y: `40`<br>J.dev: `40` | GPT model TPM capacity (K) keep-as-is: 40 = 40K tokens per minute. |
| <!-- parameter yaml:default_model_sku --><!-- parameter json.dev:default_model_sku -->`default_model_sku` | `DEFAULT_MODEL_SKU` | O | Y: `"DataZoneStandard"`<br>J.dev: `"DataZoneStandard"` | Default model deployment SKU keep-as-is: Keep inference within the selected data zone; confirm model/SKU availability and quota. |
| <!-- parameter yaml:deployModel_gpt_4o --><!-- parameter json.dev:deployModel_gpt_4o -->`deployModel_gpt_4o` | `DEPLOY_MODEL_GPT_4O` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy gpt-4o recommended: for general-purpose AI Foundry scenarios. |
| <!-- parameter yaml:deployModel_gpt_54_mini --><!-- parameter json.dev:deployModel_gpt_54_mini -->`deployModel_gpt_54_mini` | `DEPLOY_MODEL_GPT_54_MINI` | O | Y: `"false"`<br>J.dev: `"false"` | Enable the separately named GPT-5.4-mini deployment toggle; inspect its workflow binding alongside deployModel_gpt_X. |
| <!-- parameter yaml:deployModel_gpt_X --><!-- parameter json.dev:deployModel_gpt_X -->`deployModel_gpt_X` | `DEPLOY_MODEL_GPT_X` | O | Y: `"true"`<br>J.dev: `"true"` | Deploy custom GPT-X model otherwise: true, deploy the model defined in modelGPTXName. |
| <!-- parameter yaml:deployModel_text_embedding_3_large --><!-- parameter json.dev:deployModel_text_embedding_3_large -->`deployModel_text_embedding_3_large` | `DEPLOY_MODEL_TEXT_EMBEDDING_3_LARGE` | O | Y: `"true"`<br>J.dev: `"true"` | Deploy text-embedding-3-large recommended: for production RAG scenarios. |
| <!-- parameter yaml:deployModel_text_embedding_3_small --><!-- parameter json.dev:deployModel_text_embedding_3_small -->`deployModel_text_embedding_3_small` | `DEPLOY_MODEL_TEXT_EMBEDDING_3_SMALL` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy text-embedding-3-small recommended: for cost-optimized scenarios. |
| <!-- parameter yaml:deployModel_text_embedding_ada_002 --><!-- parameter json.dev:deployModel_text_embedding_ada_002 -->`deployModel_text_embedding_ada_002` | `DEPLOY_MODEL_TEXT_EMBEDDING_ADA_002` | O | Y: `"false"`<br>J.dev: `"false"` | Deploy text-embedding-ada-002 |
| <!-- parameter yaml:modelGPTXCapacity --><!-- parameter json.dev:modelGPTXCapacity -->`modelGPTXCapacity` | `MODEL_GPTX_CAPACITY` | O | Y: `30`<br>J.dev: `30` | GPT-X TPM capacity (K) keep-as-is: 30 = 30K tokens per minute. |
| <!-- parameter yaml:modelGPTXName --><!-- parameter json.dev:modelGPTXName -->`modelGPTXName` | `MODEL_GPTX_NAME` | O | Y: `"gpt-5.4-mini"`<br>J.dev: `"gpt-5.4-mini"` | GPT-X model name ensure: model is available in your Azure region with sufficient quota. |
| <!-- parameter yaml:modelGPTXSku --><!-- parameter json.dev:modelGPTXSku -->`modelGPTXSku` | `MODEL_GPTX_SKU` | O | Y: `"DataZoneStandard"`<br>J.dev: `"DataZoneStandard"` | GPT-X deployment SKU keep-as-is: Keep inference within the selected data zone; confirm model/SKU availability and quota. |
| <!-- parameter yaml:modelGPTXVersion --><!-- parameter json.dev:modelGPTXVersion -->`modelGPTXVersion` | `MODEL_GPTX_VERSION` | O | Y: `"2026-03-17"`<br>J.dev: `"2026-03-17"` | GPT-X model version ensure: update the version when selecting a different model. |

## GitHub Actions .env reference

Every unique assignment is included, including orchestrator-only and compatibility names. Values are decoded literals, not expansions; these are template values, not necessarily the workflow's effective fallback. **No verified counterpart** means no mapping was found in the inspected shared bindings, not proof that a setting is unused.

### GHA: Factory, project, naming and orchestration

| Exact environment key | YAML / JSON counterpart(s) | M/C/O | Template value | Description / conditions |
|---|---|---|---|---|
| <!-- parameter env:ACA_W_REGISTRY_IMAGE -->`ACA_W_REGISTRY_IMAGE` | `aca_w_registry_image` | O | `"mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"` | Container Apps default registry image |
| <!-- parameter env:ADMIN_AISEARCH_TIER -->`ADMIN_AISEARCH_TIER` | `admin_aiSearchTier`, `skuAISearchDev`, `skuAISearchStageProd` | M | `"basic"` | AI Search SKU tier mandatory: AI Search SKU tier ensure: 'free' is not allowed when using private endpoints. ['free','basic','standard','standard2','standard3','storage_optimized_l1','storage_optimized_l2'] |
| <!-- parameter env:ADMIN_AI_SEARCH_TIER -->`ADMIN_AI_SEARCH_TIER` | `admin_aiSearchTier` | M | `"basic"` | AI Search SKU tier mandatory: AI Search SKU tier ensure: 'free' is not allowed when using private endpoints. ['free','basic','standard','standard2','standard3','storage_optimized_l1','storage_optimized_l2'] |
| <!-- parameter env:ADMIN_COMMON_RESOURCE_SUFFIX -->`ADMIN_COMMON_RESOURCE_SUFFIX` | `admin_commonResourceSuffix` | O | `"-001"` | Common resources suffix otherwise: change to reprovision new services in the same common RG while keeping old ones. |
| <!-- parameter env:ADMIN_HYBRID_BENEFIT -->`ADMIN_HYBRID_BENEFIT` | `admin_hybridBenefit` | O | `"true"` | Azure Hybrid Benefit for VMs otherwise: true, if you have eligible Windows licenses with Software Assurance (pay-as-you-go avoided). |
| <!-- parameter env:ADMIN_IP_FW -->`ADMIN_IP_FW` | `admin_ip_fw` | O | `""` | Admin IP for firewall rules keep-as-is: Used by GHA runner to whitelist its own IP. |
| <!-- parameter env:ADMIN_PRJ_RESOURCE_SUFFIX -->`ADMIN_PRJ_RESOURCE_SUFFIX` | `admin_prjResourceSuffix` | O | `"-001"` | Project resources suffix otherwise: change to reprovision new services in the same project RG while keeping old ones. |
| <!-- parameter env:ADMIN_SEMANTIC_SEARCH_TIER -->`ADMIN_SEMANTIC_SEARCH_TIER` | `admin_semanticSearchTier` | M | `"free"` | Semantic search tier mandatory: Semantic search tier |
| <!-- parameter env:ADMIN_USERNAME -->`ADMIN_USERNAME` | `adminUsername` | O | `"esmladmin"` | VM admin username |
| <!-- parameter env:AIFACTORY_BRANCH_CHOSEN -->`AIFACTORY_BRANCH_CHOSEN` | `aifactory_branch_chosen` | O | `"release/v1.24"` | Submodule release branch |
| <!-- parameter env:AIFACTORY_COMMON_ONLY_DEV_ENVIRONMENT -->`AIFACTORY_COMMON_ONLY_DEV_ENVIRONMENT` | No verified counterpart | O | `"true"` | Create common-DEV environment only otherwise: false, creates Dev, Stage, Prod environments in Azure. |
| <!-- parameter env:AIFACTORY_DASHBOARD_URL -->`AIFACTORY_DASHBOARD_URL` | `aifactory-dash-01` | O | `""` | Existing Azure Portal AI Factory dashboard URL; never deploys a dashboard. |
| <!-- parameter env:AIFACTORY_LOCATION -->`AIFACTORY_LOCATION` | `admin_location` | M | `"eastus2"` | Azure region mandatory: Azure region |
| <!-- parameter env:AIFACTORY_LOCATION_SHORT -->`AIFACTORY_LOCATION_SHORT` | `admin_locationSuffix` | M | `"eus2"` | Region short name mandatory: Region short name |
| <!-- parameter env:AIFACTORY_PREFIX -->`AIFACTORY_PREFIX` | `admin_aifactoryPrefixRG` | O | `"acme-ai"` | AI Factory resource group prefix keep-as-is: Max 6 chars. otherwise: set your company prefix, e.g. 'acme-ai-', 'contoso-'. |
| <!-- parameter env:AIFACTORY_SALT -->`AIFACTORY_SALT` | `aifactory_salt` | O | `"<5>"` | AI Factory deterministic salt (5 chars) ensure: read from COMMON RG resource names, e.g. the 'a4c2b' in 'adf-cmn-weu-dev-a4c2b-001'. Used in project resource naming. |
| <!-- parameter env:AIFACTORY_SALT_RANDOM -->`AIFACTORY_SALT_RANDOM` | `aifactory_salt_random` | O | `"<10>"` | Random salt placeholder (10 chars) keep-as-is: Do not change. Placeholder only. |
| <!-- parameter env:AIFACTORY_SEEDING_KEYVAULT_NAME -->`AIFACTORY_SEEDING_KEYVAULT_NAME` | `dev_admin_bicep_kv_fw`, `prod_admin_bicep_kv_fw`, `test_admin_bicep_kv_fw` | M | `"kv-seeding-sdc-001<todo>"` | DEV seeding KV name mandatory: DEV seeding KV name ensure: Key Vault name storing secrets mapped to PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID. |
| <!-- parameter env:AIFACTORY_SEEDING_KEYVAULT_RG -->`AIFACTORY_SEEDING_KEYVAULT_RG` | `dev_admin_bicep_kv_fw_rg`, `prod_admin_bicep_kv_fw_rg`, `test_admin_bicep_kv_fw_rg` | M | `"rg-seeding-sdc-001<todo>"` | DEV seeding KV resource group mandatory: DEV seeding KV resource group ensure: resource group where the DEV seeding Key Vault resides. |
| <!-- parameter env:AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID -->`AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID` | `dev_admin_bicep_input_keyvault_subscription`, `prod_admin_bicep_input_keyvault_subscription`, `test_admin_bicep_input_keyvault_subscription` | M | `"<todo>"` | DEV seeding KV subscription ID mandatory: DEV seeding KV subscription ID ensure: subscription where the DEV seeding Key Vault resides. |
| <!-- parameter env:AIFACTORY_SUFFIX -->`AIFACTORY_SUFFIX` | `admin_aifactorySuffixRG` | M | `"-001"` | AI Factory scaleset suffix mandatory: AI Factory scaleset suffix keep-as-is: For 1st scaleset. otherwise: increment to '-002', '-003' for additional scalesets. |
| <!-- parameter env:AIFACTORY_VERSION_MAJOR -->`AIFACTORY_VERSION_MAJOR` | `aifactory_version_major` | O | `"1"` | AI Factory major version keep-as-is: Used to determine which bicep files to use. |
| <!-- parameter env:AIFACTORY_VERSION_MINOR -->`AIFACTORY_VERSION_MINOR` | `aifactory_version_minor` | O | `"24"` | AI Factory minor version keep-as-is: 2025-09-20: 24 = release/v1.24 |
| <!-- parameter env:AISEARCH_SEMANTIC_TIER -->`AISEARCH_SEMANTIC_TIER` | `admin_semanticSearchTier` | M | `"free"` | Semantic search tier mandatory: Semantic search tier |
| <!-- parameter env:AI_SEARCH_LOCATION -->`AI_SEARCH_LOCATION` | `aiSearchLocation` | O | `""` | AI Search region override. Empty keeps AIFACTORY_LOCATION. |
| <!-- parameter env:AML_STUDIO_UI_PRIVATE -->`AML_STUDIO_UI_PRIVATE` | `AMLStudioUIPrivate` | O | `"true"` | AML Studio UI private access otherwise: false, only data plane is private; control plane is public. |
| <!-- parameter env:ASE_SKU -->`ASE_SKU` | `aseSku` | O | `"IsolatedV2"` | App Service Environment SKU |
| <!-- parameter env:ASE_SKU_CODE -->`ASE_SKU_CODE` | `aseSkuCode` | O | `"I1v2"` | ASE SKU code |
| <!-- parameter env:ASE_SKU_WORKERS -->`ASE_SKU_WORKERS` | `aseSkuWorkers` | O | `"1"` | ASE number of workers |
| <!-- parameter env:AZURE_CLIENT_ID -->`AZURE_CLIENT_ID` | No verified counterpart | O | `""` | Preferred credentialless deployment identity: client ID of a federated app or user-assigned managed identity. When set, workflows use OIDC instead of AZURE_CREDENTIALS. |
| <!-- parameter env:BASTION_CUSTOM_NAME -->`BASTION_CUSTOM_NAME` | `bastion_custom_name` | O | `""` | Bastion name override for common RG RBAC keep-as-is: Empty uses the standard Bastion naming convention. |
| <!-- parameter env:BASTION_SUBSCRIPTION_RESOURCE_GROUP -->`BASTION_SUBSCRIPTION_RESOURCE_GROUP` | `bastion_subscription_resource_group` | O | `""` | Bastion resource group override for common RG RBAC keep-as-is: Empty uses the common resource group. |
| <!-- parameter env:BING_CUSTOM_SEARCH_SKU -->`BING_CUSTOM_SEARCH_SKU` | `bingCustomSearchSku` | O | `"G2"` | Bing Custom Search SKU |
| <!-- parameter env:COMMON_RESOURCE_GROUP_PARAM -->`COMMON_RESOURCE_GROUP_PARAM` | `commonResourceGroup_param` | O | `""` | BYO common resource group name otherwise: provide a custom name for the common resource group. |
| <!-- parameter env:COSMOS_KIND -->`COSMOS_KIND` | `cosmosKind` | O | `"GlobalDocumentDB"` | Cosmos DB kind otherwise: MongoDB. |
| <!-- parameter env:DATALAKE_NAME_PARAM -->`DATALAKE_NAME_PARAM` | `datalakeName_param` | O | `""` | BYO data lake storage account name otherwise: provide a custom storage account name. |
| <!-- parameter env:DEV_SUBSCRIPTION_ID -->`DEV_SUBSCRIPTION_ID` | `dev_sub_id` | M | `"<todo>"` | DEV subscription ID mandatory: DEV subscription ID |
| <!-- parameter env:FUNCTION_RUNTIME -->`FUNCTION_RUNTIME` | `functionRuntime` | O | `"dotnet"` | Functions runtime stack otherwise: python, node, java. |
| <!-- parameter env:FUNCTION_VERSION -->`FUNCTION_VERSION` | `functionVersion` | O | `"v7.0"` | Functions runtime version |
| <!-- parameter env:GITHUB_NEW_REPO -->`GITHUB_NEW_REPO` | `GITHUB_NEW_REPO` | M | `"<todo>/<todo>azure-enterprise-scale-aifactory-001"` | New GitHub repository path mandatory: New GitHub repository path ensure: format: |
| <!-- parameter env:GITHUB_NEW_REPO_VISIBILITY -->`GITHUB_NEW_REPO_VISIBILITY` | `GITHUB_NEW_REPO_VISIBILITY` | O | `"public"` | New repository visibility otherwise: private or internal. |
| <!-- parameter env:GITHUB_TEMPLATE_REPO -->`GITHUB_TEMPLATE_REPO` | `GITHUB_TEMPLATE_REPO` | O | `"azure/enterprise-scale-aifactory"` | GitHub template repository keep-as-is: Leave as-is if BYO repo. |
| <!-- parameter env:GITHUB_USERNAME -->`GITHUB_USERNAME` | `GITHUB_USERNAME` | M | `"<todo>"` | GitHub username or org mandatory: GitHub username or org |
| <!-- parameter env:GITHUB_USE_SSH -->`GITHUB_USE_SSH` | `GITHUB_USE_SSH` | O | `"false"` | Use SSH for git operations otherwise: true, use SSH instead of HTTPS. |
| <!-- parameter env:KEYVAULT_SOFT_DELETE -->`KEYVAULT_SOFT_DELETE` | `admin_keyvaultSoftDeleteDays` | C | `"7"` | Key Vault soft delete days mandatory: if CMK:'true' (purge protection required). otherwise: 90 days recommended; 0 to disable. |
| <!-- parameter env:KV_NAME_FROM_COMMON_PARAM -->`KV_NAME_FROM_COMMON_PARAM` | `kvNameFromCOMMON_param` | O | `""` | BYO common Key Vault name otherwise: provide a custom Key Vault name. |
| <!-- parameter env:LAKE_CONTAINER_NAME -->`LAKE_CONTAINER_NAME` | `lakeContainerName` | O | `"lake3"` | Data lake container name |
| <!-- parameter env:LAKE_PREFIX -->`LAKE_PREFIX` | `commonLakeNamePrefixMax8chars` | O | `"xxxyyy"` | Data lake storage name prefix keep-as-is: Max 8 characters. |
| <!-- parameter env:LOGIC_APP_TYPE -->`LOGIC_APP_TYPE` | No verified counterpart | O | `"Standard"` | Logic Apps plan type keep-as-is: Consumption is multi-tenant with NO private endpoints/VNet integration - only valid when ENABLE_PUBLIC_ACCESS_WITH_PERIMETER:'true'. Use Standard for private networking. |
| <!-- parameter env:MAX_RETRY_ATTEMPTS -->`MAX_RETRY_ATTEMPTS` | `maxRetryAttempts` | O | `"2"` | Maximum retry attempts keep-as-is: Valid values: 1, 2, or 3. |
| <!-- parameter env:ORG_DEPARTMENT_ID -->`ORG_DEPARTMENT_ID` | `org-department-id` | O | `""` | Project organizational department ID keep-as-is: Text, max 128 characters, not necessarily a GUID; identical across environments. No identity or authentication effect. |
| <!-- parameter env:ORG_DEPARTMENT_NAME -->`ORG_DEPARTMENT_NAME` | `org-department-name` | O | `""` | Project organizational department name keep-as-is: Unicode text, max 200 characters; identical across environments, independent of cost center. No factory inheritance or Azure tag writes. |
| <!-- parameter env:POSTGRES_ADMIN_EMAILS -->`POSTGRES_ADMIN_EMAILS` | `postGresAdminEmails` | C | `""` | PostgreSQL administrator email(s) mandatory: if ENABLE_POSTGRESQL:'true' ensure: single email address for the PostgreSQL administrator. |
| <!-- parameter env:PROD_SUBSCRIPTION_ID -->`PROD_SUBSCRIPTION_ID` | `prod_sub_id` | C | `"<todo>"` | PROD subscription ID recommended: separate subscription from DEV. otherwise: can reuse DEV_SUBSCRIPTION_ID. Required when deploying that environment. |
| <!-- parameter env:PROJECT_NUMBER -->`PROJECT_NUMBER` | `project_number_000` | M | `"001"` | Project number mandatory: Project number keep-as-is: For 1st project. otherwise: increment to '002', '003', etc. |
| <!-- parameter env:PROJECT_PREFIX -->`PROJECT_PREFIX` | `projectPrefix` | O | `"esml-"` | Project resource name prefix |
| <!-- parameter env:PROJECT_SUFFIX -->`PROJECT_SUFFIX` | `projectSuffix` | O | `"-rg"` | Project resource name suffix |
| <!-- parameter env:PROJECT_TYPE -->`PROJECT_TYPE` | `admin_projectType` | O | `"all"` | Project type keep-as-is: Not used anymore. Leave as is. |
| <!-- parameter env:STAGE_SUBSCRIPTION_ID -->`STAGE_SUBSCRIPTION_ID` | `test_sub_id` | C | `"<todo>"` | STAGE subscription ID recommended: separate subscription from DEV. otherwise: can reuse DEV_SUBSCRIPTION_ID. Required when deploying that environment. |
| <!-- parameter env:TAGS -->`TAGS` | `tags` | O | `"{\"CostCenter\":\"9999\",\"Description\":\"AI Factory common\",\"AIF-Repo\":\"aifactory\",\"AIF-Branch\":\"aifactory-001\",\"AIF-Version\":\"1.24\",\"AIF-Submodule-Chosen-Branch\":\"release/v1.24\",\"AIF-Scaleset\":\"-001\",\"AIF-Project Owners\":\"\",\"AIFactory project\":\"001\",\"AIF-Networking\":\"true,true,true\",\"AIF-enableAIFactoryCreatedDefaultProjectForAIFv2\":\"true\",\"AIF-disableAgentNetworkInjection\":\"false\",\"AIF-byoASEv3\":\"false\",\"AIF-BYO_subnets\":\"false\"}"` | Common-level Azure resource tags (JSON) keep-as-is: Update CostCenter, Description, and branch values to match your deployment. |
| <!-- parameter env:TAGS_PROJECT -->`TAGS_PROJECT` | `tagsProject` | O | `"{\"CostCenter\":\"1234\",\"Description\":\"RAG Chat 1\",\"AIF-Branch\":\"aifactory-001/project001\",\"AIF-Scaleset\":\"-001\",\"AIF-Environment\":\"dev\",\"AIF-Project Owners\":\"\",\"AIFactory project\":\"001\",\"AIF-Networking\":\"true,true,true\",\"AIF-enableAIFactoryCreatedDefaultProjectForAIFv2\":\"true\",\"AIF-disableAgentNetworkInjection\":\"false\",\"AIF-byoASEv3\":\"false\",\"AIF-BYO_subnets\":\"false\"}"` | Project-level Azure resource tags (JSON) keep-as-is: Update CostCenter, Description, and project values to match your project. |
| <!-- parameter env:TAG_COSTCENTER -->`TAG_COSTCENTER` | `tag_costcenter` | O | `"1234"` | Project cost center tag keep-as-is: Metadata for per-project cost tracking. |
| <!-- parameter env:TAG_COSTCETER_COMMON -->`TAG_COSTCETER_COMMON` | `tag_costceter_common` | O | `"9999"` | Common cost center tag keep-as-is: Metadata for Resource group cost tracking. |
| <!-- parameter env:TAG_REPOSITORY -->`TAG_REPOSITORY` | `tag_repository` | O | `"aifactory"` | Repository name tag |
| <!-- parameter env:TAG_REPOSITORY_BRANCH -->`TAG_REPOSITORY_BRANCH` | `tag_repository_branch` | O | `"aifactory-001"` | Repository branch tag otherwise: per scaleset 'aifactory-002', or per project 'aifactory-001/project001-main'. |
| <!-- parameter env:USE_COMMON_ACR_FOR_PROJECTS -->`USE_COMMON_ACR_FOR_PROJECTS` | `useCommonACR`, `useCommonACR_override` | O | `"true"` | Use shared ACR across projects otherwise: false, each project gets its own ACR (higher cost). |
| <!-- parameter env:USE_COMMON_ACR_OVERRIDE -->`USE_COMMON_ACR_OVERRIDE` | `useCommonACR_override` | O | `"true"` | Use shared ACR across projects (override) |
| <!-- parameter env:USE_SELF_HOSTED_BUILD_AGENT -->`USE_SELF_HOSTED_BUILD_AGENT` | `useSelfHostedBuildAgent` | O | `"false"` | Run project deployment jobs on a registered self-hosted runner |
| <!-- parameter env:WEBAPP_RUNTIME -->`WEBAPP_RUNTIME` | `webAppRuntime` | O | `"python"` | Web App runtime stack otherwise: dotnet, node, java. |
| <!-- parameter env:WEBAPP_RUNTIME_VERSION -->`WEBAPP_RUNTIME_VERSION` | `webAppRuntimeVersion` | O | `"3.11"` | Web App runtime version |

### GHA: Services and feature switches

| Exact environment key | YAML / JSON counterpart(s) | M/C/O | Template value | Description / conditions |
|---|---|---|---|---|
| <!-- parameter env:ACR_ADMIN_USER_ENABLED -->`ACR_ADMIN_USER_ENABLED` | `acr_adminUserEnabled` | O | `"false"` | Enable ACR admin user otherwise: true enables admin user; false is more secure. |
| <!-- parameter env:ACR_DEDICATED -->`ACR_DEDICATED` | `acr_dedicated` | O | `"true"` | Dedicated ACR (Premium only) |
| <!-- parameter env:ACR_SKU -->`ACR_SKU` | `acr_SKU` | O | `"Premium"` | ACR SKU keep-as-is: Premium required for private endpoints or CMK. |
| <!-- parameter env:ADD_AI_FOUNDRY -->`ADD_AI_FOUNDRY` | `addAIFoundry` | O | `"false"` | Add new AI Foundry instance otherwise: true, add new Foundry even if one already exists. |
| <!-- parameter env:ADD_AI_FOUNDRY_HUB -->`ADD_AI_FOUNDRY_HUB` | `addAIFoundryHub` | O | `"false"` | DEPRECATED: Add new legacy Hub v1 keep-as-is: Add new Hub even if one exists. Use ADD_AI_FOUNDRY instead. |
| <!-- parameter env:ADD_AI_SEARCH -->`ADD_AI_SEARCH` | `addAISearch` | O | `"false"` | Add new AI Search instance otherwise: true, add new instance even if one exists. |
| <!-- parameter env:ADD_AZURE_MACHINE_LEARNING -->`ADD_AZURE_MACHINE_LEARNING` | `addAzureMachineLearning` | O | `"false"` | Add new Azure ML workspace |
| <!-- parameter env:ADD_BASTION_HOST -->`ADD_BASTION_HOST` | `addBastionHost` | O | `"false"` | Add Bastion Host in common RG |
| <!-- parameter env:APIM_GATEWAY_AGGREGATE_TPM -->`APIM_GATEWAY_AGGREGATE_TPM` | `apimGatewayAggregateTpm` | C | `""` | 80-90% of summed TPM across all Azure OpenAI backends. Required by the separate AI gateway workflow when APIM is enabled. |
| <!-- parameter env:APIM_GATEWAY_API_ID -->`APIM_GATEWAY_API_ID` | `apimGatewayApiId` | O | `"azure-openai-gpt55"` | Apim gateway api id. |
| <!-- parameter env:APIM_GATEWAY_API_PATH -->`APIM_GATEWAY_API_PATH` | `apimGatewayApiPath` | O | `"openai"` | Apim gateway api path. |
| <!-- parameter env:APIM_GATEWAY_ASSIGN_OPENAI_USER_ROLE -->`APIM_GATEWAY_ASSIGN_OPENAI_USER_ROLE` | `apimGatewayAssignOpenAIUserRole` | O | `"false"` | Apim gateway assign openai user role. |
| <!-- parameter env:APIM_GATEWAY_BACKENDS_JSON -->`APIM_GATEWAY_BACKENDS_JSON` | `apimGatewayBackendsJson` | C | `"[]"` | Apim gateway backends json. Required by the separate AI gateway workflow when APIM is enabled. |
| <!-- parameter env:APIM_GATEWAY_BACKEND_POOL_NAME -->`APIM_GATEWAY_BACKEND_POOL_NAME` | `apimGatewayBackendPoolName` | O | `"aoai-gpt55-pool"` | Apim gateway backend pool name. |
| <!-- parameter env:APIM_GATEWAY_CALLER_TPM -->`APIM_GATEWAY_CALLER_TPM` | `apimGatewayCallerTpm` | O | `"10000"` | Apim gateway caller tpm. |
| <!-- parameter env:APIM_GATEWAY_RESOURCE_GROUP -->`APIM_GATEWAY_RESOURCE_GROUP` | `apimGatewayResourceGroup` | C | `""` | Apim gateway resource group. Required by the separate AI gateway workflow when APIM is enabled. |
| <!-- parameter env:APIM_GATEWAY_RETRY_COUNT -->`APIM_GATEWAY_RETRY_COUNT` | `apimGatewayRetryCount` | O | `"2"` | Apim gateway retry count. |
| <!-- parameter env:APIM_GATEWAY_SERVICE_NAME -->`APIM_GATEWAY_SERVICE_NAME` | `apimGatewayServiceName` | C | `""` | Apim gateway service name. Required by the separate AI gateway workflow when APIM is enabled. |
| <!-- parameter env:APIM_GATEWAY_SKU -->`APIM_GATEWAY_SKU` | `apimGatewaySku` | O | `"StandardV2"` | BasicV2=dev/test; StandardV2=production default + VNet integration; PremiumV2=full private network isolation, zones, and high scale. Classic Developer/Basic/Standard/Premium cannot migrate to v2 in place. Consumption cannot use backend circuit breakers. |
| <!-- parameter env:APIM_GATEWAY_SKU_CAPACITY -->`APIM_GATEWAY_SKU_CAPACITY` | `apimGatewaySkuCapacity` | O | `"1"` | BasicV2/StandardV2 support up to 10 units; PremiumV2 supports up to 30. |
| <!-- parameter env:APIM_GATEWAY_SUBSCRIPTION_ID -->`APIM_GATEWAY_SUBSCRIPTION_ID` | `apimGatewaySubscriptionId` | O | `""` | Empty uses the GitHub Environment AZURE_SUBSCRIPTION_ID. |
| <!-- parameter env:CLEAN_FOUNDRY_CAPHOST -->`CLEAN_FOUNDRY_CAPHOST` | `cleanFoundryCaphost` | O | `"true"` | Clean Foundry capability hosts before redeployment otherwise: true, deletes capability hosts before redeployment (useful when switching caphost configuration). |
| <!-- parameter env:DATABRICKS_OID -->`DATABRICKS_OID` | `databricksOID` | C | `"<todo>"` | Databricks object ID mandatory: if ENABLE_DATABRICKS:'true' ensure: find Databricks object ID in Entra ID. |
| <!-- parameter env:DATABRICKS_PRIVATE -->`DATABRICKS_PRIVATE` | `databricksPrivate` | O | `"true"` | Databricks private control plane otherwise: false, only data plane is private; control plane is public. |
| <!-- parameter env:DISABLE_WHITELISTING_FOR_BUILD_AGENTS -->`DISABLE_WHITELISTING_FOR_BUILD_AGENTS` | `disable_whitelisting_for_build_agents` | O | `"false"` | Disable runner IP whitelisting otherwise: true, skip whitelisting (use only if runner already has network access). |
| <!-- parameter env:ELASTIC_COMPANY_NAME -->`ELASTIC_COMPANY_NAME` | `elasticCompanyName` | C | `"Organization"` | Elastic Cloud company name mandatory: if ENABLE_ELASTICSEARCH:'true' |
| <!-- parameter env:ELASTIC_DEPLOYMENT_SIZE -->`ELASTIC_DEPLOYMENT_SIZE` | `elasticDeploymentSize` | O | `"small"` | Elasticsearch deployment size otherwise: medium or large. |
| <!-- parameter env:ELASTIC_EMAIL -->`ELASTIC_EMAIL` | `elasticEmail` | C | `"admin@example.com"` | Elastic Cloud account email mandatory: if ENABLE_ELASTICSEARCH:'true' ensure: valid email address. |
| <!-- parameter env:ELASTIC_FIRST_NAME -->`ELASTIC_FIRST_NAME` | `elasticFirstName` | C | `"AI"` | Elastic Cloud contact first name mandatory: if ENABLE_ELASTICSEARCH:'true' |
| <!-- parameter env:ELASTIC_LAST_NAME -->`ELASTIC_LAST_NAME` | `elasticLastName` | C | `"Factory"` | Elastic Cloud contact last name mandatory: if ENABLE_ELASTICSEARCH:'true' |
| <!-- parameter env:ELASTIC_SKU -->`ELASTIC_SKU` | `elasticSku`, `skuElasticDev`, `skuElasticStageProd` | O | `"ess-consumption-2024_Monthly"` | Elastic Cloud SKU |
| <!-- parameter env:ELASTIC_TYPE -->`ELASTIC_TYPE` | `elasticType` | O | `"ElasticCloud"` | Elasticsearch deployment type otherwise: SelfManagedOnAKS (future support). |
| <!-- parameter env:ENABLE_ADMIN_VM -->`ENABLE_ADMIN_VM` | `enableAdminVM` | O | `"false"` | Enable Admin VM in common RG |
| <!-- parameter env:ENABLE_AIFACTORY_CREATED_DEFAULT_PROJECT_FOR_AIFV2 -->`ENABLE_AIFACTORY_CREATED_DEFAULT_PROJECT_FOR_AIFV2` | `enableAIFactoryCreatedDefaultProjectForAIFv2` | O | `"true"` | AI Factory default project for AIFv2 |
| <!-- parameter env:ENABLE_AI_DOC_INTELLIGENCE -->`ENABLE_AI_DOC_INTELLIGENCE` | `enableAIDocIntelligence` | O | `"false"` | Enable Azure AI Document Intelligence |
| <!-- parameter env:ENABLE_AI_FACTORY_HUB -->`ENABLE_AI_FACTORY_HUB` | `enableAIFactoryHub` | O | `"false"` | Own AI Factory Hub intent |
| <!-- parameter env:ENABLE_AI_FOUNDRY -->`ENABLE_AI_FOUNDRY` | `enableAIFoundry` | C | `"true"` | Enable AI Foundry mandatory: Enable AI Foundry recommended: enterprise-grade private networking, BYOvNet. Required together for the standard private-agent capability-host architecture; not universal across all deployment paths. |
| <!-- parameter env:ENABLE_AI_FOUNDRY_HUB -->`ENABLE_AI_FOUNDRY_HUB` | `enableAIFoundryHub` | O | `"false"` | DEPRECATED: Legacy AI Foundry Hub v1 keep-as-is: Legacy Hub (v1). Use ENABLE_AI_FOUNDRY instead. |
| <!-- parameter env:ENABLE_AI_SEARCH -->`ENABLE_AI_SEARCH` | `enableAISearch` | C | `"true"` | Required capability-host vector store for private Foundry standard agents. mandatory: Required capability-host vector store for private Foundry standard agents. Required together for the standard private-agent capability-host architecture; not universal across all deployment paths. |
| <!-- parameter env:ENABLE_AI_SEARCH_SHARED_PRIVATE_LINK -->`ENABLE_AI_SEARCH_SHARED_PRIVATE_LINK` | `enableAISearchSharedPrivateLink` | O | `"true"` | Enable AI Search shared private link |
| <!-- parameter env:ENABLE_AI_SERVICES -->`ENABLE_AI_SERVICES` | `enableAIServices` | O | `"false"` | DEPRECATED: Standalone AI Services account keep-as-is: Replaced by ENABLE_AI_FOUNDRY. Requires ENABLE_AI_SERVICES:'true' for legacy Hub v1. |
| <!-- parameter env:ENABLE_AKS -->`ENABLE_AKS` | `enableAKS` | O | `"false"` | Deploy standalone AKS cluster keep-as-is: Independent of Azure ML, for general container workloads. |
| <!-- parameter env:ENABLE_AMPLS -->`ENABLE_AMPLS` | `enableAMPLS` | O | `"false"` | Enable AMPLS in Hub otherwise: true, AMPLS created in Hub subscription; AppInsights in private/private mode. |
| <!-- parameter env:ENABLE_APIM -->`ENABLE_APIM` | `ENABLE_APIM` | O | `"false"` | Enable apim. |
| <!-- parameter env:ENABLE_APPINSIGHTS_DASHBOARD -->`ENABLE_APPINSIGHTS_DASHBOARD` | `enableAppInsightsDashboard` | O | `"false"` | Enable Application Insights dashboard |
| <!-- parameter env:ENABLE_APPLICATION_INSIGHTS -->`ENABLE_APPLICATION_INSIGHTS` | `enableApplicationInsights` | O | `"true"` | Workspace-based project Application Insights |
| <!-- parameter env:ENABLE_AZURE_AI_VISION -->`ENABLE_AZURE_AI_VISION` | `enableAzureAIVision` | O | `"false"` | Enable Azure AI Vision |
| <!-- parameter env:ENABLE_AZURE_MACHINE_LEARNING -->`ENABLE_AZURE_MACHINE_LEARNING` | `enableAzureMachineLearning` | O | `"false"` | Enable Azure Machine Learning |
| <!-- parameter env:ENABLE_AZURE_OPENAI -->`ENABLE_AZURE_OPENAI` | `enableAzureOpenAI` | O | `"false"` | Enable Azure OpenAI standalone account otherwise: true, deploy a standalone Azure OpenAI resource (separate from AI Foundry). |
| <!-- parameter env:ENABLE_AZURE_SPEECH -->`ENABLE_AZURE_SPEECH` | `enableAzureSpeech` | O | `"false"` | Enable Azure AI Speech |
| <!-- parameter env:ENABLE_BING -->`ENABLE_BING` | `enableBing` | O | `"false"` | Enable Bing Search |
| <!-- parameter env:ENABLE_BING_CUSTOM_SEARCH -->`ENABLE_BING_CUSTOM_SEARCH` | `enableBingCustomSearch` | O | `"false"` | Enable Bing Custom Search |
| <!-- parameter env:ENABLE_BOT_SERVICE -->`ENABLE_BOT_SERVICE` | `enableBotService` | O | `"true"` | Enable Azure Bot Service |
| <!-- parameter env:ENABLE_CONTAINER_APPS -->`ENABLE_CONTAINER_APPS` | `enableContainerApps` | O | `"false"` | Enable Azure Container Apps |
| <!-- parameter env:ENABLE_CONTENT_SAFETY -->`ENABLE_CONTENT_SAFETY` | `enableContentSafety` | O | `"false"` | Enable Azure AI Content Safety |
| <!-- parameter env:ENABLE_COSMOS_DB -->`ENABLE_COSMOS_DB` | `enableCosmosDB` | C | `"true"` | Required capability-host thread and agent-history store for private Foundry standard agents. mandatory: Required capability-host thread and agent-history store for private Foundry standard agents. Required together for the standard private-agent capability-host architecture; not universal across all deployment paths. |
| <!-- parameter env:ENABLE_DATABRICKS -->`ENABLE_DATABRICKS` | `enableDatabricks` | O | `"false"` | Enable Azure Databricks |
| <!-- parameter env:ENABLE_DATAFACTORY -->`ENABLE_DATAFACTORY` | `enableDatafactory` | O | `"false"` | Enable Azure Data Factory |
| <!-- parameter env:ENABLE_DATAFACTORY_COMMON -->`ENABLE_DATAFACTORY_COMMON` | `enableDatafactoryCommon` | O | `"false"` | Enable Data Factory in common RG |
| <!-- parameter env:ENABLE_DEFENDER_FOR_AI_RESOURCE_LEVEL -->`ENABLE_DEFENDER_FOR_AI_RESOURCE_LEVEL` | `enableDefenderforAIResourceLevel` | O | `"false"` | Defender for AI at resource level keep-as-is: Per-resource Microsoft Defender for AI protection. |
| <!-- parameter env:ENABLE_DEFENDER_FOR_AI_SUB_LEVEL -->`ENABLE_DEFENDER_FOR_AI_SUB_LEVEL` | `enableDefenderforAISubLevel` | O | `"false"` | Defender for AI at subscription level keep-as-is: Subscription-level Microsoft Defender for AI protection. |
| <!-- parameter env:ENABLE_DELETE_FOR_DISABLED_RESOURCES -->`ENABLE_DELETE_FOR_DISABLED_RESOURCES` | `enableDeleteForDisabledResources` | O | `"false"` | Delete disabled services keep-as-is: true, delete resources that exist but are disabled (ENABLE_* flag = false). otherwise: false, keep all existing resources. |
| <!-- parameter env:ENABLE_ELASTICSEARCH -->`ENABLE_ELASTICSEARCH` | `enableElasticsearch` | O | `"false"` | Enable Elasticsearch (Elastic Cloud) |
| <!-- parameter env:ENABLE_EVENT_HUBS -->`ENABLE_EVENT_HUBS` | `enableEventHubs` | O | `"false"` | Enable Azure Event Hubs |
| <!-- parameter env:ENABLE_FOUNDRY_CAPHOST -->`ENABLE_FOUNDRY_CAPHOST` | `enableAFoundryCaphost` | C | `"true"` | Required for this private Foundry standard-agent architecture. Cannot be disabled; binds Cosmos DB, AI Search, and project Storage. mandatory: Required for this private Foundry standard-agent architecture. Cannot be disabled; binds Cosmos DB, AI Search, and project Storage. Required together for the standard private-agent capability-host architecture; not universal across all deployment paths. |
| <!-- parameter env:ENABLE_FUNCTION -->`ENABLE_FUNCTION` | `enableFunction` | O | `"false"` | Enable Azure Functions |
| <!-- parameter env:ENABLE_KONG -->`ENABLE_KONG` | `ENABLE_KONG` | O | `"false"` | Enable kong. |
| <!-- parameter env:ENABLE_LOGIC_APPS -->`ENABLE_LOGIC_APPS` | `enableLogicApps` | O | `"false"` | Enable Azure Logic Apps |
| <!-- parameter env:ENABLE_POSTGRESQL -->`ENABLE_POSTGRESQL` | `enablePostgreSQL` | O | `"false"` | Enable Azure PostgreSQL Flexible Server |
| <!-- parameter env:ENABLE_REDIS_CACHE -->`ENABLE_REDIS_CACHE` | `enableRedisCache` | O | `"false"` | Enable Azure Cache for Redis |
| <!-- parameter env:ENABLE_RETRIES -->`ENABLE_RETRIES` | `enableRetries` | O | `"false"` | Enable automatic job retries otherwise: true, enables retry logic for GenAI services deployment. |
| <!-- parameter env:ENABLE_SQL_DATABASE -->`ENABLE_SQL_DATABASE` | `enableSQLDatabase` | O | `"false"` | Enable Azure SQL Database |
| <!-- parameter env:ENABLE_WEBAPP -->`ENABLE_WEBAPP` | `enableWebApp` | O | `"false"` | Enable Azure Web App |
| <!-- parameter env:FOUNDRY_API_MANAGEMENT_RESOURCE_ID -->`FOUNDRY_API_MANAGEMENT_RESOURCE_ID` | `foundryApiManagementResourceId` | O | `""` | Existing APIM resource ID for AI Foundry integration keep-as-is: Leave empty for no APIM integration. otherwise: provide full resourceId of existing API Management instance. |
| <!-- parameter env:FOUNDRY_DEPLOYMENT_TYPE -->`FOUNDRY_DEPLOYMENT_TYPE` | `foundryDeploymentType` | O | `"2"` | &lt;deprecated&gt;Retained for configuration compatibility. AI Foundry always uses the second-option account deployment. |
| <!-- parameter env:KONG_CONSUMER_API_KEY -->`KONG_CONSUMER_API_KEY` | No verified counterpart | C | `""` | Stored as an environment secret, never a variable. Required by the separate AI gateway workflow when Kong is enabled; the consumer API key is an environment secret. |
| <!-- parameter env:KONG_GATEWAY_APIM_HOST -->`KONG_GATEWAY_APIM_HOST` | `kongGatewayApimHost` | C | `""` | Kong gateway apim host. Required by the separate AI gateway workflow when Kong is enabled; the consumer API key is an environment secret. |
| <!-- parameter env:KONG_GATEWAY_CPU -->`KONG_GATEWAY_CPU` | `kongGatewayCpu` | O | `"2"` | Kong gateway cpu. |
| <!-- parameter env:KONG_GATEWAY_IMAGE -->`KONG_GATEWAY_IMAGE` | `kongGatewayImage` | O | `"kong/kong-gateway:3.9"` | Kong gateway image. |
| <!-- parameter env:KONG_GATEWAY_MEMORY_GB -->`KONG_GATEWAY_MEMORY_GB` | `kongGatewayMemoryGb` | O | `"4"` | Kong gateway memory gb. |
| <!-- parameter env:SERVICE_SETTING_DEPLOY_PROJECT_VM -->`SERVICE_SETTING_DEPLOY_PROJECT_VM` | `serviceSettingDeployProjectVM` | O | `"false"` | Deploy VM in project resource group otherwise: true, deploy a jumpbox VM for use with Azure Bastion. |
| <!-- parameter env:UPDATE_AI_FOUNDRY -->`UPDATE_AI_FOUNDRY` | `updateAIFoundry` | O | `"false"` | Update AI Foundry properties otherwise: true, update existing Foundry properties and RBAC. |

### GHA: Networking, DNS and existing resources

| Exact environment key | YAML / JSON counterpart(s) | M/C/O | Template value | Description / conditions |
|---|---|---|---|---|
| <!-- parameter env:ACR_IP_WHITELIST -->`ACR_IP_WHITELIST` | `acr_IP_whitelist` | O | `""` | ACR IP allowlist for selected networks keep-as-is: comma-separated approved IPv4 addresses/ranges for ACR. |
| <!-- parameter env:ALLOW_PUBLIC_ACCESS_WHEN_BEHINDVNET -->`ALLOW_PUBLIC_ACCESS_WHEN_BEHINDVNET` | No verified counterpart | O | `"true"` | Public UI access when behind vNet recommended: false to enable fully private networking. |
| <!-- parameter env:BYO_ASEV3 -->`BYO_ASEV3` | `byoASEv3` | O | `"false"` | Bring your own ASEv3 otherwise: true, use a pre-existing App Service Environment v3. |
| <!-- parameter env:BYO_ASE_APP_SERVICE_PLAN_RESOURCE_ID -->`BYO_ASE_APP_SERVICE_PLAN_RESOURCE_ID` | `byoAseAppServicePlanResourceId` | C | `""` | BYO App Service Plan resource ID mandatory: if BYO_ASEV3:'true' and re-using an existing App Service Plan. |
| <!-- parameter env:BYO_ASE_FULL_RESOURCE_ID -->`BYO_ASE_FULL_RESOURCE_ID` | `byoAseFullResourceId` | C | `"/subscriptions/...<todo><todo_if_BYO_ASEV3_is_true>yourASEnameS2"` | BYO ASEv3 full resource ID mandatory: if BYO_ASEV3:'true' ensure: full resource ID of the existing ASEv3. |
| <!-- parameter env:BYO_CONTRIBUTOR_ROLE_ID -->`BYO_CONTRIBUTOR_ROLE_ID` | `BYOContributorRoleID` | O | `"b24988ac-6180-42a0-ab88-20f7382dd24c"` | Contributor role ID keep-as-is: Built-in Contributor role ID. otherwise: provide a custom role ID for finer-grained access control. |
| <!-- parameter env:BYO_SUBNETS -->`BYO_SUBNETS` | `BYO_subnets` | O | `"false"` | Bring your own subnets otherwise: true, uses pre-existing subnets defined by the BYO subnet variables below. |
| <!-- parameter env:CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB -->`CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB` | `centralDnsZoneByPolicyInHub` | O | `"false"` | Centralized DNS via Hub policy otherwise: true, uses central private DNS zones in HUB resource group managed by Azure Policy. |
| <!-- parameter env:COMMON_BASTION_SUBNET_CIDR -->`COMMON_BASTION_SUBNET_CIDR` | `common_bastion_subnet_cidr` | O | `"172.16.XX.192/26"` | Bastion subnet CIDR template |
| <!-- parameter env:COMMON_BASTION_SUBNET_NAME -->`COMMON_BASTION_SUBNET_NAME` | `common_bastion_subnet_name` | O | `"AzureBastionSubnet"` | Bastion subnet name keep-as-is: Must be exactly 'AzureBastionSubnet'. |
| <!-- parameter env:COMMON_PBI_SUBNET_CIDR -->`COMMON_PBI_SUBNET_CIDR` | `common_pbi_subnet_cidr` | O | `"172.16.XX.128/26"` | Power BI subnet CIDR template |
| <!-- parameter env:COMMON_PBI_SUBNET_NAME -->`COMMON_PBI_SUBNET_NAME` | `common_pbi_subnet_name` | O | `"snet-esml-cmn-pbi-001"` | Power BI subnet name |
| <!-- parameter env:COMMON_SUBNET_CIDR -->`COMMON_SUBNET_CIDR` | `common_subnet_cidr` | O | `"172.16.XX.0/26"` | Common subnet CIDR template keep-as-is: XX is replaced by the environment CIDR range value. |
| <!-- parameter env:COMMON_SUBNET_SCORING_CIDR -->`COMMON_SUBNET_SCORING_CIDR` | `common_subnet_scoring_cidr` | O | `"172.16.XX.64/26"` | Common scoring subnet CIDR template |
| <!-- parameter env:COMMON_VNET_CIDR -->`COMMON_VNET_CIDR` | `common_vnet_cidr` | O | `"172.16.XX.0/18"` | Common vNet CIDR keep-as-is: XX must be network-aligned; environments must not overlap. Address intent only, not actual peering. |
| <!-- parameter env:DEV_CIDR_RANGE -->`DEV_CIDR_RANGE` | `dev_cidr_range` | M | `"0"` | DEV network-aligned XX value mandatory: DEV network-aligned XX value keep-as-is: VNet 172.16.0.0/18. |
| <!-- parameter env:DEV_NETWORK_ENV -->`DEV_NETWORK_ENV` | `network_env_dev` | O | `"dev-"` | DEV environment prefix for BYO subnets otherwise: set to empty string if not using environment-prefixed naming. |
| <!-- parameter env:DISABLE_AGENT_NETWORK_INJECTION -->`DISABLE_AGENT_NETWORK_INJECTION` | `disableAgentNetworkInjection` | O | `"false"` | Disable agent network injection otherwise: true, disables network injection. Requires Class B/C network ranges (172.16/12 or 192.168/16). |
| <!-- parameter env:DISABLE_SUBNET_JOIN_ACTION -->`DISABLE_SUBNET_JOIN_ACTION` | `disableSubnetJoinAction` | O | `"false"` | Disable VNet subnet join RBAC recommended: false, grants Network Contributor role for subnet join actions (required for APIM, Container Apps, AKS). otherwise: true, skip if subnet permissions managed externally. |
| <!-- parameter env:ENABLE_PUBLIC_ACCESS_WITH_PERIMETER -->`ENABLE_PUBLIC_ACCESS_WITH_PERIMETER` | `enablePublicAccessWithPerimeter` | O | `"true"` | Public access with network perimeter recommended: false to enable fully private networking. |
| <!-- parameter env:ENABLE_PUBLIC_GENAI_ACCESS -->`ENABLE_PUBLIC_GENAI_ACCESS` | `enablePublicGenAIAccess` | O | `"true"` | Public GenAI access (control plane) recommended: false to enable fully private networking. |
| <!-- parameter env:KONG_GATEWAY_SUBNET_CIDR -->`KONG_GATEWAY_SUBNET_CIDR` | `kongGatewaySubnetCidr` | C | `""` | Kong gateway subnet cidr. Required by the separate AI gateway workflow when Kong is enabled; the consumer API key is an environment secret. |
| <!-- parameter env:KONG_GATEWAY_SUBNET_NAME -->`KONG_GATEWAY_SUBNET_NAME` | `kongGatewaySubnetName` | O | `"snet-kong-001"` | Kong gateway subnet name. |
| <!-- parameter env:KONG_GATEWAY_VNET_NAME -->`KONG_GATEWAY_VNET_NAME` | `kongGatewayVnetName` | C | `""` | Kong gateway vnet name. Required by the separate AI gateway workflow when Kong is enabled; the consumer API key is an environment secret. |
| <!-- parameter env:KONG_GATEWAY_VNET_RESOURCE_GROUP -->`KONG_GATEWAY_VNET_RESOURCE_GROUP` | `kongGatewayVnetResourceGroup` | C | `""` | Kong gateway vnet resource group. Required by the separate AI gateway workflow when Kong is enabled; the consumer API key is an environment secret. |
| <!-- parameter env:PRIV_DNS_RESOURCE_GROUP_PARAM -->`PRIV_DNS_RESOURCE_GROUP_PARAM` | `privDnsResourceGroup_param` | C | `"<todo>"` | Hub DNS resource group mandatory: if CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB:'true' ensure: Hub connectivity resource group. |
| <!-- parameter env:PRIV_DNS_SUBSCRIPTION_PARAM -->`PRIV_DNS_SUBSCRIPTION_PARAM` | `privDnsSubscription_param` | C | `"<todo>"` | Hub DNS subscription ID mandatory: if CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB:'true' ensure: Hub connectivity subscription ID. |
| <!-- parameter env:PROD_CIDR_RANGE -->`PROD_CIDR_RANGE` | `prod_cidr_range` | M | `"128"` | PROD network-aligned XX value mandatory: PROD network-aligned XX value keep-as-is: VNet 172.16.128.0/18. |
| <!-- parameter env:PROD_NETWORK_ENV -->`PROD_NETWORK_ENV` | `network_env_prod` | O | `"prod-"` | PROD environment prefix for BYO subnets otherwise: 'pr-', or empty string. |
| <!-- parameter env:PROJECT_MEMBERS_IP_ADDRESS -->`PROJECT_MEMBERS_IP_ADDRESS` | `project_IP_whitelist` | C | `"-"` | Project UI IP allowlist mandatory: if using IP-whitelisting networking mode ensure: comma-separated IPv4 addresses without spaces. |
| <!-- parameter env:RUN_JOB1_NETWORKING -->`RUN_JOB1_NETWORKING` | `runNetworkingVar` | M | `"true"` | Run networking module mandatory: Run networking module keep-as-is: true when creating or updating a project. otherwise: false, to skip networking on service-only updates. |
| <!-- parameter env:SCALING_MODE -->`SCALING_MODE` | `scaling-mode` | O | `"shared-subscriptions"` | Address-planning preset: own-subscriptions or shared-subscriptions; no subscription provisioning, network resizing, or peering. |
| <!-- parameter env:STAGE_CIDR_RANGE -->`STAGE_CIDR_RANGE` | `test_cidr_range` | M | `"64"` | STAGE network-aligned XX value mandatory: STAGE network-aligned XX value keep-as-is: VNet 172.16.64.0/18. |
| <!-- parameter env:STAGE_NETWORK_ENV -->`STAGE_NETWORK_ENV` | `network_env_stage` | O | `"stage-"` | STAGE environment prefix for BYO subnets otherwise: 'tst-', 'test-', or empty string. |
| <!-- parameter env:SUBNET_COMMON -->`SUBNET_COMMON` | `subnetCommon` | C | `""` | BYO common subnet name mandatory: if BYO_SUBNETS:'true' |
| <!-- parameter env:SUBNET_COMMON_BASE -->`SUBNET_COMMON_BASE` | `common_subnet_name` | O | `"snet-esml-cmn-001"` | Common subnet base name |
| <!-- parameter env:SUBNET_COMMON_POWERBI_GW -->`SUBNET_COMMON_POWERBI_GW` | `subnetCommonPowerbiGw` | O | `""` | BYO Power BI gateway subnet name |
| <!-- parameter env:SUBNET_COMMON_SCORING -->`SUBNET_COMMON_SCORING` | `subnetCommonScoring` | C | `""` | BYO common scoring subnet name mandatory: if BYO_SUBNETS:'true' |
| <!-- parameter env:SUBNET_PROJ_ACA -->`SUBNET_PROJ_ACA` | `subnetProjACA` | C | `""` | BYO Container Apps project subnet name mandatory: if ENABLE_CONTAINER_APPS:'true' and BYO_SUBNETS:'true' |
| <!-- parameter env:SUBNET_PROJ_ACA2 -->`SUBNET_PROJ_ACA2` | `subnetProjACA2` | O | `""` | BYO Container Apps secondary project subnet name |
| <!-- parameter env:SUBNET_PROJ_AKS -->`SUBNET_PROJ_AKS` | `subnetProjAKS` | C | `""` | BYO AKS project subnet name mandatory: if ENABLE_AKS_FOR_AZURE_ML:'true' and BYO_SUBNETS:'true' |
| <!-- parameter env:SUBNET_PROJ_AKS2 -->`SUBNET_PROJ_AKS2` | `subnetProjAKS2` | O | `""` | BYO AKS secondary project subnet name |
| <!-- parameter env:SUBNET_PROJ_DATABRICKS_PRIVATE -->`SUBNET_PROJ_DATABRICKS_PRIVATE` | `subnetProjDatabricksPrivate` | C | `""` | BYO Databricks private subnet name mandatory: if ENABLE_DATABRICKS:'true' and BYO_SUBNETS:'true' |
| <!-- parameter env:SUBNET_PROJ_DATABRICKS_PUBLIC -->`SUBNET_PROJ_DATABRICKS_PUBLIC` | `subnetProjDatabricksPublic` | C | `""` | BYO Databricks public subnet name mandatory: if ENABLE_DATABRICKS:'true' and BYO_SUBNETS:'true' |
| <!-- parameter env:SUBNET_PROJ_GENAI -->`SUBNET_PROJ_GENAI` | `subnetProjGenAI` | C | `""` | BYO GenAI project subnet name mandatory: if BYO_SUBNETS:'true' |
| <!-- parameter env:SUBNET_PROJ_WEBAPP -->`SUBNET_PROJ_WEBAPP` | `subnetProjWebapp` | C | `""` | BYO App Service/Function VNet-integration project subnet name mandatory: if (ENABLE_WEB_APP:'true' OR ENABLE_FUNCTION:'true') and BYO_SUBNETS:'true' |
| <!-- parameter env:VNET_NAME_BASE -->`VNET_NAME_BASE` | `vnetNameBase` | O | `"vnt-esmlcmn"` | Common vNet base name keep-as-is: Base name of the common virtual network. |
| <!-- parameter env:VNET_NAME_FULL_PARAM -->`VNET_NAME_FULL_PARAM` | `vnetNameFull_param` | C | `""` | BYO vNet full name mandatory: if BYO_SUBNETS:'true' ensure: full name of the existing virtual network. |
| <!-- parameter env:VNET_RESOURCE_GROUP_BASE -->`VNET_RESOURCE_GROUP_BASE` | `vnetResourceGroupBase` | O | `"esml-common"` | Common vNet resource group base name keep-as-is: Base name of the common vNet's resource group (used when not BYOvNet). |
| <!-- parameter env:VNET_RESOURCE_GROUP_PARAM -->`VNET_RESOURCE_GROUP_PARAM` | `vnetResourceGroup_param` | C | `""` | BYO vNet resource group mandatory: if BYO_SUBNETS:'true' ensure: resource group of the existing vNet. |

### GHA: Per-environment SKUs and compute sizing

| Exact environment key | YAML / JSON counterpart(s) | M/C/O | Template value | Description / conditions |
|---|---|---|---|---|
| <!-- parameter env:ADMIN_AKS_GPU_SKU_DEV_OVERRIDE -->`ADMIN_AKS_GPU_SKU_DEV_OVERRIDE` | `admin_aks_gpu_sku_dev_override` | O | `"Standard_D4s_v5"` | AKS system node VM SKU for DEV ensure: use an AKS-supported system-pool SKU; configure GPU workloads in a separate user pool. |
| <!-- parameter env:ADMIN_AKS_GPU_SKU_TEST_PROD_OVERRIDE -->`ADMIN_AKS_GPU_SKU_TEST_PROD_OVERRIDE` | `admin_aks_gpu_sku_test_prod_override` | O | `"Standard_DS13-2_v2"` | AKS GPU SKU for TEST/PROD |
| <!-- parameter env:ADMIN_AKS_NODES_DEV_OVERRIDE -->`ADMIN_AKS_NODES_DEV_OVERRIDE` | `admin_aks_nodes_dev_override` | O | `"2"` | AKS system node count for DEV |
| <!-- parameter env:ADMIN_AKS_NODES_TEST_PROD_OVERRIDE -->`ADMIN_AKS_NODES_TEST_PROD_OVERRIDE` | `admin_aks_nodes_testProd_override` | O | `"3"` | AKS node count for TEST/PROD |
| <!-- parameter env:ADMIN_AKS_VERSION_OVERRIDE -->`ADMIN_AKS_VERSION_OVERRIDE` | `admin_aks_version_override` | O | `"1.35.7"` | AKS Kubernetes version ensure: version has standard support in your region. |
| <!-- parameter env:ADMIN_AML_CLUSTER_MAX_NODES_DEV_OVERRIDE -->`ADMIN_AML_CLUSTER_MAX_NODES_DEV_OVERRIDE` | `admin_aml_cluster_maxNodes_dev_override` | O | `"3"` | AML cluster max nodes for DEV |
| <!-- parameter env:ADMIN_AML_CLUSTER_MAX_NODES_TEST_PROD_OVERRIDE -->`ADMIN_AML_CLUSTER_MAX_NODES_TEST_PROD_OVERRIDE` | `admin_aml_cluster_maxNodes_testProd_override` | O | `"5"` | AML cluster max nodes for TEST/PROD |
| <!-- parameter env:ADMIN_AML_CLUSTER_SKU_DEV_OVERRIDE -->`ADMIN_AML_CLUSTER_SKU_DEV_OVERRIDE` | `admin_aml_cluster_sku_dev_override` | O | `"Standard_DS3_v2"` | AML cluster VM SKU for DEV |
| <!-- parameter env:ADMIN_AML_CLUSTER_SKU_TEST_PROD_OVERRIDE -->`ADMIN_AML_CLUSTER_SKU_TEST_PROD_OVERRIDE` | `admin_aml_cluster_sku_testProd_override` | O | `"Standard_D13_v2"` | AML cluster VM SKU for TEST/PROD |
| <!-- parameter env:ADMIN_AML_COMPUTE_INSTANCE_DEV_SKU_OVERRIDE -->`ADMIN_AML_COMPUTE_INSTANCE_DEV_SKU_OVERRIDE` | `admin_aml_computeInstance_dev_sku_override` | O | `"Standard_DS11_v2"` | AML compute instance SKU for DEV |
| <!-- parameter env:ADMIN_AML_COMPUTE_INSTANCE_TEST_PROD_SKU_OVERRIDE -->`ADMIN_AML_COMPUTE_INSTANCE_TEST_PROD_SKU_OVERRIDE` | `admin_aml_computeInstance_testProd_sku_override` | O | `"Standard_ND96amsr_A100_v4"` | AML compute instance SKU for TEST/PROD |
| <!-- parameter env:ADMIN_VM_SIZE -->`ADMIN_VM_SIZE` | `adminVMSize` | O | `"Standard_D2s_v5"` | Admin VM size keep-as-is: Override when the regional SKU is unavailable. |
| <!-- parameter env:AKS_AZURE_FIREWALL_PRIVATE_IP -->`AKS_AZURE_FIREWALL_PRIVATE_IP` | `aksAzureFirewallPrivateIp` | C | `""` | Azure Firewall private IP for AKS mandatory: if AKS_OUTBOUND_TYPE:'userDefinedRouting' |
| <!-- parameter env:AKS_ENABLE_PRIVATE_CLUSTER -->`AKS_ENABLE_PRIVATE_CLUSTER` | `aksEnablePrivateCluster` | O | `"true"` | Enable private AKS cluster |
| <!-- parameter env:AKS_OUTBOUND_TYPE -->`AKS_OUTBOUND_TYPE` | `aksOutboundType` | O | `"loadBalancer"` | AKS outbound network type otherwise: userDefinedRouting for firewall/UDR scenarios. |
| <!-- parameter env:AKS_PRIVATE_DNS_ZONE -->`AKS_PRIVATE_DNS_ZONE` | `aksPrivateDNSZone` | O | `"system"` | AKS private DNS zone otherwise: none, or full resourceId of an existing private DNS zone. |
| <!-- parameter env:AKS_SKU_NAME -->`AKS_SKU_NAME` | `aksSkuName` | O | `"Base"` | AKS SKU name otherwise: Standard for production. |
| <!-- parameter env:AKS_SKU_TIER -->`AKS_SKU_TIER` | No verified counterpart | O | `"Standard"` | AKS SKU tier otherwise: Free or Premium. |
| <!-- parameter env:ENABLE_AKS_FOR_AZURE_ML -->`ENABLE_AKS_FOR_AZURE_ML` | `enableAksForAzureML` | C | `"true"` | Enable AKS for Azure ML inference mandatory: if ENABLE_AZURE_MACHINE_LEARNING:'true' |
| <!-- parameter env:SKU_AISERVICES_DEV -->`SKU_AISERVICES_DEV` | `skuAIServicesDev` | O | `"S0"` | Azure AI Services (multi-service account) SKU Dev |
| <!-- parameter env:SKU_AISERVICES_STAGEPROD -->`SKU_AISERVICES_STAGEPROD` | `skuAIServicesStageProd` | O | `"S0"` | Azure AI Services SKU Stage/Prod |
| <!-- parameter env:SKU_AKS_DEV -->`SKU_AKS_DEV` | `skuAksDev` | O | `""` | AKS SKU Dev keep-as-is: Leave empty for managed/auto SKU. |
| <!-- parameter env:SKU_AKS_STAGEPROD -->`SKU_AKS_STAGEPROD` | `skuAksStageProd` | O | `""` | AKS SKU Stage/Prod |
| <!-- parameter env:SKU_AZUREML_DEV -->`SKU_AZUREML_DEV` | `skuAzureMLDev` | O | `"basic"` | Azure ML workspace SKU Dev |
| <!-- parameter env:SKU_AZUREML_STAGEPROD -->`SKU_AZUREML_STAGEPROD` | `skuAzureMLStageProd` | O | `"basic"` | Azure ML workspace SKU Stage/Prod |
| <!-- parameter env:SKU_BING_DEV -->`SKU_BING_DEV` | `skuBingDev` | O | `"G2"` | Bing Custom Search SKU Dev keep-as-is: ['G2'] |
| <!-- parameter env:SKU_BING_STAGEPROD -->`SKU_BING_STAGEPROD` | `skuBingStageProd` | O | `"G2"` | Bing Custom Search SKU Stage/Prod |
| <!-- parameter env:SKU_BOTSERVICE_DEV -->`SKU_BOTSERVICE_DEV` | `skuBotServiceDev` | O | `"S1"` | Bot Service SKU Dev keep-as-is: ['F0','S1'] |
| <!-- parameter env:SKU_BOTSERVICE_STAGEPROD -->`SKU_BOTSERVICE_STAGEPROD` | `skuBotServiceStageProd` | O | `"S1"` | Bot Service SKU Stage/Prod |
| <!-- parameter env:SKU_CONTENTSAFETY_DEV -->`SKU_CONTENTSAFETY_DEV` | `skuContentSafetyDev` | O | `"S0"` | Content Safety SKU Dev |
| <!-- parameter env:SKU_CONTENTSAFETY_STAGEPROD -->`SKU_CONTENTSAFETY_STAGEPROD` | `skuContentSafetyStageProd` | O | `"S0"` | Content Safety SKU Stage/Prod |
| <!-- parameter env:SKU_DATABRICKS_DEV -->`SKU_DATABRICKS_DEV` | `skuDatabricksDev` | O | `"premium"` | Databricks workspace SKU Dev keep-as-is: ['standard','premium','trial'] |
| <!-- parameter env:SKU_DATABRICKS_STAGEPROD -->`SKU_DATABRICKS_STAGEPROD` | `skuDatabricksStageProd` | O | `"premium"` | Databricks workspace SKU Stage/Prod |
| <!-- parameter env:SKU_DOCINTELLIGENCE_DEV -->`SKU_DOCINTELLIGENCE_DEV` | `skuDocIntelligenceDev` | O | `"S0"` | Document Intelligence SKU Dev |
| <!-- parameter env:SKU_DOCINTELLIGENCE_STAGEPROD -->`SKU_DOCINTELLIGENCE_STAGEPROD` | `skuDocIntelligenceStageProd` | O | `"S0"` | Document Intelligence SKU Stage/Prod |
| <!-- parameter env:SKU_ELASTIC_DEV -->`SKU_ELASTIC_DEV` | `skuElasticDev` | O | `"ess-consumption-2024_Monthly"` | Elastic Cloud SKU Dev |
| <!-- parameter env:SKU_ELASTIC_STAGEPROD -->`SKU_ELASTIC_STAGEPROD` | `skuElasticStageProd` | O | `"ess-consumption-2024_Monthly"` | Elastic Cloud SKU Stage/Prod |
| <!-- parameter env:SKU_EVENTHUBS_DEV -->`SKU_EVENTHUBS_DEV` | `skuEventHubsDev` | O | `"Basic"` | Event Hubs namespace SKU Dev keep-as-is: ['Basic','Standard','Premium'] |
| <!-- parameter env:SKU_EVENTHUBS_STAGEPROD -->`SKU_EVENTHUBS_STAGEPROD` | `skuEventHubsStageProd` | O | `"Basic"` | Event Hubs namespace SKU Stage/Prod |
| <!-- parameter env:SKU_FUNCTION_DEV -->`SKU_FUNCTION_DEV` | `skuFunctionDev` | O | `"EP1"` | Function plan SKU Dev |
| <!-- parameter env:SKU_FUNCTION_STAGEPROD -->`SKU_FUNCTION_STAGEPROD` | `skuFunctionStageProd` | O | `"EP1"` | Function plan SKU Stage/Prod |
| <!-- parameter env:SKU_LOGICAPPS_DEV -->`SKU_LOGICAPPS_DEV` | `skuLogicAppsDev` | O | `"WS1"` | Logic Apps (Standard) SKU Dev |
| <!-- parameter env:SKU_LOGICAPPS_STAGEPROD -->`SKU_LOGICAPPS_STAGEPROD` | `skuLogicAppsStageProd` | O | `"WS1"` | Logic Apps (Standard) SKU Stage/Prod |
| <!-- parameter env:SKU_OPENAI_DEV -->`SKU_OPENAI_DEV` | `skuOpenAIDev` | O | `"S0"` | Azure OpenAI SKU Dev |
| <!-- parameter env:SKU_OPENAI_STAGEPROD -->`SKU_OPENAI_STAGEPROD` | `skuOpenAIStageProd` | O | `"S0"` | Azure OpenAI SKU Stage/Prod |
| <!-- parameter env:SKU_POSTGRESQL_DEV -->`SKU_POSTGRESQL_DEV` | `skuPostgreSQLDev` | O | `"Standard_B1ms"` | PostgreSQL compute SKU Dev |
| <!-- parameter env:SKU_POSTGRESQL_STAGEPROD -->`SKU_POSTGRESQL_STAGEPROD` | `skuPostgreSQLStageProd` | O | `"Standard_B1ms"` | PostgreSQL compute SKU Stage/Prod |
| <!-- parameter env:SKU_REDIS_DEV -->`SKU_REDIS_DEV` | `skuRedisDev` | O | `"Standard"` | Redis SKU Dev keep-as-is: ['Basic','Standard','Premium'] |
| <!-- parameter env:SKU_REDIS_STAGEPROD -->`SKU_REDIS_STAGEPROD` | `skuRedisStageProd` | O | `"Standard"` | Redis SKU Stage/Prod |
| <!-- parameter env:SKU_SPEECH_DEV -->`SKU_SPEECH_DEV` | `skuSpeechDev` | O | `"S0"` | Azure AI Speech SKU Dev |
| <!-- parameter env:SKU_SPEECH_STAGEPROD -->`SKU_SPEECH_STAGEPROD` | `skuSpeechStageProd` | O | `"S0"` | Azure AI Speech SKU Stage/Prod |
| <!-- parameter env:SKU_SQLDATABASE_DEV -->`SKU_SQLDATABASE_DEV` | `skuSQLDatabaseDev` | O | `"S0"` | Azure SQL DB (DTU model) SKU Dev |
| <!-- parameter env:SKU_SQLDATABASE_STAGEPROD -->`SKU_SQLDATABASE_STAGEPROD` | `skuSQLDatabaseStageProd` | O | `"S0"` | Azure SQL DB (DTU model) SKU Stage/Prod |
| <!-- parameter env:SKU_STORAGEACCOUNT_DEV -->`SKU_STORAGEACCOUNT_DEV` | `skuStorageAccountDev` | O | `"Standard_LRS"` | Project Storage Account SKU Dev keep-as-is: ['Standard_LRS','Standard_GRS','Standard_RAGRS','Standard_ZRS','Premium_LRS','Premium_ZRS','Standard_GZRS','Standard_RAGZRS'] |
| <!-- parameter env:SKU_STORAGEACCOUNT_STAGEPROD -->`SKU_STORAGEACCOUNT_STAGEPROD` | `skuStorageAccountStageProd` | O | `"Standard_LRS"` | Project Storage Account SKU Stage/Prod |
| <!-- parameter env:SKU_TIER_AKS_DEV -->`SKU_TIER_AKS_DEV` | `skuTierAksDev` | O | `"Standard"` | AKS tier Dev keep-as-is: ['Free','Standard','Premium'] |
| <!-- parameter env:SKU_TIER_AKS_STAGEPROD -->`SKU_TIER_AKS_STAGEPROD` | `skuTierAksStageProd` | O | `"Standard"` | AKS tier Stage/Prod |
| <!-- parameter env:SKU_TIER_AZUREML_DEV -->`SKU_TIER_AZUREML_DEV` | `skuTierAzureMLDev` | O | `"basic"` | Azure ML workspace tier Dev |
| <!-- parameter env:SKU_TIER_AZUREML_STAGEPROD -->`SKU_TIER_AZUREML_STAGEPROD` | `skuTierAzureMLStageProd` | O | `"basic"` | Azure ML workspace tier Stage/Prod |
| <!-- parameter env:SKU_TIER_FUNCTION_DEV -->`SKU_TIER_FUNCTION_DEV` | `skuTierFunctionDev` | O | `"ElasticPremium"` | Function plan tier Dev |
| <!-- parameter env:SKU_TIER_FUNCTION_STAGEPROD -->`SKU_TIER_FUNCTION_STAGEPROD` | `skuTierFunctionStageProd` | O | `"ElasticPremium"` | Function plan tier Stage/Prod |
| <!-- parameter env:SKU_TIER_POSTGRESQL_DEV -->`SKU_TIER_POSTGRESQL_DEV` | `skuTierPostgreSQLDev` | O | `"Burstable"` | PostgreSQL tier Dev keep-as-is: ['Burstable','GeneralPurpose','MemoryOptimized'] |
| <!-- parameter env:SKU_TIER_POSTGRESQL_STAGEPROD -->`SKU_TIER_POSTGRESQL_STAGEPROD` | `skuTierPostgreSQLStageProd` | O | `"Burstable"` | PostgreSQL tier Stage/Prod |
| <!-- parameter env:SKU_TIER_SQLDATABASE_DEV -->`SKU_TIER_SQLDATABASE_DEV` | `skuTierSQLDatabaseDev` | O | `"Standard"` | Azure SQL DB tier Dev keep-as-is: ['Basic','Standard','Premium'] |
| <!-- parameter env:SKU_TIER_SQLDATABASE_STAGEPROD -->`SKU_TIER_SQLDATABASE_STAGEPROD` | `skuTierSQLDatabaseStageProd` | O | `"Standard"` | Azure SQL DB tier Stage/Prod |
| <!-- parameter env:SKU_TIER_WEBAPP_DEV -->`SKU_TIER_WEBAPP_DEV` | `skuTierWebAppDev` | O | `"PremiumV3"` | Web App plan tier Dev |
| <!-- parameter env:SKU_TIER_WEBAPP_STAGEPROD -->`SKU_TIER_WEBAPP_STAGEPROD` | `skuTierWebAppStageProd` | O | `"PremiumV3"` | Web App plan tier Stage/Prod |
| <!-- parameter env:SKU_VISION_DEV -->`SKU_VISION_DEV` | `skuVisionDev` | O | `"S1"` | Azure AI Vision SKU Dev |
| <!-- parameter env:SKU_VISION_STAGEPROD -->`SKU_VISION_STAGEPROD` | `skuVisionStageProd` | O | `"S1"` | Azure AI Vision SKU Stage/Prod |
| <!-- parameter env:SKU_WEBAPP_DEV -->`SKU_WEBAPP_DEV` | `skuWebAppDev` | O | `"P1v3"` | Web App plan SKU Dev |
| <!-- parameter env:SKU_WEBAPP_STAGEPROD -->`SKU_WEBAPP_STAGEPROD` | `skuWebAppStageProd` | O | `"P1v3"` | Web App plan SKU Stage/Prod |

### GHA: Identity, access and encryption

| Exact environment key | YAML / JSON counterpart(s) | M/C/O | Template value | Description / conditions |
|---|---|---|---|---|
| <!-- parameter env:APIM_GATEWAY_MANAGED_IDENTITY_PRINCIPAL_ID -->`APIM_GATEWAY_MANAGED_IDENTITY_PRINCIPAL_ID` | `apimGatewayManagedIdentityPrincipalId` | C | `""` | Apim gateway managed identity principal id. Required when assigning the OpenAI user role to the APIM managed identity. |
| <!-- parameter env:AZURE_MACHINELEARNING_SP_OID -->`AZURE_MACHINELEARNING_SP_OID` | `azure_machinelearning_sp_oid` | C | `"<todo>"` | Azure ML service principal OID mandatory: Azure ML service principal OID ensure: find in Entra ID as 'Azure Machine Learning' app. otherwise: optional if ENABLE_AI_FOUNDRY:'false'. |
| <!-- parameter env:CMK -->`CMK` | `cmk` | O | `"false"` | Customer Managed Key encryption otherwise: true enables CMEK where supported. Requires KEYVAULT_SOFT_DELETE &gt; 7 days. |
| <!-- parameter env:CMK_DISABLE_FOR_AI_SEARCH -->`CMK_DISABLE_FOR_AI_SEARCH` | `cmkDisableForAISearch` | O | `"true"` | Disable CMK for AI Search otherwise: false, enables CMK encryption for AI Search even when CMK:'true'. |
| <!-- parameter env:CMK_DISABLE_FOR_FOUNDRY -->`CMK_DISABLE_FOR_FOUNDRY` | `cmkDisableForFoundry` | O | `"true"` | Disable CMK for AI Foundry otherwise: false, enables CMK encryption for AI Foundry even when CMK:'true'. |
| <!-- parameter env:CMK_KEY_NAME -->`CMK_KEY_NAME` | `cmkKeyName` | C | `"<todo>aifactory-cmk-key"` | CMK key name in seeding KV mandatory: if CMK:'true' ensure: key must exist in seeding Key Vault. |
| <!-- parameter env:CMK_KEY_VERSION -->`CMK_KEY_VERSION` | `cmkKeyVersion` | O | `""` | CMK key version keep-as-is: Leave empty to always use the latest key version. |
| <!-- parameter env:COMMON_SERVICE_PRINCIPAL_KV_S_NAME_APPID -->`COMMON_SERVICE_PRINCIPAL_KV_S_NAME_APPID` | No verified counterpart | C | `"<optional>esml-common-bicep-sp-id"` | Seeding KV secret name for common SP App ID ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter env:COMMON_SERVICE_PRINCIPAL_KV_S_NAME_SECRET -->`COMMON_SERVICE_PRINCIPAL_KV_S_NAME_SECRET` | No verified counterpart | C | `"<optional>esml-common-bicep-sp-secret"` | Seeding KV secret name for common SP secret ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter env:COMMON_SERVICE_PRINCIPLE_OID_KEY -->`COMMON_SERVICE_PRINCIPLE_OID_KEY` | `commonServicePrincipleOIDKey` | C | `"<todo>esml-common-sp-oid"` | Seeding KV secret name for common SP OID mandatory: Seeding KV secret name for common SP OID ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter env:DEBUG_DISABLE_100_RBAC_SECURITY -->`DEBUG_DISABLE_100_RBAC_SECURITY` | `debug_disable_100_rbac_security` | O | `"false"` | Disable step 100: RBAC & Security keep-as-is: RBAC assignments for steps 61-99. |
| <!-- parameter env:DISABLE_CONTRIBUTOR_ACCESS_FORUSERS -->`DISABLE_CONTRIBUTOR_ACCESS_FORUSERS` | `disableContributorAccessForUsers` | O | `"false"` | Disable Contributor for project users recommended: true, restrict direct Contributor for better governance. |
| <!-- parameter env:DISABLE_LOCAL_AUTH -->`DISABLE_LOCAL_AUTH` | `disableLocalAuth` | O | `"true"` | Disable local API key ("admin account") auth on Cognitive/AI Services & Foundry, AAD-only recommended: true, disables key auth (many orgs forbid keys). otherwise: false, allow local API keys. |
| <!-- parameter env:DISABLE_RBAC_ADMIN_ON_RG_FORUSERS -->`DISABLE_RBAC_ADMIN_ON_RG_FORUSERS` | `disableRBACAdminOnRGForUsers` | O | `"false"` | Disable RBAC Admin on RG for project users recommended: true, restrict RBAC Admin on resource group for better governance. |
| <!-- parameter env:GROUPS_CORETEAM_MEMBERS -->`GROUPS_CORETEAM_MEMBERS` | `groups_coreteam_members` | M | `"<aif001sdc_coreteam_admin_p080>,<aif001sdc_coreteam_dataops_p081>,<aif001sdc_coreteam_dataops_fabric_p082>"` | Core team Entra ID group OIDs mandatory: Core team Entra ID group OIDs ensure: 3 comma-separated AD group ObjectIDs matching personas in PERSONAS_CORE_TEAM. |
| <!-- parameter env:GROUPS_PROJECT_MEMBERS_ESML -->`GROUPS_PROJECT_MEMBERS_ESML` | `groups_project_members_esml` | M | `"<aif001sdc_prj001_team_lead_p001>,<aif001sdc_prj001_team_member_ds_p002>,<aif001sdc_prj001_team_member_fend_p003>"` | ESML project team Entra ID group OIDs mandatory: ESML project team Entra ID group OIDs ensure: 3 comma-separated AD group ObjectIDs matching personas in PERSONAS_PROJECT_ESML. |
| <!-- parameter env:GROUPS_PROJECT_MEMBERS_GENAI_1 -->`GROUPS_PROJECT_MEMBERS_GENAI_1` | `groups_project_members_genai_1` | M | `"<aif001sdc_prj002_team_lead_p011>,<aif001sdc_prj002_genai_team_member_aifoundry_p012>,<aif002sdc_prj001_genai_team_member_agentic_p013>,<aif001sdc_prj001_genai_team_member_dataops_p014>,<aif001sdc_prj001_team_member_fend_p015>"` | GenAI-1 project team Entra ID group OIDs mandatory: GenAI-1 project team Entra ID group OIDs ensure: 5 comma-separated AD group ObjectIDs matching personas in PERSONAS_PROJECT_GENAI_1. |
| <!-- parameter env:INPUT_COMMON_SPID_KEY -->`INPUT_COMMON_SPID_KEY` | `inputCommonSPIDKey` | C | `"<todo>esml-common-sp-id"` | Seeding KV secret name for common SP App ID mandatory: Seeding KV secret name for common SP App ID ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter env:INPUT_COMMON_SP_SECRET_KEY -->`INPUT_COMMON_SP_SECRET_KEY` | `inputCommonSPSecretKey` | C | `"<todo>esml-common-sp-secret"` | Seeding KV secret name for common SP secret mandatory: Seeding KV secret name for common SP secret ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter env:PERSONAS_CORE_TEAM -->`PERSONAS_CORE_TEAM` | `personas_core_team` | O | `"p080_coreteam_it_admin,coreteam_dataops,p081_coreteam_dataops_fabric, p103_coreteam_team_process_ops"` | Core team persona list keep-as-is: 4 personas (3 user, 1 SP). Mapped to GROUPS_CORETEAM_MEMBERS. |
| <!-- parameter env:PERSONAS_PROJECT_ESML -->`PERSONAS_PROJECT_ESML` | `personas_project_esml` | O | `"p001_esml_team_lead,p002_esml_team_member_datascientist,p003_esml_team_member_front_end,p101_esml_team_process_ops"` | ESML project persona list keep-as-is: 4 personas (3 user, 1 SP). Mapped to GROUPS_PROJECT_MEMBERS_ESML. |
| <!-- parameter env:PERSONAS_PROJECT_GENAI_1 -->`PERSONAS_PROJECT_GENAI_1` | `personas_project_genai_1` | O | `"p011_genai_team_lead,p012_genai_team_member_aifoundry,p013_genai_team_member_agentic,p014_genai_team_member_dataops,p015_genai_team_member_frontend,p102_esml_team_process_ops"` | GenAI-1 project persona list keep-as-is: 6 personas (5 user, 1 SP). Mapped to GROUPS_PROJECT_MEMBERS_GENAI_1. |
| <!-- parameter env:PROJECT_MEMBERS -->`PROJECT_MEMBERS` | `technical_admins_ad_object_id` | M | `"<todo>_object_id"` | Project team Entra ID object ID(s) mandatory: Project team Entra ID object ID(s) ensure: comma-separated ObjectIDs of users or AD groups (when USE_AD_GROUPS:'true'). |
| <!-- parameter env:PROJECT_MEMBERS_EMAILS -->`PROJECT_MEMBERS_EMAILS` | `technical_admins_email` | O | `"<todo>_EntraID-Security-Group-Name"` | Project team contact email or group name recommended: set for better project tracking. |
| <!-- parameter env:PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID -->`PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_APPID` | `project_service_principal_AppID_seeding_kv_name` | C | `"<optional>esml-project001-sp-id"` | Project SP App ID secret name in seeding KV ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter env:PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_OID -->`PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_OID` | `project_service_principal_OID_seeding_kv_name` | C | `"<optional>esml-project001-sp-oid"` | Project SP OID secret name in seeding KV ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter env:PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_S -->`PROJECT_SERVICE_PRINCIPAL_KV_S_NAME_S` | `project_service_principal_Secret_seeding_kv_name` | C | `"<optional>esml-project001-sp-secret"` | Project SP secret name in seeding KV ensure: name matches the secret in your Seeding Keyvault. Secret-name reference for the selected service-principal/seeding path; not a credential value. |
| <!-- parameter env:TENANT_AZUREML_OID -->`TENANT_AZUREML_OID` | `azure_machinelearning_sp_oid` | C | `"<todo>"` | Azure ML service principal OID mandatory: Azure ML service principal OID ensure: find in Entra ID as 'Azure Machine Learning' app (AppId: 0736f41a-0425-4b46-bdb5-1563eff02385). otherwise: optional if ENABLE_AI_FOUNDRY:'false'. |
| <!-- parameter env:TENANT_ID -->`TENANT_ID` | `tenantId` | M | `"<todo>"` | Azure tenant ID mandatory: Azure tenant ID ensure: find in Azure Portal &gt; Entra ID &gt; Overview (Directory ID). |
| <!-- parameter env:UPDATE_KEYVAULT_RBAC -->`UPDATE_KEYVAULT_RBAC` | `updateKeyvaultRbac` | O | `"false"` | Update Key Vault RBAC otherwise: true enables updating KV RBAC by rerunning the pipeline. |
| <!-- parameter env:USE_AD_GROUPS -->`USE_AD_GROUPS` | `use_ad_groups` | O | `"true"` | Use AD groups for project members otherwise: false, use individual ObjectIDs and simple mode Personas. |

### GHA: Operations, diagnostics and lifecycle

| Exact environment key | YAML / JSON counterpart(s) | M/C/O | Template value | Description / conditions |
|---|---|---|---|---|
| <!-- parameter env:DEBUG_DISABLE_05_BUILD_ACR_IMAGE -->`DEBUG_DISABLE_05_BUILD_ACR_IMAGE` | `debug_disable_05_build_acr_image` | O | `"false"` | Disable ACR image build step keep-as-is: Cannot be disabled if ContainerApps is enabled (requires ACR networking with runner IP allowlist). |
| <!-- parameter env:DEBUG_DISABLE_10_AIFACTORY_DASHBOARDS -->`DEBUG_DISABLE_10_AIFACTORY_DASHBOARDS` | `debug_disable_10_aifactory_dashboards` | O | `"true"` | Disable AI Factory Dashboards step |
| <!-- parameter env:DEBUG_DISABLE_61_FOUNDATION -->`DEBUG_DISABLE_61_FOUNDATION` | `debug_disable_61_foundation` | O | `"false"` | Disable step 61: Foundation keep-as-is: Resource groups, UAMIs, VMs. |
| <!-- parameter env:DEBUG_DISABLE_62_CORE_INFRASTRUCTURE -->`DEBUG_DISABLE_62_CORE_INFRASTRUCTURE` | `debug_disable_62_core_infrastructure` | O | `"false"` | Disable step 62: Core infrastructure keep-as-is: Application Insights, Key Vault, Storage, ACR. |
| <!-- parameter env:DEBUG_DISABLE_63_COGNITIVE_SERVICES -->`DEBUG_DISABLE_63_COGNITIVE_SERVICES` | `debug_disable_63_cognitive_services` | O | `"false"` | Disable step 63: Cognitive Services keep-as-is: AI Search, OpenAI Standalone, Vision, Speech. |
| <!-- parameter env:DEBUG_DISABLE_64_DATABASES -->`DEBUG_DISABLE_64_DATABASES` | `debug_disable_64_databases` | O | `"false"` | Disable step 64: Databases keep-as-is: CosmosDB, SQL Database. |
| <!-- parameter env:DEBUG_DISABLE_65_COMPUTE_SERVICES -->`DEBUG_DISABLE_65_COMPUTE_SERVICES` | `debug_disable_65_compute_services` | O | `"false"` | Disable step 65: Compute services keep-as-is: Container Apps, WebApp, FunctionApp. |
| <!-- parameter env:DEBUG_DISABLE_66_AI_PLATFORM -->`DEBUG_DISABLE_66_AI_PLATFORM` | `debug_disable_66_ai_platform` | O | `"false"` | Disable step 66: AI Platform keep-as-is: AI Foundry Hub (V1) with default project and connections. |
| <!-- parameter env:DEBUG_DISABLE_67_ML_PLATFORM -->`DEBUG_DISABLE_67_ML_PLATFORM` | `debug_disable_67_data_ml_platform` | O | `"false"` | Disable step 67: ML Platform keep-as-is: Azure Machine Learning, Datafactory, Databricks. |
| <!-- parameter env:DEBUG_DISABLE_68_INTEGRATION -->`DEBUG_DISABLE_68_INTEGRATION` | `debug_disable_68_integration` | O | `"false"` | Disable step 68: Integration keep-as-is: Logic Apps, Event Hubs. |
| <!-- parameter env:DEBUG_DISABLE_69_AIFOUNDRY_2025 -->`DEBUG_DISABLE_69_AIFOUNDRY_2025` | `debug_disable_69_aifoundry_2025` | O | `"false"` | Disable step 69: AI Foundry V2 keep-as-is: AI Foundry V2 including RBAC and default project (CosmosDB, Storage). |
| <!-- parameter env:DEBUG_DISABLE_VALIDATION_TASKS -->`DEBUG_DISABLE_VALIDATION_TASKS` | `debug_disable_validation_tasks` | O | `"false"` | Disable validation tasks otherwise: true, skip subnet, submodule, and DNS checks. |
| <!-- parameter env:DEBUG_ENABLE_CLEANING -->`DEBUG_ENABLE_CLEANING` | `debugEnableCleaning` | O | `"false"` | Enable error cleanup tasks otherwise: true, enables cleanup tasks (71-73) that delete resources on deployment failures. |
| <!-- parameter env:DELETE_ALL_FOR_PROJECT -->`DELETE_ALL_FOR_PROJECT` | `deleteAllForProject` | O | `"false"` | Delete EVERYTHING for project otherwise: true, deletes ALL resources in project RG including KV, Storage, AppInsights, and networking resources (subnets, NSGs) in common RG. Use with extreme caution! |
| <!-- parameter env:DELETE_ALL_SERVICES_FOR_PROJECT -->`DELETE_ALL_SERVICES_FOR_PROJECT` | `deleteAllServicesForProject` | O | `"false"` | Delete all project services otherwise: true, delete ALL services in the project RG (except KV, Storage, AppInsights) before redeploy. |
| <!-- parameter env:DELETE_KEYVAULT_ALSO -->`DELETE_KEYVAULT_ALSO` | `deleteKeyvaultAlso` | O | `"false"` | Also delete Key Vault when DELETE_ALL_SERVICES_FOR_PROJECT:'true' recommended: false, retains Key Vault as a safety net (secrets, CMK keys, RBAC). otherwise: true, also deletes the project Key Vault. |
| <!-- parameter env:DIAGNOSTIC_SETTING_LEVEL -->`DIAGNOSTIC_SETTING_LEVEL` | `diagnosticSettingLevel` | O | `"gold"` | Diagnostics level otherwise: silver or bronze for less verbose (lower cost) logging. |
| <!-- parameter env:POLICY_EXEMPTION_ASSIGNMENT_IDS -->`POLICY_EXEMPTION_ASSIGNMENT_IDS` | `policyExemptionAssignmentIds` | O | `"[]"` | JSON array of policy assignment IDs (deployIfNotExists or auditIfNotExists) scoped to the VNet RG keep-as-is: Prevents DINE remediation race conditions during AI Foundry Standard Agent network injection. Leave as '[]' in greenfield/non-ALZ. otherwise: e.g. '["/subscriptions/ |
| <!-- parameter env:POLICY_EXEMPTION_DEFINITION_REFERENCE_IDS -->`POLICY_EXEMPTION_DEFINITION_REFERENCE_IDS` | `policyExemptionDefinitionReferenceIds` | O | `"[]"` | JSON array of policyDefinitionReferenceIds to narrow exemption to specific DINE members within an initiative keep-as-is: Leave as '[]' to exempt the full assignment. |
| <!-- parameter env:RETRY_MINUTES -->`RETRY_MINUTES` | `retryMinutes` | O | `"5"` | Minutes between 1st and 2nd retry attempt |
| <!-- parameter env:RETRY_MINUTES_EXTENDED -->`RETRY_MINUTES_EXTENDED` | `retryMinutesExtended` | O | `"15"` | Minutes between 2nd and 3rd retry attempt |
| <!-- parameter env:SELF_HOSTED_RUNNER_LABEL -->`SELF_HOSTED_RUNNER_LABEL` | `selfHostedRunnerLabel` | O | `"aifactory-admin-vm"` | Custom label assigned to the GitHub self-hosted runner |

### GHA: Models and deployments

| Exact environment key | YAML / JSON counterpart(s) | M/C/O | Template value | Description / conditions |
|---|---|---|---|---|
| <!-- parameter env:DEFAULT_EMBEDDING_CAPACITY -->`DEFAULT_EMBEDDING_CAPACITY` | `default_embedding_capacity` | O | `"25"` | Embedding model capacity (TPM in K) |
| <!-- parameter env:DEFAULT_GPT_4O_VERSION -->`DEFAULT_GPT_4O_VERSION` | `default_gpt_4o_version` | O | `"2024-11-20"` | GPT-4o version |
| <!-- parameter env:DEFAULT_GPT_54_MINI_VERSION -->`DEFAULT_GPT_54_MINI_VERSION` | `default_gpt_54_mini_version` | O | `"2026-03-17"` | Version for the separately named GPT-5.4-mini deployment toggle. |
| <!-- parameter env:DEFAULT_GPT_CAPACITY -->`DEFAULT_GPT_CAPACITY` | `default_gpt_capacity` | O | `"40"` | GPT model capacity (TPM in K) keep-as-is: 40 = 40K tokens per minute. |
| <!-- parameter env:DEFAULT_MODEL_SKU -->`DEFAULT_MODEL_SKU` | `default_model_sku` | O | `"DataZoneStandard"` | Default model deployment SKU keep-as-is: Keep inference within the selected data zone; confirm model/SKU availability and quota. |
| <!-- parameter env:DEPLOY_MODEL_GPT_4O -->`DEPLOY_MODEL_GPT_4O` | `deployModel_gpt_4o` | O | `"false"` | Deploy GPT-4o model |
| <!-- parameter env:DEPLOY_MODEL_GPT_54_MINI -->`DEPLOY_MODEL_GPT_54_MINI` | `deployModel_gpt_54_mini` | O | `"false"` | Enable the separately named GPT-5.4-mini deployment toggle. |
| <!-- parameter env:DEPLOY_MODEL_GPT_X -->`DEPLOY_MODEL_GPT_X` | `deployModel_gpt_X` | O | `"true"` | Deploy custom GPT-X model otherwise: true, deploys the model defined in MODEL_GPTX_NAME. |
| <!-- parameter env:DEPLOY_MODEL_TEXT_EMBEDDING_3_LARGE -->`DEPLOY_MODEL_TEXT_EMBEDDING_3_LARGE` | `deployModel_text_embedding_3_large` | O | `"true"` | Deploy text-embedding-3-large |
| <!-- parameter env:DEPLOY_MODEL_TEXT_EMBEDDING_3_SMALL -->`DEPLOY_MODEL_TEXT_EMBEDDING_3_SMALL` | `deployModel_text_embedding_3_small` | O | `"false"` | Deploy text-embedding-3-small |
| <!-- parameter env:DEPLOY_MODEL_TEXT_EMBEDDING_ADA_002 -->`DEPLOY_MODEL_TEXT_EMBEDDING_ADA_002` | `deployModel_text_embedding_ada_002` | O | `"false"` | Deploy text-embedding-ada-002 |
| <!-- parameter env:MODEL_GPTX_CAPACITY -->`MODEL_GPTX_CAPACITY` | `modelGPTXCapacity` | O | `"30"` | Custom GPT-X model capacity (TPM in K) keep-as-is: 30 = 30K tokens per minute. |
| <!-- parameter env:MODEL_GPTX_NAME -->`MODEL_GPTX_NAME` | `modelGPTXName` | O | `"gpt-5.4-mini"` | Custom GPT-X model name |
| <!-- parameter env:MODEL_GPTX_SKU -->`MODEL_GPTX_SKU` | `modelGPTXSku` | O | `"DataZoneStandard"` | Custom GPT-X model SKU keep-as-is: Keep inference within the selected data zone; confirm model/SKU availability and quota. |
| <!-- parameter env:MODEL_GPTX_VERSION -->`MODEL_GPTX_VERSION` | `modelGPTXVersion` | O | `"2026-03-17"` | Custom GPT-X model version keep-as-is: Update the version when selecting a different model. |

## Shared-binding collisions

These GHA names occur against multiple YAML/JSON keys. Follow the relevant workflow/environment rather than treating this as a one-to-one rename. All source defaults remain separate above.

| GHA binding / fallback | YAML / JSON keys |
|---|---|
| `ADMIN_AISEARCH_TIER` | `admin_aiSearchTier`, `skuAISearchDev`, `skuAISearchStageProd` |
| `AIFACTORY_SEEDING_KEYVAULT_NAME` | `dev_admin_bicep_kv_fw`, `prod_admin_bicep_kv_fw`, `test_admin_bicep_kv_fw` |
| `AIFACTORY_SEEDING_KEYVAULT_RG` | `dev_admin_bicep_kv_fw_rg`, `prod_admin_bicep_kv_fw_rg`, `test_admin_bicep_kv_fw_rg` |
| `AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID` | `dev_admin_bicep_input_keyvault_subscription`, `prod_admin_bicep_input_keyvault_subscription`, `test_admin_bicep_input_keyvault_subscription` |
| `ELASTIC_SKU` | `elasticSku`, `skuElasticDev`, `skuElasticStageProd` |
| `USE_COMMON_ACR_FOR_PROJECTS` | `useCommonACR`, `useCommonACR_override` |

## Bootstrap environment inputs

Inputs are read by the create launchers, with version selectors also used by update. `M` means a value must resolve (an authenticated-context default may supply it); `C` means route/mode-specific; `O` means a default or optional override. `$...` defaults below are **literal source expressions**, not values discovered on this machine. Blank means no literal default at that point. Prompts, simple-mode fixed values, and validation can narrow them further.

| Input | M/C/O | Source default / expression | Description |
|---|---|---|---|
| <!-- parameter bootstrap:ADO_AGENT_POOL -->`ADO_AGENT_POOL` | C | `"Default"` | Azure DevOps agent pool |
| <!-- parameter bootstrap:ADO_AUTH_METHOD -->`ADO_AUTH_METHOD` | C | `"aad"` | Azure DevOps authentication: Microsoft Entra (aad) or PAT (pat); allowed: aad pat |
| <!-- parameter bootstrap:ADO_BRANCH -->`ADO_BRANCH` | C | `"main"` | ADO update branch; reviewed project dispatch requires main. |
| <!-- parameter bootstrap:ADO_ORGANIZATION -->`ADO_ORGANIZATION` | C | `""` | Azure DevOps organization name or URL |
| <!-- parameter bootstrap:ADO_PIPELINE_NAME -->`ADO_PIPELINE_NAME` | C | `"infra-project-genai"` | ADO legacy update pipeline name. |
| <!-- parameter bootstrap:ADO_PROJECT -->`ADO_PROJECT` | C | `""` | Azure DevOps project name |
| <!-- parameter bootstrap:ADO_REPOSITORY_NAME -->`ADO_REPOSITORY_NAME` | C | `"${AIF_PREFIX%-}aifactory-${AIF_SCALESET_SUFFIX}"` | Azure DevOps repository name |
| <!-- parameter bootstrap:ADO_RUNNER_MODE -->`ADO_RUNNER_MODE` | C | `"h"` | Project build agent: self-hosted admin VM (s) or Microsoft-hosted (h); allowed: s h |
| <!-- parameter bootstrap:ADO_RUNNER_SELECTION -->`ADO_RUNNER_SELECTION` | C | `"from-config"` | ADO legacy update runner selection. |
| <!-- parameter bootstrap:ADO_SERVICE_CONNECTION_NAME -->`ADO_SERVICE_CONNECTION_NAME` | C | `"sc-${AIF_PREFIX%-}dev-${AIF_SCALESET_SUFFIX}"` | Azure DevOps service connection name |
| <!-- parameter bootstrap:ADO_SETTINGS_FILE -->`ADO_SETTINGS_FILE` | C | `"$HOME/.aifactory-ado-settings.json"` | ADO saved organization/project context path; generator never reads this file. |
| <!-- parameter bootstrap:ADO_TENANT -->`ADO_TENANT` | C | `"$AIF_TENANT_ID"` | Azure DevOps connected tenant ID |
| <!-- parameter bootstrap:AIFACTORY_COMMIT_CHANGES -->`AIFACTORY_COMMIT_CHANGES` | O | `""` | Update confirmation y/yes or n/no; default No. Choosing Yes authorizes the launcher's commit/continue path. |
| <!-- parameter bootstrap:AIFACTORY_PROJECT_CONFIG -->`AIFACTORY_PROJECT_CONFIG` | C | `""` | Reviewed project JSON file; required together with explicit target environment, project number and repository root. |
| <!-- parameter bootstrap:AIFACTORY_PROJECT_NUMBER -->`AIFACTORY_PROJECT_NUMBER` | C | `""` | Reviewed update/project target number; required together with target environment, project configuration and repository root. |
| <!-- parameter bootstrap:AIFACTORY_PROJECT_ONLY -->`AIFACTORY_PROJECT_ONLY` | O | `"false"` | Update launcher equivalent of --project-only. |
| <!-- parameter bootstrap:AIFACTORY_REPO_ROOT -->`AIFACTORY_REPO_ROOT` | O | `""` | Repository root; --repo-root overrides it. |
| <!-- parameter bootstrap:AIFACTORY_TARGET_ENVIRONMENT -->`AIFACTORY_TARGET_ENVIRONMENT` | C | `"dev"` | Update target: dev, test/stage, or prod; verify route/environment naming. |
| <!-- parameter bootstrap:AIFACTORY_UPDATE_GITHUB_VARIABLES -->`AIFACTORY_UPDATE_GITHUB_VARIABLES` | O | `""` | GHA update confirmation y/yes or n/no for synchronization from .env; default No. |
| <!-- parameter bootstrap:AIFACTORY_USE_JSON_OVERRIDE -->`AIFACTORY_USE_JSON_OVERRIDE` | O | `""` | y/yes enables variables.json overrides; blank/n/no disables. Explicit reviewed project inputs force this to yes. |
| <!-- parameter bootstrap:AIFACTORY_VERSION -->`AIFACTORY_VERSION` | O | `"main"` | Explicit template release; create/update defaults to main. --aifactory-version takes precedence. |
| <!-- parameter bootstrap:AIF_ACCESS_HUB_MODE -->`AIF_ACCESS_HUB_MODE` | C | `"i"` | Standalone access hub: integrated in DEV common network (i) or external connectivity subscription (e); allowed: i e |
| <!-- parameter bootstrap:AIF_ACCESS_HUB_RESOURCE_GROUP -->`AIF_ACCESS_HUB_RESOURCE_GROUP` | C | `"aifactory-connectivity"` | External access-hub and private-DNS resource group |
| <!-- parameter bootstrap:AIF_ACCESS_HUB_SUBSCRIPTION_ID -->`AIF_ACCESS_HUB_SUBSCRIPTION_ID` | C | `""` | External access-hub subscription ID |
| <!-- parameter bootstrap:AIF_ACCESS_HUB_VNET_CIDR -->`AIF_ACCESS_HUB_VNET_CIDR` | C | `"10.240.0.0/22"` | External access-hub vNet CIDR |
| <!-- parameter bootstrap:AIF_ACCESS_HUB_VNET_NAME -->`AIF_ACCESS_HUB_VNET_NAME` | C | `""` | Aif access hub vnet name override; see create launcher. |
| <!-- parameter bootstrap:AIF_ADD_BASTION -->`AIF_ADD_BASTION` | O | `""` | Compatibility input; collection resets this to false. Access-hub Bastion is controlled separately. |
| <!-- parameter bootstrap:AIF_ADMIN_VM_SIZE -->`AIF_ADMIN_VM_SIZE` | O | `"Standard_D2s_v5"` | Self-hosted admin VM size |
| <!-- parameter bootstrap:AIF_APP_GATEWAY_BACKEND_FQDN -->`AIF_APP_GATEWAY_BACKEND_FQDN` | C | `""` | Simple-mode distinct private HTTPS backend; trusted TLS and unauthenticated GET / returning 200-399. |
| <!-- parameter bootstrap:AIF_APP_GATEWAY_CERT_SECRET_ID -->`AIF_APP_GATEWAY_CERT_SECRET_ID` | C | `""` | Simple-mode versionless Key Vault PFX certificate-secret URI, not a secret value. |
| <!-- parameter bootstrap:AIF_APP_GATEWAY_HOSTNAME -->`AIF_APP_GATEWAY_HOSTNAME` | C | `""` | Simple-mode custom frontend FQDN covered by certificate DNS SAN. |
| <!-- parameter bootstrap:AIF_AZURE_ML_PRINCIPAL_ID -->`AIF_AZURE_ML_PRINCIPAL_ID` | O | `""` | Existing Azure Machine Learning enterprise-application object ID; otherwise discovered/ensured. |
| <!-- parameter bootstrap:AIF_BOOTSTRAP_RESOURCE_GROUP -->`AIF_BOOTSTRAP_RESOURCE_GROUP` | O | `"rg-${AIF_PREFIX%-}-bootstrap-${AIF_LOCATION_SHORT}-${AIF_SCALESET_SUFFIX}"` | Aif bootstrap resource group override; see create launcher. |
| <!-- parameter bootstrap:AIF_CONFIGURE_VPN_CLIENT -->`AIF_CONFIGURE_VPN_CLIENT` | O | `"$configure_vpn_client_default"` | Install and configure Azure VPN Client on this computer? (Y/n) |
| <!-- parameter bootstrap:AIF_COST_CENTER -->`AIF_COST_CENTER` | O | `"123456"` | Simple-mode common and project cost-center tag. |
| <!-- parameter bootstrap:AIF_CREATE_DEFAULT_VERSION -->`AIF_CREATE_DEFAULT_VERSION` | O | `"main"` | Create launcher default when no explicit version selector is supplied. |
| <!-- parameter bootstrap:AIF_DATABRICKS_PRINCIPAL_ID -->`AIF_DATABRICKS_PRINCIPAL_ID` | O | `""` | Existing Databricks enterprise-application object ID; otherwise discovered/ensured when needed. |
| <!-- parameter bootstrap:AIF_DEPLOYMENT_IDENTITY_NAME -->`AIF_DEPLOYMENT_IDENTITY_NAME` | O | `"id-${AIF_PREFIX%-}-deploy-${AIF_LOCATION_SHORT}-${AIF_SCALESET_SUFFIX}"` | Aif deployment identity name override; see create launcher. |
| <!-- parameter bootstrap:AIF_DEV_SUBSCRIPTION_ID -->`AIF_DEV_SUBSCRIPTION_ID` | M | `"$current_subscription"` | DEV subscription ID |
| <!-- parameter bootstrap:AIF_DEV_VNET_CIDR -->`AIF_DEV_VNET_CIDR` | O | `"172.16.0.0/18"` | DEV vNet CIDR (canonical IPv4 /20 or larger; no XX placeholder) |
| <!-- parameter bootstrap:AIF_DRY_RUN -->`AIF_DRY_RUN` | O | `"false"` | Aif dry run override; see create launcher. |
| <!-- parameter bootstrap:AIF_HUB_RESOURCE_GROUP -->`AIF_HUB_RESOURCE_GROUP` | C | `""` | Hub private-DNS resource group |
| <!-- parameter bootstrap:AIF_HUB_SUBSCRIPTION_ID -->`AIF_HUB_SUBSCRIPTION_ID` | C | `""` | Hub subscription ID |
| <!-- parameter bootstrap:AIF_HUB_VNET_NAME -->`AIF_HUB_VNET_NAME` | C | `""` | Hub vNet name |
| <!-- parameter bootstrap:AIF_HUB_VNET_RESOURCE_GROUP -->`AIF_HUB_VNET_RESOURCE_GROUP` | C | `"$AIF_HUB_RESOURCE_GROUP"` | Hub vNet resource group |
| <!-- parameter bootstrap:AIF_IDENTITY_MODE -->`AIF_IDENTITY_MODE` | O | `"c"` | Deployment identity: create managed identity (c), existing managed identity (mi), or existing service principal (sp); allowed: c mi sp |
| <!-- parameter bootstrap:AIF_IP_ALLOWLIST -->`AIF_IP_ALLOWLIST` | O | `""` | IPv4 allowlist input; the current create prompt accepts private networking only. |
| <!-- parameter bootstrap:AIF_LOCATION -->`AIF_LOCATION` | O | `"swedencentral"` | Azure region (swedencentral, westeurope, northeurope, eastus, eastus2, uksouth, westgermany) |
| <!-- parameter bootstrap:AIF_MI_RESOURCE_ID -->`AIF_MI_RESOURCE_ID` | C | `""` | Existing user-assigned managed identity resource ID |
| <!-- parameter bootstrap:AIF_NETWORK_MODE -->`AIF_NETWORK_MODE` | O | `"priv"` | Networking: private-only (priv; enforced by policy); allowed: priv |
| <!-- parameter bootstrap:AIF_NON_INTERACTIVE -->`AIF_NON_INTERACTIVE` | O | `"false"` | Aif non interactive override; see create launcher. |
| <!-- parameter bootstrap:AIF_NO_WAIT -->`AIF_NO_WAIT` | O | `"false"` | Aif no wait override; see create launcher. |
| <!-- parameter bootstrap:AIF_PREFIX -->`AIF_PREFIX` | O | `"aif-"` | AI Factory naming prefix |
| <!-- parameter bootstrap:AIF_PREPARE_ONLY -->`AIF_PREPARE_ONLY` | O | `"false"` | Aif prepare only override; see create launcher. |
| <!-- parameter bootstrap:AIF_PROJECT_NUMBER -->`AIF_PROJECT_NUMBER` | O | `"001"` | First project number (001-999) |
| <!-- parameter bootstrap:AIF_SCALESET_SUFFIX -->`AIF_SCALESET_SUFFIX` | O | `"001"` | Scale-set number (001-999) |
| <!-- parameter bootstrap:AIF_SEEDING_KEYVAULT_NAME -->`AIF_SEEDING_KEYVAULT_NAME` | C | `"kv${prefix_compact}${AIF_LOCATION_SHORT}${AIF_SCALESET_SUFFIX}"` | Existing seeding Key Vault name |
| <!-- parameter bootstrap:AIF_SEEDING_MODE -->`AIF_SEEDING_MODE` | O | `"c"` | Seeding Key Vault: create/ensure (c) or use existing (e); allowed: c e |
| <!-- parameter bootstrap:AIF_SEEDING_RESOURCE_GROUP -->`AIF_SEEDING_RESOURCE_GROUP` | C | `"$AIF_BOOTSTRAP_RESOURCE_GROUP"` | Existing seeding Key Vault resource group |
| <!-- parameter bootstrap:AIF_SEED_PROJECT_SP -->`AIF_SEED_PROJECT_SP` | O | `"n"` | Create and seed an optional project automation service principal? (y/N) |
| <!-- parameter bootstrap:AIF_SETUP_HUB_ACCESS -->`AIF_SETUP_HUB_ACCESS` | O | `"y"` | Set up Azure VPN Gateway in the hub and Bastion Developer for DEV? (Y/n) |
| <!-- parameter bootstrap:AIF_SIMPLE_MODE -->`AIF_SIMPLE_MODE` | O | `"false"` | Opt in to the GHA Dev private foundation contract. |
| <!-- parameter bootstrap:AIF_SIMPLE_PROJECT_RESOURCES_JSON -->`AIF_SIMPLE_PROJECT_RESOURCES_JSON` | O | `"[\"foundry\",\"foundry-capability-host\",\"ai-search\",\"cosmos-db\",\"application-insights\"]"` | Simple-mode JSON resource-ID selection. Required project dependencies cannot be removed; [] removes only optional selections. |
| <!-- parameter bootstrap:AIF_SP_CLIENT_ID -->`AIF_SP_CLIENT_ID` | C | `""` | Existing service-principal client ID |
| <!-- parameter bootstrap:AIF_SP_CLIENT_SECRET -->`AIF_SP_CLIENT_SECRET` | C | `""` | Existing service-principal client secret |
| <!-- parameter bootstrap:AIF_SUBMODULE_BRANCH -->`AIF_SUBMODULE_BRANCH` | O | `""` | Legacy explicit branch selector consumed by release-version resolution. |
| <!-- parameter bootstrap:AIF_SUBMODULE_REF -->`AIF_SUBMODULE_REF` | C | `""` | Exact published commit SHA; required for the simple-mode source verification contract. |
| <!-- parameter bootstrap:AIF_TEAM_GROUP_ID -->`AIF_TEAM_GROUP_ID` | O | `""` | Reuse an existing team group by object ID; otherwise resolve/create from group name. |
| <!-- parameter bootstrap:AIF_TEAM_GROUP_NAME -->`AIF_TEAM_GROUP_NAME` | O | `"${AIF_PREFIX%-}prj${AIF_PROJECT_NUMBER}-team"` | Entra security group for the initial team |
| <!-- parameter bootstrap:AIF_TEAM_MEMBER_EMAIL -->`AIF_TEAM_MEMBER_EMAIL` | M | `"$current_user"` | Initial team member |
| <!-- parameter bootstrap:AIF_TENANT_ID -->`AIF_TENANT_ID` | M | `"$current_tenant"` | Azure tenant ID |
| <!-- parameter bootstrap:AIF_TOPOLOGY -->`AIF_TOPOLOGY` | O | `"s"` | Topology: standalone (s) or hub/spoke with central DNS (hs); allowed: s hs |
| <!-- parameter bootstrap:AIF_UPDATE_DEFAULT_VERSION -->`AIF_UPDATE_DEFAULT_VERSION` | O | `"main"` | Update launcher default when not project-only. |
| <!-- parameter bootstrap:AIF_VPN_CLIENT_CIDR -->`AIF_VPN_CLIENT_CIDR` | O | `"172.31.240.0/24"` | Point-to-site VPN client address pool |
| <!-- parameter bootstrap:AIF_YES -->`AIF_YES` | O | `"false"` | Aif yes override; see create launcher. |
| <!-- parameter bootstrap:AZURE_DEVOPS_EXT_PAT -->`AZURE_DEVOPS_EXT_PAT` | C | `""` | Azure DevOps PAT |
| <!-- parameter bootstrap:GITHUB_REPOSITORY -->`GITHUB_REPOSITORY` | C | `"$current_repo"` | GitHub repository (owner/name) |
| <!-- parameter bootstrap:GITHUB_REPOSITORY_VISIBILITY -->`GITHUB_REPOSITORY_VISIBILITY` | O | `"private"` | Simple-mode repository visibility: private or public; independent of Azure networking. |

## Configuration helper CLI inputs

`bootstrap/lib/aifactory_scaleset_config.py` is a local configuration API, **not an HTTP endpoint**. `--route`, `--repo-root`, and `--state-file` are required together for the default write operation. Other switches select independent inspection/validation operations. Unspecified argparse values are `null`; boolean switches default to `false`.

| Exact option | M/C/O | Parser default | Meaning / choices |
|---|---|---|---|
| <!-- parameter helper:--app-gateway-backend-fqdn -->`--app-gateway-backend-fqdn` | C | `""` | App gateway backend fqdn |
| <!-- parameter helper:--app-gateway-certificate-secret-id -->`--app-gateway-certificate-secret-id` | C | `""` | App gateway certificate secret id |
| <!-- parameter helper:--app-gateway-hostname -->`--app-gateway-hostname` | C | `""` | App gateway hostname |
| <!-- parameter helper:--certificate-metadata -->`--certificate-metadata` | C | `null` | Local certificate metadata JSON; validates metadata only, not private key material. |
| <!-- parameter helper:--gateway-health -->`--gateway-health` | C | `null` | Local gateway backend-health JSON; exit status indicates health. |
| <!-- parameter helper:--project-resources -->`--project-resources` | C | `null` | JSON array of simple-mode project resource IDs; required dependencies are retained. |
| <!-- parameter helper:--repo-root -->`--repo-root` | C | `null` | Consumer root containing the generated .env/YAML/JSON configuration. |
| <!-- parameter helper:--repository-visibility -->`--repository-visibility` | C | `"private"` | Repository visibility |
| <!-- parameter helper:--route -->`--route` | C | `null` | Route; choices: ado, gha |
| <!-- parameter helper:--simple-gateway-inputs -->`--simple-gateway-inputs` | C | `false` | Validate gateway input strings and print normalized JSON; no deployment. |
| <!-- parameter helper:--simple-mode-hub-subnets -->`--simple-mode-hub-subnets` | C | `null` | Validate existing subnet JSON and print reserved simple-mode subnets. |
| <!-- parameter helper:--simple-mode-manifest -->`--simple-mode-manifest` | C | `false` | Offline read-only contract/preset preview. |
| <!-- parameter helper:--state-file -->`--state-file` | C | `null` | Bootstrap state JSON, not variables.json; consumed by the selected route writer. |
| <!-- parameter helper:--verify-simple-mode-source -->`--verify-simple-mode-source` | C | `null` | Compare supplied checkout with the required shared source trees. |

## Bootstrap state JSON fields

These exact fields are consumed by the Python helper's local `--state-file` API. Normally the shell bootstrap writes this state after resolving identities and scope; it is **not** the persistent deployment `variables.json`. `C` below means required in the named function/route when invoked; `O` denotes only guarded `.get()` reads. Missing required keys are not defaulted. `project_sp_secret_names` contains the nested secret-name keys `app_id`, `object_id`, and `secret`, not secret values.

| Exact state field | M/C/O | Missing-key behavior | Consumer / meaning |
|---|---|---|---|
| <!-- parameter state:access_hub_mode -->`access_hub_mode` | O | `null` | `apply_gha`, `common_values`; Access hub mode |
| <!-- parameter state:add_bastion -->`add_bastion` | C | Required lookup | `apply_gha`, `common_values`; Add bastion |
| <!-- parameter state:admin_vm_size -->`admin_vm_size` | O | `"Standard_D2s_v5"` | `apply_gha`, `common_values`; Admin vm size |
| <!-- parameter state:ado_agent_name -->`ado_agent_name` | O | `""` | `common_values`; Ado agent name |
| <!-- parameter state:ado_agent_pool -->`ado_agent_pool` | O | `"Default"` | `common_values`; Ado agent pool |
| <!-- parameter state:ado_tenant_id -->`ado_tenant_id` | C | Required lookup | `apply_ado`; Ado tenant id |
| <!-- parameter state:allow_public_access_behind_vnet -->`allow_public_access_behind_vnet` | C | Required lookup | `apply_gha`, `common_values`; Allow public access behind vnet |
| <!-- parameter state:azure_ml_principal_id -->`azure_ml_principal_id` | O | `""` | `apply_gha`, `common_values`; Azure ml principal id |
| <!-- parameter state:cost_center -->`cost_center` | C | Required lookup | `common_values`; Cost center |
| <!-- parameter state:databricks_principal_id -->`databricks_principal_id` | O | `""` | `apply_gha`, `common_values`; Databricks principal id |
| <!-- parameter state:dev_service_connection -->`dev_service_connection` | C | Required lookup | `apply_ado`; Dev service connection |
| <!-- parameter state:dev_subscription_id -->`dev_subscription_id` | C | Required lookup | `apply_gha`, `common_values`; Dev subscription id |
| <!-- parameter state:dev_vnet_cidr -->`dev_vnet_cidr` | C | Required lookup | `apply_gha`, `common_values`; Dev vnet cidr |
| <!-- parameter state:enable_public_genai_access -->`enable_public_genai_access` | C | Required lookup | `apply_gha`, `common_values`; Enable public genai access |
| <!-- parameter state:enable_public_perimeter -->`enable_public_perimeter` | C | Required lookup | `apply_gha`, `common_values`; Enable public perimeter |
| <!-- parameter state:github_repository -->`github_repository` | C | Required lookup | `apply_gha`; Github repository |
| <!-- parameter state:github_repository_visibility -->`github_repository_visibility` | O | `null` | `common_values`; Github repository visibility |
| <!-- parameter state:hub_resource_group -->`hub_resource_group` | O | `""` | `apply_gha`, `common_values`; Hub resource group |
| <!-- parameter state:hub_subscription_id -->`hub_subscription_id` | O | `""` | `apply_gha`, `common_values`; Hub subscription id |
| <!-- parameter state:ip_allowlist -->`ip_allowlist` | O | `""`, `null` | `apply_gha`, `common_values`; Ip allowlist |
| <!-- parameter state:location -->`location` | C | Required lookup | `apply_gha`, `common_values`; Location |
| <!-- parameter state:location_short -->`location_short` | C | Required lookup | `apply_gha`, `common_values`; Location short |
| <!-- parameter state:oidc_client_id -->`oidc_client_id` | O | `""` | `apply_gha`; Oidc client id |
| <!-- parameter state:prefix -->`prefix` | C | Required lookup | `apply_gha`, `common_values`; Prefix |
| <!-- parameter state:prod_service_connection -->`prod_service_connection` | C | Required lookup | `apply_ado`; Prod service connection |
| <!-- parameter state:prod_subscription_id -->`prod_subscription_id` | C | Required lookup | `apply_gha`, `common_values`; Prod subscription id |
| <!-- parameter state:project_number -->`project_number` | C | Required lookup | `apply_gha`, `common_values`, `selected_project_organization`; Project number |
| <!-- parameter state:project_sp_secret_names -->`project_sp_secret_names` | O | `null` | `apply_gha`, `common_values`; Project sp secret names |
| <!-- parameter state:runner_mode -->`runner_mode` | O | `null` | `apply_gha`, `common_values`; Runner mode |
| <!-- parameter state:scaleset_suffix -->`scaleset_suffix` | C | Required lookup | `apply_gha`, `common_values`; Scaleset suffix |
| <!-- parameter state:seeding_keyvault_name -->`seeding_keyvault_name` | C | Required lookup | `apply_gha`, `common_values`; Seeding keyvault name |
| <!-- parameter state:seeding_resource_group -->`seeding_resource_group` | C | Required lookup | `apply_gha`, `common_values`; Seeding resource group |
| <!-- parameter state:seeding_subscription_id -->`seeding_subscription_id` | C | Required lookup | `apply_gha`, `common_values`; Seeding subscription id |
| <!-- parameter state:simple_mode -->`simple_mode` | O | `"false"` | `simple_mode_enabled`; Simple mode |
| <!-- parameter state:simple_project_resources_json -->`simple_project_resources_json` | O | `null` | `common_values`; Simple project resources json |
| <!-- parameter state:stage_service_connection -->`stage_service_connection` | C | Required lookup | `apply_ado`; Stage service connection |
| <!-- parameter state:stage_subscription_id -->`stage_subscription_id` | C | Required lookup | `apply_gha`, `common_values`; Stage subscription id |
| <!-- parameter state:team_group_id -->`team_group_id` | C | Required lookup | `apply_gha`, `common_values`; Team group id |
| <!-- parameter state:team_group_name -->`team_group_name` | C | Required lookup | `apply_gha`, `common_values`; Team group name |
| <!-- parameter state:team_member_email -->`team_member_email` | O | `null` | `common_values`; Team member email |
| <!-- parameter state:tenant_id -->`tenant_id` | C | Required lookup | `apply_gha`, `common_values`; Tenant id |
| <!-- parameter state:topology -->`topology` | C | Required lookup | `apply_gha`, `common_values`; Topology |

<!-- END GENERATED PARAMETERS -->
