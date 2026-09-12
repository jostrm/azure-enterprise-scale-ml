# Agent Factory - Agents and Tools

Agent Factory provides persistent Foundry prompt agents, framework-based hosted
agents, and a hosted multi-agent team. The reference inventory below uses the
default `aif` name prefix; other deployments can configure a different prefix.

## Default agent inventory

| Agent name | Type / runtime | Tools and agent calls |
| --- | --- | --- |
| `aif-knowledge` | Prompt | Foundry IQ MCP tool `knowledge_base_retrieve`, querying the private Kaggle knowledge base. |
| `aif-reviewer` | Prompt | No tools. Reviews the draft and supplied evidence for unsupported claims. |
| `aif-docs` | Prompt | Microsoft Learn MCP tools `microsoft_docs_search` and `microsoft_docs_fetch`. Each call requires approval. |
| `aif-agent-framework` | Hosted / Microsoft Agent Framework | Calls `aif-knowledge` internally for grounded evidence. |
| `aif-langgraph` | Hosted / LangGraph | Calls `aif-knowledge` internally for grounded evidence. |
| `aif-openai-sdk` | Hosted / OpenAI Agents SDK | Calls `aif-knowledge` internally for grounded evidence. |
| `aif-copilot-sdk` | Hosted / GitHub Copilot SDK | Calls `aif-knowledge` internally. Copilot's built-in tools are disabled. |
| `aif-custom` | Hosted / custom Responses runtime | Calls `aif-knowledge` internally for grounded evidence. |
| `aif-helpdesk-team` | Hosted / multi-agent coordinator | Calls `aif-knowledge`, then `aif-reviewer`, then synthesizes the reviewed answer. |

## Attached tools versus internal agent calls

Only `aif-knowledge` and `aif-docs` have attached MCP tools. Knowledge retrieval
uses the configured private Foundry IQ connection without per-call approval.
Microsoft Learn calls always require approval.

Hosted agents call their participants through application code, not through
declarative tools attached to their Foundry definitions. An empty hosted-agent
tool list therefore does not mean that it has no knowledge dependency. The team
passes the knowledge agent's findings to the reviewer before synthesis.

## Optional expanded read-only profile

Set `tool_profile` to `expanded-readonly` in the consumer's
`aifactory/agent-factory/config.json` only when deploying the additional private
Azure MCP infrastructure. This is opt-in; the default profile above is unchanged.

| Agent role | Additional capabilities |
| --- | --- |
| Knowledge | Private Azure resource inventory through `group_resource_list`, alongside Foundry IQ. |
| Reviewer | Foundry IQ for evidence checks and private Azure resource inventory. |
| Documentation | `microsoft_code_sample_search`, plus private Azure inventory. Public Learn calls still require approval. |
| Hosted framework agents and team | Foundry IQ or Azure inventory through the persisted knowledge participant. No shell or Copilot built-in tools are enabled. |

The initial Azure MCP allowlist contains exactly `group_resource_list`: resource
names, IDs, types and locations in the selected project resource group. It does
not provide resource changes, secret retrieval, storage contents, or arbitrary
CLI execution. Hosted agents do not silently call public Learn with private
conversation data; public documentation remains a separate approval-gated agent.

### Private service and identity boundary

The reusable templates are
[`08-azure-mcp.bicep`](../../../environment_setup/aifactory/bicep/esml-genai-1/08-azure-mcp.bicep)
and [`azureMcpServer.bicep`](../../../environment_setup/aifactory/bicep/modules/azureMcpServer.bicep).
They create an internal workload-profile Container Apps environment with public
network access disabled, a TLS-only app, a private endpoint and a dedicated
system-assigned hosting identity. Reader is granted only on the project resource
group. The existing infrastructure and private-endpoint subnets are not changed.

The Foundry **project** managed identity receives permission to invoke the
single-tenant MCP API. The API role is named `Mcp.Tools.ReadWrite.All` by Azure MCP;
that name does not grant Azure write access. The server's exact read-only tool
allowlist and its separate Reader-only hosting identity constrain Azure access.
No client secret, shared project UAMI or public endpoint is used.

Use an immutable official image digest, not `latest`. The initial implementation
was checked against Azure MCP 2.0.5: it exposes only the selected inventory tool
and rejects unselected tools. This release does not support the newer
`--disable-proxy-tools` flag; do not add unsupported flags copied from main-branch
documentation. Upgrades require reviewing the actual `tools/list` response.

### Deployment sequence

Keep the target-specific `azure_mcp` settings beside the existing `targets` in
`aifactory/agent-factory/config.json`: `name`, `infrastructure_subnet_id`,
`private_endpoint_subnet_id`, `private_dns_zone_id`, digest-pinned `image`, and
`tools: ["group_resource_list"]`. Set `enableAzureMcpServer` to `"true"` in the
selected environment's variables JSON.

From the central repository, using the Agent Factory operator environment:

```powershell
$config = "C:\path\to\consumer\aifactory\agent-factory\config.json"
python .\usecase_code\40-agent-factory\44-azure-mcp\deploy.py plan --config $config
python .\usecase_code\40-agent-factory\44-azure-mcp\deploy.py prepare-identity --config $config --apply
python .\usecase_code\40-agent-factory\44-azure-mcp\deploy.py validate --config $config
```

Identity preparation requires appropriate Entra directory permissions. It writes
only IDs and readiness information to `azure-mcp-identity.json` beside the config.
Publish the reviewed generic code, update the consumer's submodule from that
commit, and distribute the matching pipeline templates before queuing a build.

For an existing project, register `infra-project-azure-mcp.yaml` as a dedicated
Azure DevOps pipeline for the consumer repository. Its three environment stages
accept the existing reviewed-project contract, but execute **only** MCP deployment:
they do not recreate networking, Foundry capability hosts, ML, AKS or Databricks.
Run the consumer launcher with:

```powershell
$env:AIFACTORY_PROJECT_DEPLOYMENT_SCOPE = "azure-mcp"
& "C:\Program Files\Git\bin\bash.exe" ".\ADO-update-aifactory-and-run-project.sh" --project-only
```

The regular project ADO and GitHub Actions Foundry phases also have a
default-disabled MCP step. Azure CLI deployment uses the exact reviewed
variables file and checks its subscription, project number and environment
against the selected pipeline target. Preparing the directory identity is a
separate operator step; the pipeline does not receive directory-write permissions.

After deployment, from the Agent Factory starter directory:

```powershell
python -m agent_factory configure-azure-mcp --config $config --apply
python -m agent_factory deploy --config $config --apply
# Select each supported hosted agent explicitly; Claude still needs its own model.
python -m agent_factory deploy --config $config --agent aif-helpdesk-team --apply
```

Connection setup checks the live image, flags, identity, private network,
project-scoped Reader assignment and unauthenticated HTTP 401 challenge before
creating the project-MI connection. Hub-policy DNS ownership is preserved; missing
private DNS is a blocker, not a reason to enable public access. Infrastructure
verification alone is not proof of a successful managed-identity tool call:
exercise `group_resource_list` and confirm its actual results before calling
the expansion operational.

## Anthropic template

`aif-anthropic` is implemented but is not deployed in the reference inventory.
It requires a compatible Foundry-hosted Claude deployment and an explicit
`model_overrides.anthropic-agents` selection. It uses the Anthropic Python
Messages SDK, not Claude Code or the Claude Agent SDK, and does not fall back
to the public Anthropic endpoint.

## Implementation and setup

See the [Agent Factory starter](../../../usecase_code/40-agent-factory/readme.md)
for configuration, private networking, data ingestion, deployment commands, and
current Agent Map limitations.
