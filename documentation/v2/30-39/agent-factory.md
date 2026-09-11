# Agent Factory - Agents and Tools

Agent Factory provides persistent Foundry prompt agents, framework-based hosted
agents, and a hosted multi-agent team. The reference inventory below uses the
default `aif` name prefix; other deployments can configure a different prefix.

## Agent inventory

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
