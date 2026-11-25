---
id: ai-gateway-apim-provisioning
status: observed
sources:
  - environment_setup/aifactory/bicep/scripts/apim-gateway-deployment.py
  - environment_setup/aifactory/bicep/scripts/apim_gateway_config.py
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/main.bicep
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/network-main.bicep
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/network-subnet.bicep
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/service-main.bicep
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/apim-service.bicep
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/private-endpoint-main.bicep
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/private-endpoint.bicep
  - environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/README.md
  - environment_setup/aifactory/bicep/copy_to_local_settings/ai-gateway/apim.managed.dev.example.json
  - environment_setup/aifactory/bicep/copy_to_local_settings/ai-gateway/apim.existing.dev.example.json
  - environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-common/infra-ai-gateway.yaml
  - environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-common/jobs/job-2-ai-gateway.yaml
  - environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-common/infra-ai-gateway.md
  - environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-ai-gateway.yml
  - environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/03a-GH-create-or-update-github-variables.sh
  - environment_setup/aifactory/variables.json
  - documentation/v2/20-29/29-factory-AI-Gateways.md
  - environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/ai_gateway_finops.py
  - environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/ai-gateway-finops.kql
  - environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops/ai-gateway-finops.workbook.json
  - environment_setup/aifactory/bicep/scripts/deploy-aifactory-dashboard.py
  - environment_setup/aifactory/bicep/scripts/deploy-dashboards-only.py
  - environment_setup/aigateway/readme.md
tests:
  - environment_setup/unit-tests/test-bicep/unit/test_apim_gateway_deployment.py
  - environment_setup/unit-tests/test-bicep/unit/test_apim_gateway_workflows.py
  - environment_setup/unit-tests/test-bicep/unit/test_apim_gateway_examples.py
  - environment_setup/unit-tests/test-bicep/unit/test_apim_provisioning_bicep.py
  - environment_setup/unit-tests/test-bicep/unit/test_bicep_matrix.py
  - environment_setup/unit-tests/test-bicep/unit/test_pipeline_feature_contracts.py
  - environment_setup/unit-tests/test-bicep/unit/test_mcp_ai_gateway_flags.py
  - environment_setup/unit-tests/test-bicep/test_ai_gateway_finops.py
  - environment_setup/unit-tests/test-bicep/test_aifactory_dashboard.py
  - environment_setup/unit-tests/test-bicep/test_dashboard_only.py
graph_symbols:
  - environment_setup/aifactory/bicep/scripts/apim-gateway-deployment.py::class:Deployment
  - environment_setup/aifactory/bicep/scripts/apim-gateway-deployment.py::function:Deployment.execute
  - environment_setup/aifactory/bicep/scripts/apim-gateway-deployment.py::function:review_plan
  - environment_setup/aifactory/bicep/scripts/apim_gateway_config.py::function:validate_config
  - environment_setup/aifactory/bicep/scripts/apim_gateway_config.py::function:load_config
reviewed_source: '1f76c0a0 + managed APIM provisioning working tree; observed 2026-10-21'
---
# AI gateway: reviewed APIM runner and managed provisioning

## Two paths, one switch

The AI gateway pipelines (ADO `infra-ai-gateway.yaml` -> `jobs/job-2-ai-gateway.yaml`, GHA
`infra-ai-gateway.yml`) have two mutually exclusive APIM paths, chosen by
`apimGatewayManagedProvisioning` / `APIM_GATEWAY_MANAGED_PROVISIONING` (default `false`):

- **Classic (default).** "Deploy APIM Azure OpenAI pool" patches the SKU of an existing APIM and
  deploys `main.bicep`. Its script, the MCP step and Kong keep their behaviour while the switch is
  off; contract tests pin that.
- **Reviewed runner (opt-in).** With `ENABLE_APIM` and the switch on, `apim-gateway-deployment.py`
  replaces the classic step: an offline `plan`, a read-only `what-if` of the next phase, and an
  `apply` of at most one phase that needs the reviewed `planDigest` and `previewDigest`. The
  configuration is a consumer JSON (`apimGatewayConfigFile`) or, when empty, an `existing`
  configuration built from the `apimGateway*` variables.

The runner is the only writer in the opt-in path; the pipeline scripts only serialize arguments
(no `az` calls, no inline input evaluation) and publish `plan.json`, `receipt.json` and phase
previews as artifacts, also on failure.

## Managed lifecycle (Template Method over phase templates)

`Deployment.execute` runs one fixed algorithm per invocation - inventory, resolve the next phase,
preview, verify approvals, write once, post-check - over the `PHASE_TEMPLATES` map:
`network` (`network-main.bicep`, only an explicitly requested new subnet), `service-bootstrap` and
`service-lockdown` (`service-main.bicep`, StandardV2, public access Enabled then Disabled),
`private-endpoint` (`private-endpoint-main.bicep`), `configuration` (`main.bicep`, shared with the
classic step). Ownership is an `aifactory-gateway-owner` tag equal to `ownershipId`; anything else is
refused rather than adopted. Writes are never retried and nothing is deleted automatically.

`main.bicep` stays the single configuration template for both paths: the runner passes exactly the
parameters the classic step passes, so the policy package and `mcpServers` keep their defaults in
the runner path (a known limitation, not a separate contract).

## Coupling to the MCP and Kong

The MCP step (`addAIFactoryMCP2APIM`, see [[MCP-Boundary]]) and Kong locate the APIM through the
`apimGateway*` variables. In the runner path they run only when the same run's apply reached the
`configuration` phase (`gatewayConfigured` in the runner summary -> ADO variable
`apimGatewayManagedConfigured`, GHA step output `managed_apim.configured`), and `load_config`
refuses a JSON that names a different APIM than non-empty `apimGateway*` variables.

## Environments and serialization

ADO keeps the Dev -> Stage -> Prod promotion with `deploymentTarget: all` (default) and can select
one stage; `apply` across `all` is refused before the runner starts. GHA serializes runner runs per
environment with a workflow concurrency group, and leaves classic runs unserialized as before.
Digests are content equality, not authorization or a lock: environment approvals and one writer per
APIM remain operator responsibilities.

## Evidence limits

All evidence is offline: unit tests with a fake Azure CLI, compiled Bicep and parsed pipelines. No
what-if or deployment of the runner has run against Azure (status `observed` describes source).
User guide: `documentation/v2/20-29/29-factory-AI-Gateways.md`.

## Gateway FinOps reporting (source addition, 2026-11-25)

The reusable report lives under
`environment_setup/aifactory/bicep/copy_to_local_settings/automation/coreteam/finops`.
Its Python builder renders the Azure Monitor workbook from the canonical KQL and
validated configuration. The generated JSON is also importable without deployment tooling.
The existing common-dashboard reconciler and dashboard-only pipeline save one workbook
in the DEV common resource group and publish its launch tile on the common dashboard.
The workbook uses existing, viewer-authorized Log Analytics workspaces; dashboard refresh
does not enable diagnostics, provision a gateway, grant roles, or ingest telemetry.

Native APIM LLM logs supply token usage and are correlated with gateway logs for the
APIM subscription. An APIM subscription is not an Azure subscription, and the APIM
developer user is not an authenticated application end user. Per-user estimates require
the documented metadata-only producer and an explicitly trusted telemetry source.
Missing identity, cache details, rates, or complete usage remain visibly unattributed
or unpriced. Estimated token charges are not invoice amounts; provisioned capacity and
other meters require separate billing reconciliation.

Consumer configuration is optional and repository-relative through
`dev.aiGatewayFinopsConfigFile`. Without an explicit replacement, refreshed workbooks
preserve validated saved settings. The dashboard-only plan remains read-only and its
workbook writes are constrained to the deterministic common workbook resource.
See `environment_setup/aigateway/readme.md` for prerequisites, producer usage,
configuration, and plan/deploy commands.

This addition describes source and offline evidence only. No live workspace query,
portal workbook execution, APIM configuration change, or Azure deployment is established
by this note. Earlier provisioning observations above retain their original scope.
