# Agent Factory and GenAIOps

The Agent Factory is a set of code templates for prompt agents, hosted agents, multi-agent teams, data
ingestion and RAG. Find them all, with filters, in the [code templates library](../../code-templates/index.md).

## Watch RAG step by step

Follow approved documents through chunking and indexing, then a question through retrieval to a grounded
answer. RAG gives the model your documents as context when a question is asked. The model itself isn't
trained on them.

<picture>
  <source media="(prefers-reduced-motion: reduce)" srcset="../../../assets/animations/rag.png">
  <img src="../../../assets/animations/rag.gif" alt="RAG separates document preparation and indexing from question-time authorized retrieval and grounded answer generation." width="1400" height="940" loading="lazy">
</picture>

[Animated SVG](../../assets/animations/rag.svg) |
[GIF](../../assets/animations/rag.gif) |
[Still image](../../assets/animations/rag.png)

See also [DataOps + RAG and fine-tuning](dataops.md#watch-the-data-flow).

## Choose a starting point

| Example area | Use |
| --- | --- |
| `41-single-agent` | Foundry prompt-agent and supported hosted-framework examples. |
| `42-multi-agent` | A hosted team calling separately persisted knowledge/reviewer agents. |
| `43-data` | Ingestion and retrieval preparation for the selected target. |
| `44-azure-mcp` | A narrow, private read-only Azure tool example. |
| `45-rag-agent` | Explicit source-bound RAG with separate Search and Foundry IQ paths. |

[Open the Agent Factory quickstart](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/40-agent-factory/readme.md),
or follow [Run your first agent](../../usage/01-first-agent.md).

## The project gives you the services, the template gives you the agent

The project pipeline deploys Foundry, Storage, Key Vault, AI Search, Cosmos DB, monitoring and the hosting
services you switched on. Private Foundry agents need AI Search, Cosmos DB and Storage together. You then run
a template to ingest your data and deploy an agent.

The model names, versions, SKUs and capacity of a project are settings. See
[Every variable in variables.json](../../parameters/variables.md).

## RAG and shared data

Choose the source, its version and who may read the answers. Then run the ingestion and connect the index or
the Foundry IQ knowledge base to the agent. To keep the access rights of each document, start from the
template with access control lists in the [library](../../code-templates/index.md).

When you change `use_common_datalake_storage`, copy the data yourself and deploy the agent again.

## Gateways

| Gateway | What it does |
| --- | --- |
| API Management as the AI gateway | Puts one endpoint in front of several model deployments, with load balancing, retries and token limits. |
| Kong | The alternative AI gateway, when your organization runs Kong. |
| Application Gateway | Brings web traffic from your network to an application in a project. |

See the [gateway settings](../../parameters/advanced.md#mcp-and-ai-gateway-parameters) and the
[architecture](../../architectures.md).

Agent Chat and the Factory MCP server are for operating the Factory itself. The agents you build for your
workload are separate, and each runs with its own identity and permissions.

<details markdown="1">
<summary>More info</summary>

[Private RAG example](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/40-agent-factory/45-rag-agent/readme.md) |
[Private Azure MCP](https://github.com/jostrm/azure-enterprise-scale-ml/blob/main/usecase_code/40-agent-factory/44-azure-mcp/readme.md) |
[Monitor and operate](../../intelligence.md)

The private Azure MCP template gives an agent read-only tools for Azure resources. It can't change them.
Model calls and ingestion cost money, so check the quota and the budget of the project before a large run.

</details>
