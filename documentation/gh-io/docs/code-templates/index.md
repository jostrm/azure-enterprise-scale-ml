---
hide:
  - toc
---

# Code templates library: Project team

Start from working code instead of an empty file. Each template runs inside a project of your AI Factory and
uses the services that project already has.

Type in the search box, or select a factory, an Azure service or a tag. Filters of different rows combine:
**Agent Factory** with **Fabric** shows the agent templates that use Fabric. A blue number means the template
has a place on the [architecture images](../architectures.md).

<!-- code-templates:library -->

## Before you run a template

1. Ask your platform team for a project: see [Usage docs](../usage/index.md) and the
   [prerequisites](../usage/prerequisites.md).
2. Check that the project has the services on the card. The [Azure resource library](../resources/index.md)
   names the setting that switches each one on.
3. Open the template and follow its guide. New to the Agent Factory or the Model Factory? Start with
   [Run your first agent](../usage/01-first-agent.md) or [Train your first model](../usage/02-first-ml-model.md).

## Where the templates live

| Folder in `usecase_code` | What it holds |
| --- | --- |
| [`40-agent-factory`](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/usecase_code/40-agent-factory) | The Agent Factory: prompt agents, hosted agents, RAG, voice, MCP and the agents that work with Fabric and Azure Machine Learning. |
| [`50-ml-model-factory`](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/usecase_code/50-ml-model-factory) | The Model Factory: batch, online and streaming examples for each task and technology. The library lists the examples that are tested in Azure. The [use-case tree](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/usecase_code/50-ml-model-factory/usecase-type) has all of them. |
| [`10-azure-function`](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/usecase_code/10-azure-function) | Azure Functions, including the one that runs the six ESAF scenarios. |
| [`20-agent-foundry`](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/usecase_code/20-agent-foundry) | Two starter scripts for Foundry agents, each in one file. |
