# Private Azure inventory tool for Foundry agents

This folder provisions the private Azure MCP service used by the optional
expanded read-only agent profile. It lets agents inspect actual project resource
names, IDs, types and locations instead of inventing live infrastructure facts.
It is a supporting tool service, not a RAG dataset or a model-training workload.

Discovery inherits the
[root common/project storage selection](../readme.md#one-storage-selection-for-every-example)
and previews report the selected account/group/container. This does **not**
move the MCP inventory scope or Reader role to the common resource group;
both remain restricted to the project's resources.

## Use case summary

- Use case type: Not applicable as a standalone model use case; supporting tooling for RAG with LLM
- Data type: Tabular (structured Azure resource metadata returned as JSON; no document or image contents)
- Number of source data sets: 0; live Azure Resource Manager metadata is not an ingested corpus
- Data sources: No master-lake path; Azure Resource Manager resources in the configured project resource group
- Inference type: Online (agent tool calls); provisioning itself performs no inference
- Technology used in full chain: Microsoft Foundry | Azure MCP Server | Azure Container Apps | Azure Resource Manager | Microsoft Entra ID | Azure Private Link / Private DNS | Azure DevOps or GitHub Actions for deployment

## Security and operations

The exact initial tool allowlist is `group_resource_list`. The server has its
own managed identity with Reader on the project resource group only. The Foundry
project identity authenticates to the single-tenant MCP API; no client secret,
project-UAMI attachment or public ingress is required.

`deploy.py` provides read-only `plan` and `validate` commands, explicit
`prepare-identity --apply`, and `deploy --apply`. The consumer's reviewed
configuration and `enableAzureMcpServer=true` gate deployment.
Use the [full deployment instructions](../../../documentation/v2/30-39/agent-factory.md#optional-expanded-read-only-profile)
for the isolated MCP-only pipeline and connection verification.

Pinned Azure MCP 2.0.5 serves at its root URL, not `/mcp`. Its application role
name `Mcp.Tools.ReadWrite.All` permits MCP invocation, not Azure write operations;
the allowlisted tool and server identity's RBAC constrain actual Azure access.
Public Microsoft Learn is a separate service and still requires approval.

## Prerequisites

- Complete the root [prerequisites](../readme.md#prerequisites) for an existing
  Foundry project and model deployment. Keep reviewed configuration at
  `<consumer>\aifactory\agent-factory\config.json`, with the correct variables
  file and explicit target key, such as `project001-dev`. Do not replace an
  existing config with the generic example.
- Azure CLI and its supported Bicep tooling must be available. Use cached Azure
  CLI OAuth for the selected tenant/subscription first; use browser-based login
  only if that tenant's cached OAuth is unavailable. Keep VPN/private DNS and
  routing to Foundry and the eventual private ACA endpoint available; never
  enable public ingress to work around connectivity failures.
- Review the config's `azure_mcp` object: optional `name`, exact
  `infrastructure_subnet_id`, `private_endpoint_subnet_id`,
  `private_dns_zone_id`, immutable official
  `mcr.microsoft.com/azure-sdk/azure-mcp@sha256:<digest>` image, and
  `tools: ["group_resource_list"]`. Use the reviewed Azure MCP 2.0.5 digest,
  not `latest` or an invented digest.
- Both subnets must already exist in the same target-subscription VNet and be
  different subnets. The infrastructure subnet must be IPv4 `/27` or larger,
  delegated exactly to `Microsoft.App/environments`, and available to this
  environment; do not reuse Foundry's `-aca-002` subnet. Use the existing regional
  `privatelink.<region>.azurecontainerapps.io` zone and preserve hub-policy
  ownership (`centralDnsZoneByPolicyInHub`).
- `validate`/`deploy` require `enableAzureMcpServer=true` in the selected
  environment's variables. Identity preparation requires approved Entra
  directory permissions to create/reuse the owned API application/service
  principal and assign the API role to the Foundry **project** identity.
  Deployment separately requires the reviewed ARM deployment, networking and
  project-RG Reader role-assignment permissions. A runtime caller does not need
  these administrative permissions.
- Retain a central repository checkout containing
  `environment_setup\aifactory\bicep\esml-genai-1\08-azure-mcp.bicep`.
  A consumer starter copy alone does not contain that infrastructure template.

## How to set up the Python environment

Use the shared Python 3.13 operator environment, not a new MCP server Python
runtime: the server itself is the digest-pinned container. Commands below run
from **`40-agent-factory`**, never from `44-azure-mcp`.

```powershell
$RepositoryRoot = "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml"
Set-Location (Join-Path $RepositoryRoot "usecase_code\40-agent-factory")
# Consumer alternative: C:\path\to\consumer\aifactory-usecase-code\40-agent-factory
$Consumer = "C:\path\to\consumer" # Replace with your consumer checkout.
$Config = Join-Path $Consumer "aifactory\agent-factory\config.json"
$Target = "project001-dev"
if (-not (Test-Path $Config)) { throw "Complete the reviewed consumer configuration first." }
if (-not (Test-Path ".\.venv\Scripts\python.exe")) { py -3.13 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

Reuse an already prepared environment; no activation or folder-local requirements
are needed. See [Python setup](../readme.md#how-to-set-up-the-python-environment)
and [folder layout](../readme.md#folder-layout).

## How to run the code

Execute one numbered step at a time and stop on errors. `plan`/`validate` are
read-only Azure checks, not offline simulations or successful deployment claims.

1. **Inspect the selected target and read the MCP plan using cached OAuth.**
   Use browser-based login only if the selected tenant's cached OAuth is unavailable.

   ```powershell
   $Plan = .\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target | ConvertFrom-Json
   if ($LASTEXITCODE -ne 0) { throw "Resolve the configuration error before continuing." }
   $Plan.target
   # Only if cached OAuth for this tenant is unavailable:
   # az login --tenant $Plan.target.tenant_id
   # Read-only identity inspection; this alone does not prove token validity.
   az account show --subscription $Plan.target.subscription_id --query "{subscription:id,tenant:tenantId}" --output json
   .\.venv\Scripts\python.exe .\44-azure-mcp\deploy.py plan --config $Config --target $Target
   ```

   The MCP result contains `plan`, `preflight`, `storage` and `mutations: false`.
   Inspect the exact subscription, tenant, project resource group, project
   identity, image, subnets and DNS zone. Storage selection is informational for
   MCP; the inventory scope and Reader grant remain the project resource group.

2. **Entra mutation: prepare the secretless caller identity, only if needed.**

   ```powershell
   .\.venv\Scripts\python.exe .\44-azure-mcp\deploy.py prepare-identity --config $Config --target $Target --apply
   ```

   Expected output identifies `identity_file`, normally
   `<config-directory>\azure-mcp-identity.json`. It records IDs/readiness, not
   secrets. Inspect ambiguous failures before retrying; existing compatible owned
   identities are reused, not arbitrary apps overwritten. If the reviewed identity
   file already exists for this project, proceed to validation instead.
   Keep the default filename: the downstream connection CLI reads it directly.

3. **Read-only ARM validation using the prepared identity.**

   ```powershell
   .\.venv\Scripts\python.exe .\44-azure-mcp\deploy.py validate --config $Config --target $Target `
     --repository-root $RepositoryRoot
   ```

   Expect `arm_validation` without errors and `mutations: false`.
   Validation needs the existing identity file and the explicit enable flag; it
   does not create identity or infrastructure.

4. **Azure mutation: provision only the reviewed private MCP infrastructure.**
   Use the organization's isolated MCP-only pipeline described in the
   [deployment guide](../../../documentation/v2/30-39/agent-factory.md#optional-expanded-read-only-profile),
   **or**, when direct operator deployment is approved, run:

   ```powershell
   .\.venv\Scripts\python.exe .\44-azure-mcp\deploy.py deploy --config $Config --target $Target `
     --repository-root $RepositoryRoot --apply
   ```

   Do not run both deployment routes. This provisions the owned private
   workload-profile ACA environment/app, its dedicated system identity, private
   endpoint/DNS association as permitted by policy, and Reader at the project RG.
   It does not grant common-RG inventory access or redeploy the whole AI Factory.
   Expected status is `infrastructure-deployed-not-yet-validated`, **not** proof
   that Foundry can invoke the service. Direct deployment records
   `<config-directory>\.agent-factory\<account>\<project>\azure-mcp.json`.
   If infrastructure is already deployed, skip provisioning and verify it below.

5. **Check private DNS; mutate only when an inspected association is missing.**

   ```powershell
   .\.venv\Scripts\python.exe -m agent_factory repair-azure-mcp-dns --config $Config --target $Target
   # Conditional Azure mutation, only after reviewing the preceding result:
   .\.venv\Scripts\python.exe -m agent_factory repair-azure-mcp-dns --config $Config --target $Target --apply
   ```

   Skip the second command when no repair is needed. Repair can create the
   missing association only on the owned, approved private endpoint using the
   existing regional hub zone. It does not replace conflicts or change DNS policy.

6. **Azure mutation: configure the project-MI connection; then run the live probe.**

   ```powershell
   .\.venv\Scripts\python.exe -m agent_factory configure-azure-mcp --config $Config --target $Target --apply
   .\.venv\Scripts\python.exe -m agent_factory verify-azure-mcp --config $Config --target $Target
   ```

   Configuration verifies the actual image, flags, identity, Reader scope,
   private endpoint and unauthenticated HTTP **401** challenge. It should return
   `connection_ready: true`, `infrastructure_verified: true` and initially
   `tool_call_verified: false`.

   `verify-azure-mcp` performs **billable model inference and one read-only
   inventory tool call**; it has no `--apply` because it does not provision Azure
   resources. Success requires the actual `group_resource_list` arguments,
   successful output and returned resource IDs to match the selected subscription
   and project group. It records `tool_call_verified: true` in
   `<config-directory>\.agent-factory\<account>\<project>\azure-mcp-connection.json`.
   An operator's endpoint check or the model saying it called a tool is not enough.

Only after this exact connection is verified should the reviewed consumer config
select `tool_profile: "expanded-readonly"` and deploy the chosen agents through
the root [run sequence](../readme.md#how-to-run-the-code). Do not deploy the whole
catalog just to test MCP. No secret retrieval, storage-content reads, arbitrary
CLI execution or Azure resource writes are exposed by this initial allowlist.
