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
