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
  - usecase_code/40-agent-factory/agent_factory/factory_chat_agent.py
  - usecase_code/40-agent-factory/agent_factory/agent_live_voice.py
  - usecase_code/40-agent-factory/47-aifactory-agent-live-voice/deploy.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/main.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/runtime.py
  - usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/sales_demo/search.py
tests:
  - usecase_code/40-agent-factory/tests/test_prompt.py
  - usecase_code/40-agent-factory/tests/test_hosted.py
  - usecase_code/40-agent-factory/tests/test_cli.py
  - usecase_code/40-agent-factory/40-aifactory-agent/tests/test_services.py
  - usecase_code/40-agent-factory/tests/test_factory_chat_agent.py
  - usecase_code/40-agent-factory/tests/test_agent_live_voice.py
graph_symbols:
  - usecase_code/40-agent-factory/agent_factory/cli.py::function:run
  - usecase_code/40-agent-factory/40-aifactory-agent/aifactory_agent/services.py::class:AgentServiceFactory
reviewed_source: 'd7dc78dc + native voice working tree; observed 2026-10-10; no live deployment asserted'
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
| Factory Chat Agent step (`46-factory-chat-agent`, `enableFactoryChatAgent`) | Opt-in late project-pipeline step that creates or versions the owned Foundry prompt agent from the canonical definition; idempotent by definition hash, never deletes, refuses a foreign owner. |
| Live voice step (`47-aifactory-agent-live-voice`, `enableAIFactoryAgentLiveVoice`) | Opt-in late project-pipeline step for project001 Dev: verifies that owned agent (never creates it), builds the knowledge index and deploys the private chat application with Azure Voice Live using the application's own ownership-checked commands. Voice without the chat flag fails; an app deployed by hand is never replaced; false never deletes. |

The shared operator and Factory Chat application have separate Python/dependency/configuration boundaries. Parent operator `--apply` conventions are not portable to Chat's immediate `ingest`/`deploy-agent` commands. Offline plans/help do not imply live connectivity; invocation and ingestion can incur model/service charges.

Storage selection is explicit common/project data storage. Changing it does not move the Foundry target, create permission, infer an account by first-match discovery or rewrite historical lake paths.

## Authority boundary

The model can propose or explain; backend authorization determines scope. Platform/Project audience changes explanation, not permissions. A source/knowledge agent and a reviewer cannot approve an infrastructure change merely by agreeing with each other.

The application has a compatibility speech shell and an opt-in native Voice Live realtime engine. Both reuse the common prepared-turn grounding/read-tool policy; native streaming is not another privileged agent or an external full-text answer chain. Language profiles and voice mode are operator-owned configuration, not deployment intent from a spoken request. Voice-only failure must not invalidate authenticated text chat. Native streamed speech is provisional until final citation checks (see [[Chat-and-Grounding]]); local tests do not establish the installed live revision.

Private Azure MCP in `44-azure-mcp` is a separate narrow Azure resource-read integration from this repository's `mcp` Factory API adapter. Neither name implies arbitrary shell access or unrestricted Azure writes.

## Split-table sales example

`48-rag-with-splitted-tables-acl-adlsgen2` is a separately configured demonstration,
not a change to the project-wide permissions of example 45. Whole JSON and
normalized workbook text enter Search Text Split before embedding. Native ADLS
permission metadata is projected onto every derived chunk. End-user Search
authorization and delegated structured-source reads remain separate from the
Search/backend service identities.

Exact totals come from complete hash-pinned structured rows, not semantic top-k
results or model arithmetic. Consumer-owned policy selects authorized partitions;
native Search authorization and source access still have to succeed. Independent
evaluation answers are excluded from ingestion and agent tools. A separate
synthetic image-serving branch is necessary because asset stores cannot be
combined with native permission ingestion.

Local fixtures or passing unit tests do not establish three real service chunks,
successful revocation, image use, or a deployed Foundry agent. The example's
README distinguishes measured local results from approval-gated cloud evidence.

See [[Chat-and-Grounding]], [[MCP-Boundary]], [[Retrieval-Provenance]], [[Dependency-Injection]], [[System-Context]] and [[Index]].

Authority: [Agent Factory quickstart](../../../usecase_code/40-agent-factory/readme.md), [operator responsibilities](../../../usecase_code/40-agent-factory/agent_factory/readme.md), [agent catalog guide](../../v2/30-39/agent-factory.md).
