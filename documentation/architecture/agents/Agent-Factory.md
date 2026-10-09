---
id: agent-factory
status: observed
sources:
  - usecase_code/40-agent-factory/readme.md
  - usecase_code/40-agent-factory/agent_factory/readme.md
  - usecase_code/40-agent-factory/agent_factory/cli.py
  - usecase_code/40-agent-factory/agent_factory/catalog.py
  - usecase_code/40-agent-factory/agent_factory/prompt.py
  - usecase_code/40-agent-factory/agent_factory/hosted.py
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/services.py
tests:
  - usecase_code/40-agent-factory/tests/test_prompt.py
  - usecase_code/40-agent-factory/tests/test_hosted.py
  - usecase_code/40-agent-factory/tests/test_cli.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_services.py
graph_symbols:
  - usecase_code/40-agent-factory/agent_factory/cli.py::function:run
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/services.py::class:AgentServiceFactory
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Agent Factory

## Observed responsibilities

| Component | Responsibility |
|---|---|
| Shared `agent_factory` operator | Explicit target/storage discovery, private-network checks, ingestion/Foundry IQ, prompt and hosted deployment/invocation. |
| Prompt agents | Persistent versioned Foundry definitions with catalogued roles and allowed tools. |
| Hosted examples | Framework-specific runtime and package construction; they are not independent factory provisioning engines. |
| Multi-agent examples | Knowledge/reviewer collaboration pattern; role names alone do not grant additional tools or permissions. |
| `40-aifactory-agent` application | Grounded Factory Chat, exact-scope authorization, existing API adapters and durable human-approved operations. |
| Backend functions | Execute client-side tool implementations. Creating a Foundry definition alone does not host those functions. |

The shared operator and Factory Chat application have separate Python/dependency/configuration boundaries. Parent operator `--apply` conventions are not portable to Chat's immediate `ingest`/`deploy-agent` commands. Offline plans/help do not imply live connectivity; invocation and ingestion can incur model/service charges.

Storage selection is explicit common/project data storage. Changing it does not move the Foundry target, create permission, infer an account by first-match discovery or rewrite historical lake paths.

## Authority boundary

The model can propose or explain; backend authorization determines scope. Platform/Project audience changes explanation, not permissions. A source/knowledge agent and a reviewer cannot approve an infrastructure change merely by agreeing with each other.

Private Azure MCP in `44-azure-mcp` is a separate narrow Azure resource-read integration from this repository's `mcp` Factory API adapter. Neither name implies arbitrary shell access or unrestricted Azure writes.

See [[Chat-and-Grounding]], [[MCP-Boundary]], [[Retrieval-Provenance]], [[Dependency-Injection]], [[System-Context]] and [[Index]].

Authority: [Agent Factory quickstart](../../../usecase_code/40-agent-factory/readme.md), [operator responsibilities](../../../usecase_code/40-agent-factory/agent_factory/readme.md), [agent catalog guide](../../v2/30-39/agent-factory.md).
