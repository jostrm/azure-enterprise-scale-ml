# AI Gateway Azure DevOps pipeline

This guide covers `infra-ai-gateway.yaml`.

## Short answer

Setting `ENABLE_APIM: "true"` is **not sufficient** and does **not** create an API Management service.

The pipeline configures an **existing APIM service**. It can update that service's SKU and capacity, then creates or updates:

- Azure OpenAI backend entities with `429` circuit breakers
- A weighted APIM backend pool
- An APIM API and its operations
- Token-limit, managed-identity authentication, pool-routing, and retry policies
- Optional `Cognitive Services OpenAI User` role assignments for the APIM identity

The APIM resource group is not inferred from the AI Factory common resource group. Set `apimGatewayResourceGroup` explicitly. It may be the common resource group, but that is a deployment choice rather than a pipeline default.

## Resources that must already exist

Before running the pipeline, create or identify:

1. An APIM service in a supported non-Consumption SKU. Enable its system-assigned managed identity.
2. One or more Azure OpenAI-compatible `Microsoft.CognitiveServices/accounts` resources.
3. The model deployment used by clients on every backend account in the pool. Deployment names must be identical because the `{deployment}` path is forwarded unchanged to every backend.
4. Network connectivity and DNS resolution from APIM to every backend endpoint. Private backends require APIM VNet connectivity and private DNS resolution.

The backend `resourceId` is the Cognitive Services or Foundry **account** resource ID, not a Foundry project ID. The pipeline does not create Foundry accounts, Azure OpenAI accounts, projects, or model deployments.

## Required variables

These values are required when `ENABLE_APIM` is `true`; the task fails before deployment when any value is empty or when the backend list is `[]`:

| Variable | Required value |
| --- | --- |
| `apimGatewayResourceGroup` | Resource group containing the existing APIM service |
| `apimGatewayServiceName` | Existing APIM service name |
| `apimGatewayAggregateTpm` | Positive integer, normally 80-90% of the sum of backend deployment TPM |
| `apimGatewayBackendsJson` | Non-empty JSON array of existing backend accounts |

Example configuration in `../variables/variables.yaml`:

```yaml
ENABLE_APIM: "true"
apimGatewaySubscriptionId: "<apim-subscription-id>"
apimGatewayResourceGroup: "<existing-apim-resource-group>"
apimGatewayServiceName: "<existing-apim-name>"
apimGatewaySku: "StandardV2"
apimGatewaySkuCapacity: 1
apimGatewayAggregateTpm: "51000"
apimGatewayCallerTpm: "10000"
apimGatewayAssignOpenAIUserRole: "true"
apimGatewayManagedIdentityPrincipalId: "<apim-system-identity-object-id>"
apimGatewayBackendsJson: '[{"name":"aoai-01","endpoint":"https://aoai-01.openai.azure.com","resourceId":"/subscriptions/<backend-subscription-id>/resourceGroups/<backend-rg>/providers/Microsoft.CognitiveServices/accounts/aoai-01","weight":1,"priority":1}]'
```

`apimGatewaySubscriptionId` is optional. When empty, each stage uses its environment subscription: `dev_sub_id`, `test_sub_id`, or `prod_sub_id`.

The remaining defaults create API ID `azure-openai-gpt55`, public path `openai`, backend pool `aoai-gpt55-pool`, a 10,000 TPM per-caller limit, and two retries.

## Backend pool configuration

Each object in `apimGatewayBackendsJson` must contain:

| Property | Meaning |
| --- | --- |
| `name` | Unique APIM backend entity name |
| `endpoint` | Account endpoint without `/openai`; a trailing slash is accepted |
| `resourceId` | Full account-level Azure resource ID |
| `weight` | Routing weight, normally proportional to provisioned TPM |
| `priority` | Optional; defaults to `1`. Use `1` for active-active routing |

For example, backends provisioned with 30K and 60K TPM should normally use weights `1` and `2`. Their total is 90K TPM, so an 85% aggregate guard would be `76500`.

Do not put credentials or API keys in this JSON. APIM authenticates to the backends with its managed identity.

## Identity and permissions

APIM's system-assigned identity needs `Cognitive Services OpenAI User` on every backend account.

Choose one of these approaches:

- Assign the role before running the pipeline and leave `apimGatewayAssignOpenAIUserRole: "false"`.
- Set `apimGatewayAssignOpenAIUserRole: "true"` and supply `apimGatewayManagedIdentityPrincipalId`. The Azure DevOps service connection must then have `Microsoft.Authorization/roleAssignments/write` on every backend account, including accounts in other subscriptions.

The Azure DevOps service connection also needs permission to:

- Read and update the existing APIM service, including its SKU
- Create subscription-scope deployments in the APIM subscription
- Create and update APIM backends, pools, APIs, operations, and policies
- Read backend resources and create role assignments when automatic RBAC is enabled

Use `dev_service_connection`, `test_service_connection`, and `prod_service_connection` for the corresponding stages. All referenced subscriptions must authorize the relevant service connection.

## SKU behavior

The pipeline reads the current APIM SKU and patches it to `apimGatewaySku` and `apimGatewaySkuCapacity` before applying the gateway configuration.

- Supported: `Developer`, `Basic`, `Standard`, `Premium`, `BasicV2`, `StandardV2`, and `PremiumV2`.
- Unsupported: `Consumption`, because backend circuit breakers are unavailable.
- APIM cannot switch between classic and v2 SKU families in place. If the existing service is classic, leaving the `StandardV2` default causes the pipeline to stop. Set a compatible classic SKU or create a new v2 APIM service first.
- To avoid an unintended SKU change, set the SKU and capacity to the existing service's values.

## Azure DevOps setup

1. Create an Azure DevOps pipeline that points to `environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-common/infra-ai-gateway.yaml`.
2. Replace the `<todo>` subscription IDs and service connection names used by the selected stages in `../variables/variables.yaml` or override them securely in Azure DevOps.
3. Configure the APIM and backend variables above.
4. Confirm that the checkout folder is named `azure-enterprise-scale-ml`. The job currently uses that hard-coded folder under `$(System.DefaultWorkingDirectory)`.
5. Configure approvals/checks on the Azure DevOps `Dev`, `Stage`, and `Prod` environments if required. Referencing an environment does not create an approval automatically.
6. Run the pipeline manually. It has `trigger: none`.

A normal manual run evaluates Dev, Stage, and Prod in sequence. The gateway variables in the shared variable template are reused across stages. If environments have different APIM names, resource groups, backend lists, SKUs, or TPM values, define stage-specific overrides or use separate variable templates before running all stages.

`ENABLE_KONG` is independent and defaults to `false`; Kong configuration is not required for the APIM gateway.

## Preflight checklist

- [ ] Existing APIM name, subscription, and resource group are correct.
- [ ] APIM system-assigned managed identity is enabled.
- [ ] Configured SKU belongs to the same family as the existing APIM SKU.
- [ ] Every backend resource ID and endpoint exists.
- [ ] Every backend contains the same model deployment names used by clients.
- [ ] APIM can resolve and reach every backend endpoint.
- [ ] APIM identity has `Cognitive Services OpenAI User`, or automatic assignment is enabled with sufficient pipeline permissions.
- [ ] Aggregate and caller TPM limits are appropriate.
- [ ] Service connections are authorized for all selected stages and subscriptions.
- [ ] Any required Azure DevOps environment approvals/checks are configured.

## After deployment

The API requires an APIM subscription key. Its default routes are:

- `POST https://<apim-gateway-host>/openai/deployments/<deployment>/chat/completions`
- `POST https://<apim-gateway-host>/openai/responses`
- `POST https://<apim-gateway-host>/openai/v1/responses`

Send the configured Azure OpenAI API version as required by the selected operation. Verify that requests succeed, that a backend receives traffic, and that APIM returns `429` when the configured token limit is exceeded.

The pipeline does not run an Azure deployment `what-if`. Use a non-production APIM instance for the first run or add a reviewed what-if step before production rollout.